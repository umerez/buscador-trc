"""Scraper del Tribunal Administrativo de Contratos Públicos de Navarra (TACPN).

Fuente: listados anuales Liferay `https://portalcontratacion.navarra.es/es/acuerdos-AAAA`
(2013-2026). No hay buscador ni ficha por acuerdo: todo lo que se indexa sale del propio
listado (título, fecha de publicación, materias y botón «Ver» con el PDF).

Paginación: asset publisher de Liferay, 20 ítems por página (`delta` se ignora), parámetro
`_com_liferay_..._INSTANCE_<id>_cur=N` (1-based). El id de instancia del portlet cambia de
un año a otro (P1Z8jxMmBoEr en 2024, ZJOUZ8nAM5pn en 2014, JwTrEOjlDk0s en 2026), así que
no se construye la URL: se sigue el enlace «Siguiente» del HTML. El texto «Mostrando el
intervalo 1 - 20 de 70 resultados.» sirve de tope de seguridad.

Cada ítem es un `div.asset-full-content` con campos `div.field-wrapper-content` etiquetados
«Año», «Título» (`h2.titulo-acuerdos`), «Fecha de publicación», «Materias» y «Url»
(`div.boton-ver a[href]`).

Título: «Acuerdo 78/2024, de 23 de diciembre. Desestimación. Legitimación para …». De ahí
salen `n`, `f` (día y mes del título + año del número; la fecha de publicación del portal
no vale, puede ir meses por detrás), `s` (sentido, cuando la primera frase tras la fecha
es un sentido reconocible) y `d` (el resto del título, con las materias al final). Las
variantes antiguas («de 16 diciembre,», «24 septiembre.», «Estimacion parcial») se toleran.

El número de expediente («Expediente 121/2025») solo consta dentro del PDF: `r` queda vacío.
No hay página propia por acuerdo: `url` queda vacío. Los Acuerdos son la serie principal
del tribunal: `k` vacío.

PDF: href del botón, absoluto y sin el parámetro `?t=` (marca de caché; el servidor responde
igual sin él). Desde 2018 `/documents/880958/{0|1690342}/Acuerdo+N-AAAA.pdf/<uuid>`; en
2013-2017 nombres irregulares (`2013044AcuerdodesestimacionAliaga1.pdf`,
`R19Acuerdodefondoparapublicar.pdf`) y algún enlace al antiguo `www.navarra.es/NR/rdonlyres/`
que hoy devuelve 502. Se indexa lo que publica el listado, sin comprobar cada PDF.

Cada página pesa unos 400 KB y tarda entre 1 y 15 s según el humor del servidor; a veces
corta la conexión (los reintentos de `Sesion` lo absorben).

Uso: `python3 -m scrapers.navarra 2024`.
"""
from __future__ import annotations

import logging
import math
import re
import sys
import time
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from scrapers.base import Registro, Sesion, absoluta, fecha_iso, limpiar, numero, sin_acentos

log = logging.getLogger("scrapers.navarra")

TRIBUNAL = {
    "id": "navarra",
    "siglas": "TACPN",
    "nombre": "Tribunal Administrativo de Contratos Públicos de Navarra",
    "ambito": "Comunidad Foral de Navarra",
    "buscador": "https://portalcontratacion.navarra.es/es/todos-acuerdos",
    "idioma": "es",
    "desde": 2013,
    "documento": "Acuerdo",
}

BASE = "https://portalcontratacion.navarra.es"
POR_PAGINA = 20
MAX_PAGINAS = 60          # tope absoluto por año, por si la paginación se vuelve circular

# «Acuerdo 78/2024, de 23 de diciembre. …» / «Acuerdo 50/2014, de 16 diciembre, …» /
# «Acuerdo 101/2026, 24 septiembre. …» / «Acuerdo 11/2024, 29 de febrero. …»
RE_TITULO = re.compile(
    r"Acuerdo\s+(?P<num>\d{1,4})\s*/\s*(?P<anio>\d{2,4})"
    r"(?:\s*[,.]?\s*(?:de\s+)?(?P<dia>\d{1,2})\s+(?:de\s+)?(?P<mes>[A-Za-zÁÉÍÓÚáéíóú]+)"
    r"(?:\s+de\s+(?P<anio2>\d{4}))?)?"
    r"\s*[,.:;]?\s*(?P<resto>.*)$",
    re.S | re.I,
)
RE_SOLO_NUMERO = re.compile(r"(\d{1,4})\s*/\s*(\d{4})")
RE_TOTAL = re.compile(r"Mostrando el intervalo\s+\d+\s*-\s*\d+\s+de\s+(\d+)\s+resultados", re.I)

