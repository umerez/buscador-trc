"""Tribunal Català de Contractes del Sector Públic (TCCSP).

Fuente: buscador GET (OpenCms) https://contractacio.gencat.cat/ca/contacte/tccsp/cercador-resolucions/index.html
con ``datainf``/``datasup`` (dd/mm/aaaa) para acotar el año.

Comportamiento comprobado el 11/10/2026:

- El listado pagina de 10 en 10 con ``page74bdffe4-cd83-11ea-a60c-005056924a59=N`` (1-based), pero admite
  ``rows=N`` para pedir hasta N resultados de golpe (probado con 500 y 1000: devuelve el año entero, ~900 KB).
  OJO: ``page…`` ignora ``rows`` (con rows=200 las páginas 1, 2 y 3 se solapan), así que no se combinan:
  o una sola petición con ``rows`` grande, o paginación clásica de 10 en 10. Aquí se usa lo primero y,
  si el servidor devolviera menos artículos que el contador «S'han trobat N resultats», se recurre a lo segundo.
- Cada ``<article class='llistat_cerca_avancada'>`` trae: título «Resolució núm. 352/2023, de 31 de maig»
  (o «Acord núm. 18/2026, …»), enlace a la ficha HTML, href del PDF, fecha dd/mm/aaaa y un resumen
  (``div.descripcio``) que empieza por el sentido («Estimació. Exclusió i desert. …»).
- El listado NO trae nº de recurso, administración reclamada ni sentido normalizado: solo la ficha HTML
  («Sentit de la resolució», «Administració reclamada», «Paraula/es clau» y, en el texto,
  «Resolució: 485/2024 (recurs N-2024-0545)»). Por eso ``listar`` abre la ficha de cada registro
  (1 petición por resolución, ~4.100 en 2017-2026). Con ``fichas=False`` se obtiene solo el listado
  (10 peticiones para todo el histórico) con n, f, d, pdf y url.
- En 2017 la ficha no reproduce el texto íntegro (solo un resumen), así que el nº de recurso suele faltar.
- Los «Acord núm. N/AAAA» (desistimientos, archivo…) llevan ``k="acuerdo"``; su ficha no tiene «Sentit».
- Los nombres de PDF cambian por año (``Resolucio-num.-176_2017.pdf``, ``resolucio-num-352-2023.pdf``,
  ``resolucio_num._485_2024.pdf``, acuerdos en ``/resolucions/acords/AAAA/``): se toma siempre el href del listado.
- Cobertura 2017-2026. Años sin resultados: «No s'han trobat resultats.» → ``[]``.
- Solo catalán: ``f`` se toma del ``<span>dd/mm/aaaa</span>``; si faltara, ``fecha_iso`` entiende los meses catalanes.
"""
from __future__ import annotations

import logging
import math
import re
import sys
from typing import Optional

from bs4 import BeautifulSoup

from scrapers.base import Registro, Sesion, limpiar, numero, fecha_iso, absoluta, sin_acentos

log = logging.getLogger("scrapers.cataluna")

TRIBUNAL = {
    "id": "cataluna",
    "siglas": "TCCSP",
    "nombre": "Tribunal Català de Contractes del Sector Públic",
    "ambito": "Cataluña",
    "buscador": "https://contractacio.gencat.cat/ca/contacte/tccsp/cercador-resolucions/index.html",
    "idioma": "ca",
    "desde": 2017,
    "documento": "Resolució",
}

BASE = "https://contractacio.gencat.cat"
BUSCADOR = TRIBUNAL["buscador"]
PARAM_PAGINA = "page74bdffe4-cd83-11ea-a60c-005056924a59"
POR_PAGINA = 10          # tamaño de página cuando se pagina de forma clásica
ROWS_MAX = 1000          # resultados por petición con ``rows`` (el año más largo visto: 488)
MAX_DESCRIPCION = 1200   # el resumen del listado puede ser largo; se recorta para no engordar el índice

