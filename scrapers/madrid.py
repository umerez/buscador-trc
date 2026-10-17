"""TACP Madrid: Tribunal Administrativo de Contratación Pública de la Comunidad de Madrid.

Fuente: buscador Drupal 7 `https://www.comunidad.madrid/tacp/busquedaresoluciones` (GET).

Estrategia (comprobada el 11/10/2026):

- El año se acota con el rango de fechas del buscador (`field_fecha[date]` / `field_fecha_1[date]`,
  dd/mm/aaaa). El buscador devuelve siempre 5 filas por página (`page` empieza en 0); no admite
  `items_per_page` ni ningún otro parámetro para ampliar la página (no está expuesto en el formulario).
  2024 = 488 resoluciones = 98 páginas.
- Cada fila del listado trae: nº de resolución (con enlace a la ficha), fecha, descripción (body)
  y un enlace al PDF del tipo `/tacp/file/NNNN/download?token=...` (funciona sin sesión, 200).
- El listado NO trae recurso, sentido, tipo de contrato, acto recurrido ni procedencia. Esos campos
  solo están en la ficha `/tacp/resolucion/NNNAAAA`, así que `listar()` abre una ficha por registro
  (1 petición por resolución; `fichas=False` lo desactiva y deja solo n, f, d, pdf y url).
  La ficha trae además el PDF con URL directa y estable
  (`/tacp/sites/default/files/...pdf`), que se prefiere al enlace con token del listado.
- `o` (órgano) solo puede rellenarse con la categoría «Procedencia» (Consejerías, Hospitales,
  Municipios/Entidades Locales, Universidades, Otros Poderes Adjudicadores): el tribunal no publica
  el órgano concreto en los metadatos.
- La categoría «Objeto» (Limpieza, TICs, Suministros Médicos...) se añade al final de `d` entre
  paréntesis para que sea buscable.
- Orden inestable (corregido el 17/10/2026): con muchas resoluciones el mismo día (hasta 26) la paginación
  repite unas filas y salta otras, y el contador no cuadra (2026: 508 declaradas, 488 leídas). `listar` lee por
  meses y, si un rango no cuadra con su contador, lo relee y lo parte hasta llegar a un día.
- Trampa: el megamenú trae tres enlaces fijos a resoluciones destacadas (`/tacp/resolucion/...`)
  fuera del `view-content`, y hay un segundo `div.view-content` (bloque lateral) sin filas de
  resolución. Solo se leen los `li.views-row` del `view-content` que contiene
  `views-field-field-numero-de-resolucion`.
- Formato idéntico en 2011-2012 y 2024; solo cambia el nombre del PDF
  (`Resolución-089-2011.pdf` / `resolucion-238-2020.pdf` / `resolucion_400-2025_expediente_375-2025.pdf`).
- Algunas fichas enlazadas desde el listado devuelven 404 (en 2024: 293, 364 y 416; alias roto en el
  propio portal). El registro se queda con los datos del listado (n, f, d, pdf con token) y sin `url`.
- Rodeo a `Sesion`: `Sesion._pedir` reintenta tres veces (con esperas de 2+4+6 s) también los errores
  4xx, que son definitivos. Para las fichas se usa `_get_ficha`, que hace la petición directa con la
  misma pausa y solo delega en `Sesion.texto` (con reintentos) ante errores de red o 5xx.
"""
from __future__ import annotations

import calendar
import logging
import math
import re
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

import requests

from scrapers.base import TIMEOUT, Registro, Sesion, limpiar, numero, fecha_iso, absoluta

log = logging.getLogger("scrapers.madrid")

BASE = "https://www.comunidad.madrid"
BUSCADOR = BASE + "/tacp/busquedaresoluciones"
POR_PAGINA = 5          # fijo en el buscador; no se puede ampliar
MAX_PAGINAS = 400       # cortafuegos contra bucles (ningún año pasa de ~120 páginas)

TRIBUNAL = {
    "id": "madrid",
    "siglas": "TACP Madrid",
    "nombre": "Tribunal Administrativo de Contratación Pública de la Comunidad de Madrid",
    "ambito": "Comunidad de Madrid",
    "buscador": BUSCADOR,
    "idioma": "es",
    "desde": 2011,
    "documento": "Resolución",
}

