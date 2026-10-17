"""TARCJA: Tribunal Administrativo de Recursos Contractuales de la Junta de Andalucía.

Fuente: buscador Drupal (Views + Search API) de
https://www.juntadeandalucia.es/organismos/tarc/servicios/resoluciones.html

Estrategia
----------
Una petición GET por página de 50 resultados con el filtro «Entre fechas»
(`date-year=2`, `field_res_num_fecha_fecha_value=AAAA-01-01`,
`field_res_num_fecha_fecha_value_1=AAAA-12-31`, `items_per_page=50`, `page` 0-based).
El filtro «Por año» (`date-year=1`) usa un índice del `<select>` que se desplaza cada
año, así que no se usa. La cabecera `<div class="view-header">N recursos disponibles</div>`
da el total y sirve para calcular las páginas; además se para cuando una página viene vacía.

Qué trae el listado (comprobado el 11/10/2026 sobre 2011, 2012, 2024, 2025 y 2026)
------------------------------------------------------------------------------------
Cada `<li>` de `.view-content` lleva: título con `<a href="PDF">` (el href viene con espacios
y saltos de línea dentro de las comillas), observaciones (resumen de la resolución), fecha
(`<time datetime>`), nº de recurso, tipo de contrato, acto recurrido y tipo de resolución.
Los siete campos están presentes en todas las filas de todos los años (solo las observaciones
vienen vacías en alguna fila de 2026).

- No hay ficha HTML: el título enlaza directamente al PDF. Por tanto `url` queda vacío.
- No hay órgano de contratación en el listado ni en ningún otro sitio accesible: `o` queda vacío.
- `pdf` sale del href del listado (carpeta `/sites/default/files/AAAA-MM/` del mes de subida,
  nombre variable: `Resolucion_271_24_Recurso_255_24.pdf`, `Resolución_106_2026_Recurso_85_2026.pdf`,
  `resolucion_123_12.pdf`, `Resolucion46_0.pdf`...).

Rarezas del repositorio que el módulo absorbe
---------------------------------------------
- Títulos irregulares: «Resolución  460/2026» (doble espacio), «Resolución 680_2025»,
  «Resolución_693_2025_Recurso_624_2025_», «Resoluión_692_2025_Recurso_613_2025»,
  «Resolución 440/2025_IE_3_25» (incidente de ejecución, numerado en la serie principal).
  `numero()` toma siempre el primer número N/AAAA o N_AAAA del título.
- Resoluciones de rectificación / aclaración: tienen serie propia y títulos muy variados
  («Resolución Rectificación 9/2026 (Resolución 377/2026 Recurso 360/2026)»,
  «Resolución de rectificacion_6_2026_(Resolución_349_2026_ Recurso_304_2026)»,
  «Resolución 4_2026_Rectificacion_(Resolución_300_2026_Recurso_254_2026»,
  «Resolución Rectif. - Aclaración 17/2026 Resolución 606/2026 Recurso 576/202»,
  «Resolución Aclaración 14/2026 (Resolución 532/2026_Recurso 502/2026)»). Se marcan con
  `k="rectificacion"`; su `n` es el número que sigue a la palabra clave o, si no lo hay, el
  primero del título; la resolución rectificada se antepone a `d`.
  En cambio «Resolución 395/2025 y Resolución Aclaración 19/2025» o
  «Resolución 433/2025/Resolución-Aclaración 20/2025» (sin la palabra «Recurso» en el título)
  son un único PDF con la resolución principal y su aclaración: se indexan como la resolución
  principal.
- Filas duplicadas: la misma resolución aparece dos veces cuando se ha resubido el PDF
  (`..._0.pdf`, `..._6.pdf`), a veces con fecha distinta (633/2026: 16/09 y 25/09). Se conserva
  una sola, la de fecha más reciente (y, a igualdad, la resubida más tardía).
- Títulos mal tecleados que chocan con otra resolución: «Resolución 463/2024» cuyo PDF es
  `Resolucion_563_24_Recurso_472_24.pdf` (es la 563/2024); «Resolución 614/2025» cuyo PDF es
  `Resolución_714_2025_Recurso_664_2025.pdf` (es la 714/2025). Cuando dos registros con
  distinto recurso comparten clave, se recupera el número del nombre del PDF para el que no
  coincide con su título.
- Fechas erróneas: «Resolución 46/2020» está fechada el 11/02/2010, así que el filtro por fechas
  no la devuelve en 2020. Para el primer año de cobertura (2011) el rango inferior se abre a
  1990-01-01 para recoger esos extraviados. No se corrige `n` ni `f`.
- La paginación de Drupal con `page` fuera de rango devuelve la cabecera y cero filas; un año
  sin resoluciones (2027) no devuelve ni cabecera.
"""
from __future__ import annotations