# Palabras clave de la ficha → tipo de contrato (c) y acto recurrido (a). Se comparan sin acentos y en minúscula.
_CONTRATOS = {
    "serveis": "Serveis", "servei": "Serveis",
    "obres": "Obres", "obra": "Obres",
    "subministraments": "Subministraments", "subministrament": "Subministraments",
    "concessio de serveis": "Concessió de serveis", "concessio d'obres": "Concessió d'obres",
    "concessio": "Concessió", "acord marc": "Acord marc", "mixt": "Mixt", "privat": "Privat",
    "sistema dinamic d'adquisicio": "Sistema dinàmic d'adquisició",
}
_ACTOS = [
    ("plecs", "Plecs"), ("plec", "Plecs"), ("anunci", "Anunci"), ("adjudicacio", "Adjudicació"),
    ("exclusio", "Exclusió"), ("admissio", "Admissió"), ("desert", "Desert"), ("desistiment de l'organ", "Desistiment"),
    ("renuncia", "Renúncia"), ("modificacio", "Modificació"), ("encarrec", "Encàrrec"), ("rescat", "Rescat"),
    ("formalitzacio", "Formalització"), ("acte de tramit", "Acte de tràmit"), ("valoracio", "Valoració"),
    ("classificacio", "Classificació"), ("baixa anormal", "Baixa anormal"), ("resolucio del contracte", "Resolució del contracte"),
]
# Sentido a partir de la primera frase del resumen, cuando la ficha no lo trae (acuerdos, fichas incompletas).
_SENTIDOS_RESUMEN = re.compile(
    r"^(Estimaci[oó] parcial|Estimaci[oó]|Desestimaci[oó]|Inadmissi[oó]|Acceptaci[oó] del desistiment|"
    r"Desistiment|Arxiu|Rectificaci[oó]|Mesura cautelar|Aclariment)\b", re.I)

_peticiones = 0  # contador de peticiones HTTP de este módulo (para el informe de __main__)


# ---------------------------------------------------------------- HTTP

def _get(sesion: Sesion, url: str, **kw) -> str:
    global _peticiones
    _peticiones += 1
    return sesion.texto(url, **kw)


def _pagina_listado(sesion: Sesion, anio: int, rows: Optional[int] = None, pagina: Optional[int] = None) -> str:
    params = {"datainf": f"01/01/{anio}", "datasup": f"31/12/{anio}"}
    if rows:
        params["rows"] = str(rows)
    if pagina and pagina > 1:
        params[PARAM_PAGINA] = str(pagina)
    return _get(sesion, BUSCADOR, params=params)


# ---------------------------------------------------------------- parseo del listado

def _contador(soup: BeautifulSoup) -> Optional[int]:
    """«S'han trobat <span>488</span> resultats» → 488; «No s'han trobat resultats.» → 0; None si no aparece."""
    p = soup.find("p", class_="txt_result")
    if p is None:
        return 0 if soup.find(string=re.compile(r"No s'han trobat resultats")) else None
    txt = limpiar(p.get_text(" ")) or ""
    if "No s'han trobat" in txt:
        return 0
    m = re.search(r"S'han trobat\s+(\d[\d.]*)\s+resultat", txt)
    return int(m.group(1).replace(".", "")) if m else None


def _articulos(soup: BeautifulSoup):
    return soup.find_all("article", class_="llistat_cerca_avancada")