# Nombres del tribunal → valores normalizados del campo `s`
SENTIDOS = {
    "desestimatoria": "Desestimatoria",
    "estimatoria": "Estimatoria",
    "estimatoria parcial": "Estimación parcial",
    "inadmision": "Inadmisión",
    "inadmisión": "Inadmisión",
    "otros": "Otros",
}

_RE_TOTAL = re.compile(r"(\d+)\s+registros?\s+de\s+(\d+)")


# ---------------------------------------------------------------- listado

def _sopa(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _view_content(soup: BeautifulSoup):
    """El `div.view-content` del listado de resoluciones (no el del bloque lateral ni el megamenú)."""
    for vc in soup.select("div.view-content"):
        if vc.select_one("li.views-row .views-field-field-numero-de-resolucion"):
            return vc
    return None


def _total(vc) -> Optional[int]:
    m = _RE_TOTAL.search(vc.get_text(" ", strip=True))
    return int(m.group(2)) if m else None


def _fila(li, anio: int) -> Optional[Registro]:
    a = li.select_one(".views-field-field-numero-de-resolucion a[href]")
    if a is None:
        return None
    n_txt = limpiar(a.get_text()) or ""
    n = numero(n_txt, anio)
    if not re.search(r"\d", n):
        return None
    url = absoluta(BASE, a["href"])

    f = None
    fecha_el = li.select_one(".views-field-field-fecha .date-display-single")
    if fecha_el is not None:
        f = fecha_iso(fecha_el.get("content") or fecha_el.get_text())
    if f is None:
        fecha_el = li.select_one(".views-field-field-fecha .field-content")
        if fecha_el is not None:
            f = fecha_iso(fecha_el.get_text())

    d = None
    body = li.select_one(".views-field-body .field-content")
    if body is not None:
        d = limpiar(body.get_text(" "))

    pdf = None
    doc = li.select_one(".views-field-field-documento a[href]")
    if doc is not None:
        pdf = absoluta(BASE, doc["href"])

    return Registro(t=TRIBUNAL["id"], n=n, f=f, d=d, pdf=pdf, url=url)


def _dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _pagina(ses: Sesion, anio: int, page: int, ini: Optional[date] = None, fin: Optional[date] = None):
    """Una página del listado. Sin rango explícito, el año entero."""
    params = {
        "field_fecha[date]": _dmy(ini) if ini else f"01/01/{anio}",
        "field_fecha_1[date]": _dmy(fin) if fin else f"31/12/{anio}",
        "page": page,
    }
    html = ses.texto(BUSCADOR, params=params)
    return _sopa(html)


def _leer_paginas(ses: Sesion, anio: int, ini: date, fin: date, acumulado: Dict[str, Registro]):
    """Recorre la paginación del rango [ini, fin] y suma a `acumulado` las filas nuevas. Devuelve el total declarado.

    No corta cuando una página no aporta nada nuevo: con el orden inestable del buscador (muchas resoluciones
    con la misma fecha) una página puede repetir filas y la siguiente traer las que faltaban. Se acota por el total
    declarado (más una página de margen) y por MAX_PAGINAS.
    """
    total: Optional[int] = None
    for page in range(MAX_PAGINAS):
        soup = _pagina(ses, anio, page, ini, fin)
        vc = _view_content(soup)
        if vc is None:
            break
        if total is None:
            total = _total(vc)
        filas = vc.select("li.views-row")
        for li in filas:
            reg = _fila(li, anio)
            if reg is None:
                continue
            acumulado.setdefault(reg.clave(), reg)
        if not filas or len(filas) < POR_PAGINA:
            break
        if total is not None and page + 1 >= math.ceil(total / POR_PAGINA) + 1:
            break
    return total


def _leer_rango(ses: Sesion, anio: int, ini: date, fin: date, incompletos: List[tuple]) -> Dict[str, Registro]:
    """Todas las resoluciones fechadas en [ini, fin].

    El buscador pagina con un orden que no es estable entre peticiones cuando varias resoluciones comparten fecha
    (hasta 26 el mismo día): al leer 5 en 5 se repiten unas y se saltan otras, y el contador no cuadra con lo leído
    (2026: 508 declaradas, 488 leídas). Remedio: si el rango no cuadra con su contador se vuelve a leer (hasta tres
    pasadas en rangos de una semana o menos) y, si sigue sin cuadrar, se parte por la mitad hasta llegar a un día.
    Lo que no se pueda completar en un día se anota en `incompletos` (fecha, leídas, declaradas).
    """
    acumulado: Dict[str, Registro] = {}
    dias = (fin - ini).days
    pasadas = 1 if dias > 7 else 3
    total: Optional[int] = None
    for _ in range(pasadas):
        total = _leer_paginas(ses, anio, ini, fin, acumulado)
        if total is None or len(acumulado) >= total:
            break
    if total is None or len(acumulado) >= total:
        return acumulado
    if dias == 0:
        incompletos.append((ini, len(acumulado), total))
        return acumulado
    mitad = ini + timedelta(days=dias // 2)
    for sub_ini, sub_fin in ((ini, mitad), (mitad + timedelta(days=1), fin)):
        for k, reg in _leer_rango(ses, anio, sub_ini, sub_fin, incompletos).items():
            acumulado.setdefault(k, reg)
    return acumulado


def _meses(anio: int):
    for m in range(1, 13):
        ini = date(anio, m, 1)
        fin = date(anio, m, calendar.monthrange(anio, m)[1])
        yield ini, fin


# ---------------------------------------------------------------- ficha

def _campo(soup: BeautifulSoup, nombre: str) -> List[str]:
    """Valores (uno por `.field-item`) del campo Drupal `field-name-<nombre>`."""
    div = soup.select_one(f"div.field-name-{nombre}")
    if div is None:
        return []
    items = [limpiar(i.get_text(" ")) for i in div.select(".field-item")]
    items = [i for i in items if i]
    if items:
        return items
    # sin .field-item: quitar la etiqueta y quedarse con el resto
    for lab in div.select(".field-label"):
        lab.decompose()
    v = limpiar(div.get_text(" "))
    return [v] if v else []


def _uno(soup: BeautifulSoup, nombre: str) -> Optional[str]:
    vals = _campo(soup, nombre)
    return ", ".join(vals) if vals else None


def _pdf_ficha(soup: BeautifulSoup) -> Optional[str]:
    div = soup.select_one("div.field-name-field-documento")
    if div is None:
        return None
    hrefs = [a["href"] for a in div.select("a[href]")]
    # preferir la URL directa a sites/default/files; después cualquier .pdf; después lo que haya
    for h in hrefs:
        if "/sites/default/files/" in h:
            return absoluta(BASE, h)
    for h in hrefs:
        if h.lower().endswith(".pdf") or "download" in h:
            return absoluta(BASE, h)
    return absoluta(BASE, hrefs[0]) if hrefs else None


def _get_ficha(ses: Sesion, url: str) -> Optional[str]:
    """HTML de la ficha, o None si el servidor responde 4xx (sin reintentos: un 404 es definitivo)."""
    try:
        ses._espera()  # misma pausa que el resto de peticiones
        r = ses.s.get(url, timeout=TIMEOUT)
        if 400 <= r.status_code < 500:
            log.warning("ficha %s: %d", url, r.status_code)
            return None
        if r.status_code < 400:
            if ses.encoding:
                r.encoding = ses.encoding
            return r.text
    except requests.RequestException as e:
        log.warning("ficha %s: %s; reintentando por Sesion", url, e)
    # error de red o 5xx: que Sesion reintente
    try:
        return ses.texto(url)
    except Exception as e:  # noqa: BLE001
        log.warning("ficha %s no disponible: %s", url, e)
        return None


def _completar(reg: Registro, ses: Sesion) -> bool:
    """Abre la ficha y rellena r, s, o, a, c, pdf (y f/d si faltaban). Devuelve False si no se pudo.

    Si la ficha no existe (404) se borra `url` para no enlazar a una página rota.
    """
    if not reg.url:
        return False
    html = _get_ficha(ses, reg.url)
    if html is None:
        reg.url = None
        return False
    soup = _sopa(html)

    exp = _uno(soup, "field-numero-de-expediente")
    if exp:
        reg.r = numero(exp) if re.search(r"\d", exp) else exp

    tipo = _uno(soup, "field-tipo-de-resolucion")
    if tipo:
        reg.s = SENTIDOS.get(tipo.lower(), tipo)

    reg.c = _uno(soup, "field-tipo-contrato") or reg.c
    reg.a = _uno(soup, "field-acto-recurrido") or reg.a
    reg.o = _uno(soup, "field-procedencia") or reg.o

    if not reg.f:
        reg.f = fecha_iso(_uno(soup, "field-fecha"))
    if not reg.d:
        reg.d = _uno(soup, "body")

    objeto = [v for v in _campo(soup, "field-objeto") if v.lower() != "otros"]
    if objeto:
        suf = f"(Objeto: {', '.join(objeto)})"
        if reg.d:
            if suf not in reg.d:
                reg.d = f"{reg.d} {suf}"
        else:
            reg.d = suf

    pdf = _pdf_ficha(soup)
    if pdf:
        reg.pdf = pdf
    return True


# ---------------------------------------------------------------- API

def listar(anio: int, sesion: Optional[Sesion] = None, fichas: bool = True, omitir=None) -> List[Registro]:
    """Devuelve TODAS las resoluciones del año (recorre la paginación de 5 en 5).

    Con `fichas=True` (por defecto) abre la ficha de cada resolución para completar recurso, sentido,
    tipo de contrato, acto recurrido, procedencia y la URL directa del PDF. `[]` si el año no tiene nada.
    """
    ses = sesion or Sesion()
    incompletos: List[tuple] = []
    vistos: Dict[str, Registro] = {}
    for ini, fin in _meses(anio):
        for k, reg in _leer_rango(ses, anio, ini, fin, incompletos).items():
            vistos.setdefault(k, reg)
    registros: List[Registro] = list(vistos.values())
    if not registros:
        log.info("madrid %d: sin resultados", anio)
        return []
    log.info("madrid %d: %d resoluciones leídas", anio, len(registros))

    if incompletos:
        resumen = ", ".join(f"{d.isoformat()} ({leidas}/{decl})" for d, leidas, decl in incompletos[:8])
        log.warning("madrid %d: %d día(s) con menos resoluciones que su contador tras repetir la lectura: %s",
                    anio, len(incompletos), resumen)

    fuera = [r.n for r in registros if not r.n.endswith(f"/{anio}")]
    if fuera:
        # erratas de origen (número con año equivocado o fecha con año equivocado): no son un fallo del scraper
        log.info("madrid %d: %d resoluciones numeradas en otro año (erratas de origen): %s", anio, len(fuera), fuera[:10])

    if fichas:
        for i, reg in enumerate(registros, 1):
            if omitir and reg.clave() in omitir:   # ya indexada: el orquestador conserva sus campos de ficha
                continue
            _completar(reg, ses)
            if i % 50 == 0:
                log.info("madrid %d: %d/%d fichas", anio, i, len(registros))

    return registros


# ---------------------------------------------------------------- CLI

def _main(argv: List[str]) -> int:
    import time
    from collections import Counter

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    anio = int(argv[1]) if len(argv) > 1 else 2024
    sin_fichas = "--sin-fichas" in argv

    ses = Sesion()
    peticiones = {"n": 0}

    def _contar(r, *a, **kw):  # noqa: ARG001
        peticiones["n"] += 1

    ses.s.hooks["response"].append(_contar)

    t0 = time.monotonic()
    regs = listar(anio, ses, fichas=not sin_fichas)
    dt = time.monotonic() - t0

    print(f"\n{TRIBUNAL['siglas']} {anio}: {len(regs)} registros en {peticiones['n']} peticiones ({dt:.0f} s)")
    for r in regs[:3]:
        print("  ", r.limpio())
    if len(regs) > 6:
        print("   ...")
    for r in regs[-3:]:
        print("  ", r.limpio())

    if regs:
        con_pdf = sum(1 for r in regs if r.pdf)
        con_f = sum(1 for r in regs if r.f)
        print(f"con pdf: {con_pdf}/{len(regs)} ({100 * con_pdf / len(regs):.1f} %)   "
              f"con fecha: {con_f}/{len(regs)} ({100 * con_f / len(regs):.1f} %)")
        for campo in ("r", "s", "o", "a", "c"):
            k = sum(1 for r in regs if getattr(r, campo))
            print(f"   {campo}: {k}/{len(regs)}", end="")
        print()
        print("sentidos:", dict(Counter(r.s for r in regs)))

    claves = Counter(r.clave() for r in regs)
    repetidas = {k: v for k, v in claves.items() if v > 1}
    if repetidas:
        print("CLAVES REPETIDAS:", repetidas)
        return 1
    print("claves únicas: OK")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