# (forma normalizada sin acentos y en minúsculas, forma canónica). Orden: de más larga a más corta.
SENTIDOS = [
    ("estimacion parcial", "Estimación parcial"),
    ("estimacion", "Estimación"),
    ("desestimacion", "Desestimación"),
    ("inadmision parcial", "Inadmisión parcial"),
    ("inadmision", "Inadmisión"),
    ("nulidad de pleno derecho", "Nulidad de pleno derecho"),
    ("nulidad", "Nulidad"),
    ("aceptacion del desistimiento", "Desistimiento"),
    ("aceptacion desistimiento", "Desistimiento"),
    ("desistimiento", "Desistimiento"),
    ("perdida sobrevenida", "Pérdida sobrevenida del objeto"),
    ("rectificacion", "Rectificación"),
    ("archivo", "Archivo"),
]


# ---------------------------------------------------------------- parseo de un ítem

def _campos(item) -> dict:
    """Devuelve {etiqueta: texto} de los `div.field-wrapper-content` de un ítem."""
    campos = {}
    for w in item.select("div.field-wrapper-content"):
        lab = w.find("label")
        if not lab:
            continue
        etiqueta = limpiar(lab.get_text()) or ""
        # texto visible del wrapper sin la etiqueta (los <input hidden> no aportan texto)
        trozos = [t for t in w.find_all(string=True) if t.parent is not lab and t.parent.name != "script"]
        campos[etiqueta] = limpiar(" ".join(trozos))
    return campos


def _sentido_y_resumen(resto: str):
    """Separa el sentido («Desestimación.») del resumen cuando la primera frase es un sentido conocido."""
    resto = (resto or "").strip()
    if not resto:
        return None, None
    m = re.match(r"\s*([^.]+?)\s*(?:\.\s*|$)(.*)$", resto, re.S)
    primera, siguiente = (m.group(1), m.group(2)) if m else (resto, "")
    norm = sin_acentos(primera.lower()).strip(" ,;:")
    for clave, canonico in SENTIDOS:
        if norm == clave or norm.startswith(clave + " "):
            # si la primera frase es solo el sentido, se quita del resumen; si dice algo más, se conserva
            resumen = siguiente if norm == clave else resto
            return canonico, (limpiar(resumen) or None)
    return None, limpiar(resto)


def _fecha(dia: Optional[str], mes: Optional[str], anio: int) -> Optional[str]:
    if not dia or not mes:
        return None
    # fecha_iso() exige el año en la cadena: se compone aquí con el año del número de acuerdo
    return fecha_iso(f"{dia} de {mes} de {anio}")