def _registro_de_articulo(art, anio: int) -> Optional[Registro]:
    enlaces = art.find_all("a", href=True)
    ficha = next((a for a in enlaces if "/cercador-resolucions/resolucio/" in a["href"]), None)
    pdf = next((a for a in enlaces if a["href"].lower().endswith(".pdf")), None)
    titulo = limpiar((ficha or (enlaces[0] if enlaces else None) or art).get("title") or "") \
        or limpiar((ficha.get_text(" ") if ficha else art.get_text(" ")))
    if not titulo:
        return None
    m = re.search(r"(Resoluci[oó]|Acord)\s+n[uú]m\.?\s*(\d{1,4}\s*/\s*\d{2,4})", titulo, re.I)
    if not m:
        log.warning("título no reconocido: %r", titulo)
        return None
    k = "acuerdo" if m.group(1).lower().startswith("acord") else "resolucion"
    n = numero(m.group(2), anio)

    f = None
    for sp in art.find_all("span"):
        t = limpiar(sp.get_text())
        if t and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", t):
            f = fecha_iso(t)
            break
    if not f:
        f = fecha_iso(titulo) or fecha_iso(re.sub(r".*,\s*", "", titulo) + f" de {anio}")

    desc_div = art.find("div", class_="descripcio")
    d = limpiar(desc_div.get_text(" ")) if desc_div else None
    if d and len(d) > MAX_DESCRIPCION:
        d = d[:MAX_DESCRIPCION].rsplit(" ", 1)[0] + "…"

    s = None
    if d:
        ms = _SENTIDOS_RESUMEN.match(d)
        if ms:
            s = ms.group(1)

    return Registro(
        t=TRIBUNAL["id"], n=n, f=f, d=d, s=s, k=k,
        pdf=absoluta(BASE, pdf["href"]) if pdf else None,
        url=absoluta(BASE, ficha["href"]) if ficha else None,
    )


def _listado(sesion: Sesion, anio: int) -> list[Registro]:
    """Todos los artículos del año, en una petición con ``rows`` o, si no cuadra, paginando de 10 en 10."""
    html = _pagina_listado(sesion, anio, rows=ROWS_MAX)
    soup = BeautifulSoup(html, "lxml")
    total = _contador(soup)
    arts = _articulos(soup)
    if total == 0 or (total is None and not arts):
        return []
    if total is not None and len(arts) < total and total > ROWS_MAX:
        html = _pagina_listado(sesion, anio, rows=total + 50)
        soup = BeautifulSoup(html, "lxml")
        arts = _articulos(soup)
    if total is not None and len(arts) < total:
        log.warning("%d: rows=%d devolvió %d de %d; paginando de %d en %d", anio, ROWS_MAX, len(arts), total, POR_PAGINA, POR_PAGINA)
        arts = []
        for pagina in range(1, math.ceil(total / POR_PAGINA) + 1):
            soup = BeautifulSoup(_pagina_listado(sesion, anio, pagina=pagina), "lxml")
            nuevos = _articulos(soup)
            if not nuevos:
                break
            arts.extend(nuevos)

    registros: dict[str, Registro] = {}
    for art in arts:
        reg = _registro_de_articulo(art, anio)
        if reg is None:
            continue
        previo = registros.get(reg.clave())
        if previo is None:
            registros[reg.clave()] = reg
        else:  # mismo número repetido en el listado: completar huecos, no duplicar
            for campo in ("f", "d", "s", "pdf", "url"):
                if not getattr(previo, campo) and getattr(reg, campo):
                    setattr(previo, campo, getattr(reg, campo))
    if total is not None and len(registros) < total:
        log.warning("%d: el contador dice %d y se han obtenido %d registros únicos", anio, total, len(registros))
    return list(registros.values())


# ---------------------------------------------------------------- ficha

def _valor_tras(soup: BeautifulSoup, etiqueta: str) -> Optional[str]:
    """Texto del <p> que contiene <strong>etiqueta</strong>, sin la etiqueta."""
    st = soup.find("strong", string=re.compile(re.escape(etiqueta), re.I))
    if not st or not st.parent:
        return None
    txt = limpiar(st.parent.get_text(" ")) or ""
    txt = re.sub(r"^.*?" + re.escape(etiqueta.rstrip(":")) + r"\s*:?\s*", "", txt, count=1, flags=re.I)
    return limpiar(txt)


def _clasificar_claves(claves: Optional[str]):
    """«Serveis. Estimació. Exclusió. Desert.» → (c, a)."""
    if not claves:
        return None, None
    partes = [sin_acentos(p.strip().lower()) for p in re.split(r"[.;,]", claves) if p.strip()]
    c = None
    actos = []
    for p in partes:
        if c is None and p in _CONTRATOS:
            c = _CONTRATOS[p]
            continue
        for patron, nombre in _ACTOS:
            if p == patron or p.startswith(patron + " "):
                if nombre not in actos:
                    actos.append(nombre)
                break
    return c, (", ".join(actos) or None)