import logging
import math
import re
import sys
from typing import Optional
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from scrapers.base import Registro, Sesion, absoluta, fecha_iso, limpiar, numero

log = logging.getLogger("scrapers.andalucia")

TRIBUNAL = {
    "id": "andalucia",
    "siglas": "TARCJA",
    "nombre": "Tribunal Administrativo de Recursos Contractuales de la Junta de Andalucía",
    "ambito": "Comunidad Autónoma de Andalucía",
    "buscador": "https://www.juntadeandalucia.es/organismos/tarc/servicios/resoluciones.html",
    "idioma": "es",
    "desde": 2011,
    "documento": "Resolución",
}

URL = TRIBUNAL["buscador"]
POR_PAGINA = 50
MAX_PAGINAS = 100          # tope de seguridad: ningún año llega a 5.000 resoluciones

_RE_TOTAL = re.compile(r"(\d+)\s+recursos?\s+disponibles?", re.I)
_RE_KW = re.compile(r"rectif\w*\.?|aclaraci\w*", re.I)
_RE_KW_NUM = re.compile(r"(?:rectif\w*\.?|aclaraci\w*)[\s_\-–.]*(\d{1,4})[\s_/\-]+(\d{2,4})", re.I)
# solo letras tras «resolu» ([^\W\d_]): \w incluiría dígitos y «_» y se tragaría «Resolucion_563_24_Recurso_47» → «2/24»
_RE_RESOL_NUM = re.compile(r"resolu[^\W\d_]*[\s_\-]*(\d{1,4})[\s_/\-]+(\d{2,4})", re.I)
_RE_SUFIJO_RESUBIDA = re.compile(r"_(\d+)\.pdf$", re.I)


# ---------------------------------------------------------------- parseo

def _campo(li, clase: str) -> Optional[str]:
    div = li.select_one(f"div.views-field-{clase} .field-content")
    return limpiar(div.get_text(" ")) if div else None


def _num_pdf(pdf: Optional[str], anio: int) -> Optional[str]:
    """Número de resolución según el nombre del fichero PDF ('Resolucion_563_24_Recurso_472_24.pdf' → '563/2024')."""
    if not pdf:
        return None
    nombre = unquote(urlsplit(pdf).path.rsplit("/", 1)[-1])
    m = _RE_RESOL_NUM.search(nombre)
    if not m:
        return None
    return numero(f"{m.group(1)}/{m.group(2)}", anio)


def _parsear_titulo(titulo: str, anio: int) -> tuple[str, Optional[str], Optional[str]]:
    """Devuelve (n, k, resolución rectificada) a partir del título del listado."""
    es_rect = bool(_RE_KW.search(titulo)) and re.search(r"recurso", titulo, re.I) is not None
    if not es_rect:
        return numero(titulo, anio), None, None
    m = _RE_KW_NUM.search(titulo)
    n = numero(f"{m.group(1)}/{m.group(2)}", anio) if m else numero(titulo, anio)
    principal = None
    for mm in _RE_RESOL_NUM.finditer(titulo):
        cand = numero(f"{mm.group(1)}/{mm.group(2)}", anio)
        if cand != n:
            principal = cand
            break
    return n, "rectificacion", principal