def _sin_query(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _registro(item, anio: int) -> Optional[Registro]:
    campos = _campos(item)
    h2 = item.select_one("h2.titulo-acuerdos")
    titulo = limpiar(h2.get_text(" ")) if h2 else campos.get("Título")
    if not titulo:
        return None

    m = RE_TITULO.search(titulo)
    if m:
        anio_n = int(m.group("anio"))
        if anio_n < 100:
            anio_n += 2000
        n = f"{int(m.group('num'))}/{anio_n}"
        anio_f = int(m.group("anio2")) if m.group("anio2") else anio_n
        f = _fecha(m.group("dia"), m.group("mes"), anio_f)
        if (m.group("dia") and not f):
            log.warning("fecha no reconocida en «%s»", titulo[:80])
        s, d = _sentido_y_resumen(m.group("resto"))
    else:
        m2 = RE_SOLO_NUMERO.search(titulo)
        if not m2:
            log.warning("título sin número de acuerdo: «%s»", titulo[:100])
            return None
        n = numero(m2.group(0))
        f, s, d = None, None, limpiar(titulo)
        log.warning("título con formato inesperado: «%s»", titulo[:100])

    materias = campos.get("Materias")
    if materias and materias.lower() not in ("materias", "-", "—"):
        d = f"{d} (Materias: {materias})" if d else f"Materias: {materias}"

    a = item.select_one("div.boton-ver a[href]")
    pdf = None
    if a and a["href"].strip() and not a["href"].startswith("javascript"):
        pdf = _sin_query(absoluta(BASE, a["href"]))

    if int(n.split("/")[1]) != anio:
        log.info("listado %d incluye %s", anio, n)

    return Registro(t=TRIBUNAL["id"], n=n, f=f, s=s, d=d, pdf=pdf)


# ---------------------------------------------------------------- paginación

def _siguiente(soup, url_actual: str) -> Optional[str]:
    """URL del enlace «Siguiente» de la paginación del asset publisher, o None en la última página."""
    for a in soup.find_all("a", href=re.compile(r"_cur=\d+")):
        if (limpiar(a.get_text()) or "").lower().startswith("siguiente"):
            url = absoluta(url_actual, a["href"])
            if url != url_actual:
                return url
    return None


def _total(soup) -> Optional[int]:
    t = soup.find(string=RE_TOTAL)
    if t:
        return int(RE_TOTAL.search(t).group(1))
    return None


def listar(anio: int, sesion: Optional[Sesion] = None) -> list:
    """Todos los acuerdos del año publicados en `/es/acuerdos-AAAA`. [] si el año no existe (404)."""
    sesion = sesion or Sesion()
    url = f"{BASE}/es/acuerdos-{anio}"
    registros: list = []
    vistas: set = set()
    claves: set = set()
    total = None
    pagina = 0

    while url and url not in vistas and pagina < MAX_PAGINAS:
        vistas.add(url)
        pagina += 1
        t0 = time.monotonic()
        try:
            html = sesion.texto(url)
        except RuntimeError as e:
            # base.py reintenta también los 404; si el año no existe, se devuelve [] sin fallar
            if pagina == 1 and "404" in str(e):
                log.info("no existe el listado de %d", anio)
                return []
            raise
        soup = BeautifulSoup(html, "lxml")
        if total is None:
            total = _total(soup)
        items = soup.select("div.asset-full-content")
        nuevos = 0
        for item in items:
            r = _registro(item, anio)
            if r is None:
                continue
            k = r.clave()
            if k in claves:
                log.warning("acuerdo repetido en el listado: %s (se conserva el primero)", r.n)
                continue
            claves.add(k)
            registros.append(r)
            nuevos += 1
        log.info("%d pág. %d: %d ítems (%d nuevos), %.1f s, %d KB", anio, pagina, len(items), nuevos,
                 time.monotonic() - t0, len(html) // 1024)
        if not items:
            break
        if total is not None and pagina >= math.ceil(total / POR_PAGINA):
            break
        url = _siguiente(soup, url)

    if total is not None and len(registros) != total:
        log.warning("%d: el listado anuncia %d resultados y se han indexado %d", anio, total, len(registros))
    return registros


# ---------------------------------------------------------------- ejecución directa

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    anio = int(sys.argv[1]) if len(sys.argv) > 1 else 2024

    sesion = Sesion()
    peticiones = {"n": 0}
    _get = sesion.get

    def _get_contando(url, **kw):
        peticiones["n"] += 1
        return _get(url, **kw)

    sesion.get = _get_contando  # type: ignore[assignment]

    t0 = time.monotonic()
    regs = listar(anio, sesion)
    dt = time.monotonic() - t0

    print(f"\n{TRIBUNAL['siglas']} {anio}: {len(regs)} acuerdos en {peticiones['n']} peticiones, {dt:.1f} s")
    for r in regs[:3]:
        print(" ", r.limpio())
    if len(regs) > 6:
        print("  …")
    for r in regs[-3:] if len(regs) > 3 else []:
        print(" ", r.limpio())

    if regs:
        con_pdf = sum(1 for r in regs if r.pdf)
        con_f = sum(1 for r in regs if r.f)
        con_s = sum(1 for r in regs if r.s)
        print(f"\ncon pdf: {con_pdf}/{len(regs)} ({100 * con_pdf / len(regs):.0f} %)  "
              f"con fecha: {con_f}/{len(regs)} ({100 * con_f / len(regs):.0f} %)  "
              f"con sentido: {con_s}/{len(regs)} ({100 * con_s / len(regs):.0f} %)")
        vistas = {}
        for r in regs:
            vistas.setdefault(r.clave(), []).append(r)
        repetidas = {k: v for k, v in vistas.items() if len(v) > 1}
        if repetidas:
            print(f"CLAVES REPETIDAS: {len(repetidas)}")
            for k, v in repetidas.items():
                print("  ", k, [x.pdf for x in v])
        else:
            print("claves repetidas: ninguna")
        fuera = [r.n for r in regs if int(r.n.split('/')[1]) != anio]
        if fuera:
            print(f"acuerdos de otro año en el listado: {fuera}")