def _completar_con_ficha(sesion: Sesion, reg: Registro) -> None:
    html = _get(sesion, reg.url)
    soup = BeautifulSoup(html, "lxml")
    detalle = soup.find("div", id="detall") or soup

    sentit = _valor_tras(detalle, "Sentit de la resolució:")
    if sentit:
        reg.s = sentit
    admin = _valor_tras(detalle, "Administració reclamada:")
    if admin:
        reg.o = admin
    claves = _valor_tras(detalle, "Paraula/es clau:")
    c, a = _clasificar_claves(claves)
    reg.c = reg.c or c
    reg.a = reg.a or a

    texto = detalle.get_text(" ")
    m = re.search(r"\(\s*recurs\s+(N-\d{4}-\d{1,5})\s*\)", texto) or re.search(r"\b(N-\d{4}-\d{3,5})\b", texto)
    if m:
        reg.r = m.group(1)

    if not reg.pdf:
        a_pdf = detalle.find("a", href=re.compile(r"\.pdf$", re.I))
        if a_pdf:
            reg.pdf = absoluta(BASE, a_pdf["href"])


# ---------------------------------------------------------------- interfaz

def listar(anio: int, sesion: Optional[Sesion] = None, fichas: bool = True) -> list[Registro]:
    """Devuelve TODAS las resoluciones y acuerdos del año.

    ``fichas=True`` (por defecto) abre la ficha HTML de cada registro para rellenar r, o, s, c y a
    (1 petición por registro). Con ``fichas=False`` solo se consulta el listado (n, f, d, s aproximado, pdf, url).
    """
    sesion = sesion or Sesion(encoding="utf-8")
    registros = _listado(sesion, anio)
    if fichas:
        for i, reg in enumerate(registros, 1):
            if not reg.url:
                continue
            try:
                _completar_con_ficha(sesion, reg)
            except Exception as e:  # noqa: BLE001 - una ficha caída no debe tirar el año entero
                log.warning("ficha %s no disponible: %s", reg.url, e)
            if i % 50 == 0:
                log.info("%d: %d/%d fichas", anio, i, len(registros))
    registros.sort(key=lambda r: (r.k or "resolucion", int(r.n.split("/")[0]) if r.n.split("/")[0].isdigit() else 0))
    return registros


if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sin_fichas = "--sin-fichas" in sys.argv
    anio = int(args[0]) if args else 2024
    t0 = time.monotonic()
    regs = listar(anio, fichas=not sin_fichas)
    dt = time.monotonic() - t0
    print(f"{TRIBUNAL['siglas']} {anio}: {len(regs)} registros, {_peticiones} peticiones, {dt:.0f} s"
          + (" (solo listado)" if sin_fichas else ""))
    for r in regs[:3]:
        print(" ", r.limpio())
    if len(regs) > 6:
        print("  ...")
    for r in regs[-3:]:
        print(" ", r.limpio())
    if regs:
        n = len(regs)
        print(f"con pdf: {sum(1 for r in regs if r.pdf) * 100 / n:.1f} %  con fecha: {sum(1 for r in regs if r.f) * 100 / n:.1f} %  "
              f"con recurso: {sum(1 for r in regs if r.r) * 100 / n:.1f} %  con órgano: {sum(1 for r in regs if r.o) * 100 / n:.1f} %  "
              f"con sentido: {sum(1 for r in regs if r.s) * 100 / n:.1f} %  con descripción: {sum(1 for r in regs if r.d) * 100 / n:.1f} %  "
              f"acuerdos: {sum(1 for r in regs if r.k == 'acuerdo')}")
    claves: dict[str, int] = {}
    for r in regs:
        claves[r.clave()] = claves.get(r.clave(), 0) + 1
    repetidas = {k: v for k, v in claves.items() if v > 1}
    print("claves repetidas:", repetidas or "ninguna")