def _parsear_pagina(html: str, anio: int) -> tuple[list[Registro], Optional[int]]:
    sopa = BeautifulSoup(html, "lxml")
    total = None
    cab = sopa.select_one(".view-header")
    if cab:
        m = _RE_TOTAL.search(cab.get_text(" "))
        if m:
            total = int(m.group(1))
    registros: list[Registro] = []
    contenido = sopa.select_one(".view-content")
    if not contenido:
        return registros, total
    for li in contenido.select("li"):
        a = li.select_one("div.views-field-title a")
        if not a:
            continue
        titulo = limpiar(a.get_text(" ")) or ""
        href = (a.get("href") or "").strip()
        pdf = requote_uri(absoluta(URL, href)) if href else None
        n, k, principal = _parsear_titulo(titulo, anio)
        if not n:
            log.warning("título sin número: %r", titulo)
            continue
        # año mal tecleado en el título («Resolución 5/2005» con PDF Resolucion_5_25_Recurso_625_24.pdf):
        # si el título no es del año consultado y el nombre del PDF sí, manda el PDF
        if k is None and not n.endswith(f"/{anio}"):
            n_pdf = _num_pdf(pdf, anio)
            if n_pdf and n_pdf.endswith(f"/{anio}"):
                log.info("título %r corregido a %s por el nombre del PDF", titulo, n_pdf)
                n = n_pdf
        fecha = None
        t = li.select_one("div.views-field-field-res-num-fecha-fecha time")
        if t is not None:
            fecha = fecha_iso(t.get("datetime")) or fecha_iso(t.get_text(" "))
        if not fecha:
            fecha = fecha_iso(_campo(li, "field-res-num-fecha-fecha"))
        recurso = _campo(li, "field-expediente-oc")
        if recurso:
            recurso = re.sub(r"^recurso\s+", "", recurso, flags=re.I)
        d = _campo(li, "field-observaciones")
        if k == "rectificacion" and principal:
            d = f"Rectificación de la Resolución {principal}. {d}" if d else f"Rectificación de la Resolución {principal}."
        registros.append(Registro(
            t=TRIBUNAL["id"],
            n=n,
            f=fecha,
            r=recurso,
            s=_campo(li, "field-tarc-tipo-de-resolucion"),
            d=d,
            a=_campo(li, "field-tarc-acto-recurrido"),
            c=_campo(li, "field-tarc-tipo-contrato"),
            k=k,
            pdf=pdf,
        ))
    return registros, total


# ---------------------------------------------------------------- deduplicación

def _sufijo_resubida(pdf: Optional[str]) -> int:
    m = _RE_SUFIJO_RESUBIDA.search(unquote(pdf or ""))
    return int(m.group(1)) if m else -1


def _recurso_pdf(pdf: Optional[str]) -> Optional[str]:
    """Número de recurso que lleva el nombre del PDF ('..._Recurso_368_2026.pdf' → '368/2026')."""
    if not pdf:
        return None
    m = re.search(r"recurso[\s_\-]*(\d{1,4})[\s_/\-]+(\d{2,4})", unquote(urlsplit(pdf).path.rsplit("/", 1)[-1]), re.I)
    return numero(f"{m.group(1)}/{m.group(2)}") if m else None


def _coherencia(r: Registro, anio: int) -> int:
    """2 si el nombre del PDF coincide con el número y con el recurso del título; 1 si solo con el número; 0 si no."""
    if _num_pdf(r.pdf, anio) != r.n:
        return 0
    rp = _recurso_pdf(r.pdf)
    return 2 if (rp is None or r.r is None or rp == numero(r.r)) else 1


def _deduplicar(registros: list[Registro], anio: int) -> list[Registro]:
    """Quita filas repetidas (resubidas del mismo PDF) y corrige títulos mal tecleados usando el nombre del PDF.

    Una clave solo puede salir una vez. Entre filas con la misma clave se prefiere la que cuadra con su PDF (número
    y recurso); si hay recursos distintos, las que no ganan se reubican en el número que dice su PDF cuando ese
    número está libre en todo el listado (el título estaba mal) y, si no, se descartan avisando con detalle.
    """
    por_clave: dict[str, list[Registro]] = {}
    for r in registros:
        por_clave.setdefault(r.clave(), []).append(r)

    ocupadas = set(por_clave)          # claves presentes en el listado (para saber qué números del PDF están libres)
    salida: dict[str, Registro] = {}
    huerfanas: list[Registro] = []
    for clave, grupo in por_clave.items():
        por_recurso: dict[Optional[str], list[Registro]] = {}
        for g in grupo:
            por_recurso.setdefault(g.r, []).append(g)
        candidatas: list[Registro] = []
        for lote in por_recurso.values():
            # resubidas del mismo PDF: gana la que cuadra con su nombre de fichero, luego la fecha y la resubida más tardía
            lote.sort(key=lambda x: (_coherencia(x, anio), x.f or "", _sufijo_resubida(x.pdf)), reverse=True)
            if len(lote) > 1:
                log.info("duplicado %s (%d filas), me quedo con %s", clave, len(lote), lote[0].pdf)
            candidatas.append(lote[0])
        candidatas.sort(key=lambda x: (_coherencia(x, anio), x.f or ""), reverse=True)
        salida[clave] = candidatas[0]
        huerfanas.extend(candidatas[1:])

    for g in huerfanas:
        n_pdf = _num_pdf(g.pdf, anio)
        if g.k is None and n_pdf and n_pdf != g.n:
            nuevo = Registro(**{**g.__dict__, "n": n_pdf})
            if nuevo.clave() not in ocupadas:
                log.info("título %r corregido a %s por el nombre del PDF %s", g.n, n_pdf, g.pdf)
                ocupadas.add(nuevo.clave())
                salida[nuevo.clave()] = nuevo
                continue
        log.warning("clave repetida con recursos distintos sin arreglo posible: %s; se descarta la fila con recurso %s y PDF %s",
                    g.clave(), g.r, (g.pdf or "").rsplit("/", 1)[-1])
    return list(salida.values())


# ---------------------------------------------------------------- interfaz

def listar(anio: int, sesion: Optional[Sesion] = None) -> list[Registro]:
    """Devuelve TODAS las resoluciones del año (recorre la paginación). [] si el año no existe."""
    s = sesion or Sesion()
    desde = f"{anio}-01-01" if anio > TRIBUNAL["desde"] else "1990-01-01"
    params = {
        "date-year": "2",
        "field_res_num_fecha_fecha_value": desde,
        "field_res_num_fecha_fecha_value_1": f"{anio}-12-31",
        "items_per_page": str(POR_PAGINA),
        "page": "0",
    }
    registros: list[Registro] = []
    paginas = None
    pagina = 0
    while pagina < MAX_PAGINAS:
        params["page"] = str(pagina)
        html = s.texto(URL, params=params)
        filas, total = _parsear_pagina(html, anio)
        if paginas is None and total is not None:
            paginas = max(1, math.ceil(total / POR_PAGINA))
            log.info("%s %d: %d resoluciones en %d páginas", TRIBUNAL["siglas"], anio, total, paginas)
        if not filas:
            break
        registros.extend(filas)
        pagina += 1
        if paginas is not None and pagina >= paginas:
            break
    registros = _deduplicar(registros, anio)
    registros.sort(key=lambda r: (r.k or "", int(r.n.split("/")[0]) if r.n.split("/")[0].isdigit() else 0))
    return registros


if __name__ == "__main__":
    import time
    from collections import Counter

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    anio = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    ses = Sesion()
    peticiones = [0]
    _get = ses.get

    def _contar(url, **kw):
        peticiones[0] += 1
        return _get(url, **kw)
    ses.get = _contar  # type: ignore[method-assign]

    t0 = time.monotonic()
    regs = listar(anio, ses)
    dt = time.monotonic() - t0
    print(f"{TRIBUNAL['siglas']} {anio}: {len(regs)} registros en {peticiones[0]} peticiones ({dt:.1f} s)")
    for r in regs[:3]:
        print(" ", r.limpio())
    print("  ...")
    for r in regs[-3:]:
        print(" ", r.limpio())
    if regs:
        con_pdf = sum(1 for r in regs if r.pdf)
        con_fecha = sum(1 for r in regs if r.f)
        print(f"con pdf: {con_pdf}/{len(regs)} ({100 * con_pdf / len(regs):.1f} %); "
              f"con fecha: {con_fecha}/{len(regs)} ({100 * con_fecha / len(regs):.1f} %)")
        print("clases:", dict(Counter(r.k or "resolucion" for r in regs)))
        for campo in ("r", "s", "o", "d", "a", "c", "url"):
            print(f"  {campo}: {sum(1 for r in regs if getattr(r, campo))}")
    repetidas = [k for k, v in Counter(r.clave() for r in regs).items() if v > 1]
    print("claves repetidas:", repetidas or "ninguna")
