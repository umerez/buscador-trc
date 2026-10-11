"""OARC / KEAO: Órgano Administrativo de Recursos Contractuales de la Comunidad Autónoma de Euskadi.

Fuentes (todas por GET, sin navegador ni captcha; verificadas el 11/10/2026):

1. Catálogo completo de Open Data Euskadi (un solo GET de ~3,4 MB con los ~2.650 registros 2011-2026),
   cacheado a nivel de módulo:
       https://opendata.euskadi.eus/contenidos/ds_juridicos/resoluciones_oarc/opendata/documentacion.json
   Trae: documentName (objeto, completo), legalDocTitle (objeto truncado a 250), documentDescription
   (resumen, solo 2011-2014), contractingAuthority, legalDocResolutionDate, legalDocPublishDate,
   physicalUrl (ficha) y dataXML. NO trae nº de resolución (se saca del slug `{N}_{AAAA}` de la
   physicalUrl), ni sentido, ni nº de expediente, ni acto recurrido, ni URL del PDF.

2. JSON anual del buscador del propio OARC (un GET por año, ~300 KB), cacheado por año:
       https://www.contratacion.euskadi.eus/webkpe00-kpeoarc/es/y96aResolucionesWar/busqueda/buscarListado?anio=AAAA&idSubcriterio=
   Trae numResolucion («001/2024»), fechaResolucion, sentidoResolucionDesc, resumenResolucion,
   poderAdjudicadorDesc, objContrato y urlFichaResolucion. numExp y tipoActoRec vienen siempre a null.
   Se usa para rellenar `s` (sentido) y el resumen de `d`, para arbitrar fechas con errata y para
   añadir las resoluciones que aún no están en Open Data (el catálogo va unas semanas por detrás).
   Si falla, el scraper sigue solo con el catálogo.

3. dataXML de cada registro (una petición por resolución) SOLO para los años <= ANIO_XML_HASTA (2014):
   en 2011-2014 el nombre del PDF es irregular («Resolución 11_2012.pdf» con tilde y espacio, a veces
   fuera de `adjuntos/`) y la única forma segura de conocerlo es leer el XML. Son ~400 peticiones
   (unos 4 minutos con la pausa de Sesion), y son años cerrados: se hace una vez. Desde 2015 el PDF
   es siempre `.../{N}_{AAAA}/es_def/adjuntos/Resolucion{N}_{AAAA}.pdf` y se construye sin petición.

PDF en euskera (`p2`): `.../{N}_{AAAA}/eu_def/adjuntos/Erabakia{N}_{AAAA}.pdf` existe desde mediados de
2019 (ver P2_DESDE); antes no hay versión en euskera con nombre predecible y se deja vacío.

Lo que no se puede rellenar con estas fuentes: `r` (nº de expediente «EB 2023/260»; ninguna de las
tres fuentes lo trae) y `c` (tipo de contrato). `a` (acto recurrido) se deduce del primer segmento
del resumen («Adjudicación. Desestimación. ...» -> «Adjudicación»), que el OARC redacta con ese patrón.
"""
from __future__ import annotations

import html as _html
import logging
import re
import sys
from datetime import date
from typing import Optional
from xml.etree import ElementTree as ET

import requests

from scrapers.base import Registro, Sesion, limpiar, numero, fecha_iso, absoluta, sin_acentos

log = logging.getLogger("scrapers.oarc")

TRIBUNAL = {
    "id": "oarc",
    "siglas": "OARC/KEAO",
    "nombre": "Órgano Administrativo de Recursos Contractuales de la Comunidad Autónoma de Euskadi "
              "/ Kontratuen inguruko Errekurtsoen Administrazio Organoa",
    "ambito": "Comunidad Autónoma de Euskadi",
    "buscador": "https://www.contratacion.euskadi.eus/webkpe00-kpeoarc/es/y96aResolucionesWar/busqueda/listado",
    "idioma": "es/eu",
    "desde": 2011,
    "documento": "Resolución",
}

URL_CATALOGO = "https://opendata.euskadi.eus/contenidos/ds_juridicos/resoluciones_oarc/opendata/documentacion.json"
URL_ANUAL = ("https://www.contratacion.euskadi.eus/webkpe00-kpeoarc/es/y96aResolucionesWar/"
             "busqueda/buscarListado?anio={anio}&idSubcriterio=")
BASE_CONTENIDOS = "https://www.euskadi.eus/contenidos/resolucion_oarc/"

ANIO_XML_HASTA = 2014        # hasta este año (incluido) se lee el dataXML para conocer el PDF
P2_DESDE = (2019, 10)        # (año, nº) de la primera resolución con PDF en euskera «Erabakia{N}_{AAAA}.pdf» (HEAD: 9/2019 no, 10/2019 sí)
MAX_D = 300                  # longitud máxima de la descripción
XML_ANTIGUOS = True          # __main__ --sin-xml lo pone a False (solo para pruebas rápidas)

SENTIDOS = {
    "estimatoria parcial": "Estimación parcial",
    "estimatoria": "Estimatoria",
    "desestimatoria": "Desestimatoria",
    "inadmisión": "Inadmisión",
    "inadmision": "Inadmisión",
    "desistimiento": "Desistimiento",
    "procedimiento concluso": "Procedimiento concluso",
}
# primeros segmentos del resumen que NO son el acto recurrido sino el sentido u otra cosa
_NO_ACTO = {"", "estimacion", "estimacion parcial", "desestimacion", "inadmision", "inadmision fuera de plazo",
            "procedimiento concluso", "resolucion", "escrito", "estimacion total"}

# palabras que delatan un acto recurrido en el primer segmento del resumen (sin acentos, minúsculas)
_RE_ACTO = re.compile(r"adjudicaci|pliego|exclusi|anuncio|admisi|propuesta|acuerdo|informe|acta\b|desistimiento|"
                      r"renuncia|declaraci|formalizaci|modificaci|convenio|encargo|solicitud|escrito|nulidad|"
                      r"incidente|valoraci|desiert|tramite|licitaci|mesa|requerimiento|oferta|contrato|rescate|"
                      r"resolucion|notificaci|clasificaci|puntuaci|penalidad|prorroga|cesion|subrogaci")
_RE_SLUG = re.compile(r"resolucion_oarc/([^/]+)/")
_RE_N_AAAA = re.compile(r"^(\d{1,4})_(\d{4})$")
_RE_EB = re.compile(r"eb_(\d{4})_(\d{1,4})", re.I)

# ---------------------------------------------------------------- cachés de módulo
_CATALOGO: Optional[list] = None
_ANUAL: dict = {}            # anio -> {slug: item} (o {} si el JSON anual falló)
_AVISADOS: set = set()       # slugs raros ya avisados (el catálogo se recorre entero en cada listar())


def _sesion(sesion: Optional[Sesion]) -> Sesion:
    return sesion or Sesion()


def catalogo(sesion: Optional[Sesion] = None) -> list:
    """Descarga el catálogo de Open Data una sola vez por proceso."""
    global _CATALOGO
    if _CATALOGO is None:
        log.info("OARC: descargando catálogo Open Data (%s)", URL_CATALOGO)
        datos = _sesion(sesion).json(URL_CATALOGO)
        if not isinstance(datos, list):
            raise RuntimeError("OARC: el catálogo Open Data no es una lista")
        _CATALOGO = datos
        log.info("OARC: catálogo con %d registros", len(datos))
    return _CATALOGO


def anual(anio: int, sesion: Optional[Sesion] = None) -> dict:
    """JSON anual del buscador del OARC, indexado por slug `N_AAAA`. {} si no se pudo obtener."""
    if anio not in _ANUAL:
        indice: dict = {}
        try:
            datos = _sesion(sesion).json(URL_ANUAL.format(anio=anio))
            for it in datos if isinstance(datos, list) else []:
                slug = _slug(it.get("urlFichaResolucion") or "")
                if not slug:
                    n = numero(it.get("numResolucion") or "", anio)
                    if "/" in n:
                        slug = n.replace("/", "_")
                if slug:
                    indice[slug] = it
        except Exception as e:  # noqa: BLE001 - complemento opcional
            log.warning("OARC: sin JSON anual de %d (%s); se sigue solo con el catálogo", anio, e)
        _ANUAL[anio] = indice
    return _ANUAL[anio]


# ---------------------------------------------------------------- helpers

def _slug(url: str) -> Optional[str]:
    m = _RE_SLUG.search(url or "")
    return m.group(1) if m else None


def _num_anio(slug: str, fecha_txt: Optional[str]) -> Optional[tuple]:
    """(N, AAAA) a partir del slug `100_2024`, `resolucion_eb_2012_071`...

    Si el año del slug es imposible (p. ej. `68_2104`), se toma el de la fecha.
    """
    hoy = date.today().year
    m = _RE_N_AAAA.match(slug)
    if m:
        n, an = int(m.group(1)), int(m.group(2))
    else:
        m = _RE_EB.search(slug)
        if not m:
            return None
        an, n = int(m.group(1)), int(m.group(2))
    if not (TRIBUNAL["desde"] <= an <= hoy + 1):
        m2 = re.search(r"(\d{4})\s*$", fecha_txt or "")
        if m2 and TRIBUNAL["desde"] <= int(m2.group(1)) <= hoy + 1:
            if slug not in _AVISADOS:
                _AVISADOS.add(slug)
                log.warning("OARC: slug %s con año imposible; se usa el de la fecha %s", slug, fecha_txt)
            an = int(m2.group(1))
        else:
            return None
    return n, an


def _fecha(f_cat: Optional[str], f_anual: Optional[str], an: int, slug: str) -> Optional[str]:
    """Fecha ISO. Si el año de la fecha del catálogo no es el del número, se prefiere la del
    buscador anual (si coincide) y, si no, se corrige el año al del número."""
    iso = fecha_iso(f_cat)
    if iso and iso.startswith(f"{an:04d}-"):
        return iso
    iso2 = fecha_iso(f_anual)
    if iso2 and iso2.startswith(f"{an:04d}-"):
        if f_cat:
            log.warning("OARC: fecha %r de %s no cuadra con el número; se usa la del buscador %s", f_cat, slug, iso2)
        return iso2
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", f_cat or "")
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        try:
            corregida = date(an, mo, d).isoformat()
            log.warning("OARC: fecha %r de %s con año erróneo; corregida a %s", f_cat, slug, corregida)
            return corregida
        except ValueError:
            pass
    return iso or iso2


def _sentido(s: Optional[str]) -> Optional[str]:
    s = limpiar(s)
    if not s:
        return None
    return SENTIDOS.get(s.lower(), s)


def _acto(resumen: Optional[str]) -> Optional[str]:
    """Acto recurrido deducido del resumen, que el OARC encabeza con él: «Adjudicación. Desestimación. ...»
    -> «Adjudicación»; «Adjudicación; motivación...» -> «Adjudicación». Si el primer segmento es el sentido
    («Estimación. Adjudicación. ...»), se mira el segundo. Nada si no hay un segmento corto reconocible."""
    if not resumen:
        return None
    segs = re.split(r"\./?\s+|\.(?=[A-ZÁÉÍÓÚ])|\.$|:\s|;\s", resumen.strip(), maxsplit=2)
    for seg in segs[:2]:
        seg = seg.strip(" \"'«»“”¿?/")
        if not seg or len(seg) > 60:
            return None
        plano = sin_acentos(seg.lower())
        if plano in _NO_ACTO:
            continue
        if _RE_ACTO.search(plano):
            return seg
        return None
    return None


def _recortar(s: str, n: int = MAX_D) -> str:
    if len(s) <= n:
        return s
    corte = s[: n - 1].rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:.") + "…"


def _descripcion(objeto: Optional[str], resumen: Optional[str]) -> Optional[str]:
    objeto = limpiar(objeto)
    resumen = limpiar(resumen)
    if objeto and resumen:
        return _recortar(f"{objeto.rstrip('.')}. {resumen}")
    return _recortar(objeto or resumen) if (objeto or resumen) else None


def _pdf_construido(n: int, an: int) -> str:
    return f"{BASE_CONTENIDOS}{n}_{an}/es_def/adjuntos/Resolucion{n}_{an}.pdf"


def _p2(n: int, an: int) -> Optional[str]:
    if (an, n) >= P2_DESDE:
        return f"{BASE_CONTENIDOS}{n}_{an}/eu_def/adjuntos/Erabakia{n}_{an}.pdf"
    return None


def _pdf_desde_xml(slug: str, url_xml: str, sesion: Sesion) -> Optional[str]:
    """Lee el dataXML del registro y devuelve la URL canónica (y bien codificada) del PDF.

    El <url> puede venir relativo (`adjuntos/Resolucion135_2013.pdf`), absoluto
    (`/contenidos/resolucion_oarc/1_2013/es_def/adjuntos/Resolución 1_2013.pdf`), con entidades
    (`Resoluci&oacute;n`) o fuera de `adjuntos/` (`.../es_def/Resolución 104_2012.pdf`).
    """
    try:
        r = sesion.get(url_xml)
    except Exception as e:  # noqa: BLE001
        log.warning("OARC: sin dataXML de %s (%s)", slug, e)
        return None
    href = None
    try:
        root = ET.fromstring(r.content)
        el = root.find(".//legalDocBibliography/link/url")
        if el is not None and el.text:
            href = el.text.strip()
    except ET.ParseError:
        pass
    if not href:
        txt = r.content.decode("iso-8859-1", "replace")
        m = re.search(r"<url>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</url>", txt)
        href = m.group(1).strip() if m else None
    if not href:
        log.warning("OARC: el dataXML de %s no trae <url> del PDF", slug)
        return None
    base = f"{BASE_CONTENIDOS}{slug}/es_def/"
    url = absoluta(base, _html.unescape(href))
    # normaliza dobles barras («/es_def//contenidos/...») y host alternativo
    url = re.sub(r"(?<!:)//+", "/", url)
    url = url.replace("https://www.contratacion.euskadi.eus/contenidos/", BASE_CONTENIDOS[: -len("resolucion_oarc/")])
    return requests.utils.requote_uri(url)


# ---------------------------------------------------------------- principal

def listar(anio: int, sesion: Optional[Sesion] = None) -> list:
    """Todas las resoluciones del año: catálogo Open Data + JSON anual del buscador (ver docstring del módulo)."""
    sesion = _sesion(sesion)
    cat = catalogo(sesion)
    an_idx = anual(anio, sesion)

    candidatos: dict = {}   # clave -> (prioridad, slug, Registro)
    vistos: set = set()

    def _anadir(reg: Registro, slug: str, n: int, an: int):
        prio = 0 if slug == f"{n}_{an}" else 1   # slug canónico gana al duplicado raro
        clave = reg.clave()
        if clave in candidatos:
            log.warning("OARC: %s duplicada en el catálogo (slugs %s y %s); se conserva el canónico",
                        reg.n, candidatos[clave][1], slug)
            if prio < candidatos[clave][0]:
                candidatos[clave] = (prio, slug, reg)
        else:
            candidatos[clave] = (prio, slug, reg)

    # 1) catálogo Open Data
    for it in cat:
        slug = _slug(it.get("physicalUrl") or "")
        if not slug:
            continue
        f_cat = it.get("legalDocResolutionDate") or ""
        na = _num_anio(slug, f_cat)
        if not na:
            log.warning("OARC: slug no reconocido %s", slug)
            continue
        n, an = na
        if an != anio:
            continue
        vistos.add(slug)
        a_it = an_idx.get(f"{n}_{an}") or an_idx.get(slug) or {}

        objeto = limpiar(it.get("documentName")) or limpiar(it.get("legalDocTitle"))
        if (not objeto or "?" in objeto) and limpiar(a_it.get("objContrato")):
            objeto = limpiar(a_it.get("objContrato"))   # el catálogo pierde las comillas tipográficas («?»)
        resumen = limpiar(a_it.get("resumenResolucion")) or limpiar(it.get("documentDescription"))

        if an <= ANIO_XML_HASTA and XML_ANTIGUOS and it.get("dataXML"):
            pdf = _pdf_desde_xml(slug, it["dataXML"], sesion)
        elif an <= ANIO_XML_HASTA:
            pdf = None
        else:
            pdf = _pdf_construido(n, an)

        reg = Registro(
            t=TRIBUNAL["id"],
            n=numero(f"{n}/{an}"),
            f=_fecha(f_cat, a_it.get("fechaResolucion"), an, slug),
            s=_sentido(a_it.get("sentidoResolucionDesc")),
            o=limpiar(it.get("contractingAuthority")) or limpiar(a_it.get("poderAdjudicadorDesc")),
            d=_descripcion(objeto, resumen),
            a=_acto(resumen),
            pdf=pdf,
            p2=_p2(n, an) if pdf and "/eu_def/" not in pdf else None,
            url=f"{BASE_CONTENIDOS}{slug}/es_def/index.shtml",
        )
        _anadir(reg, slug, n, an)

    # 2) resoluciones que solo están en el JSON anual (el catálogo va por detrás)
    for slug, a_it in an_idx.items():
        if slug in vistos:
            continue
        na = _num_anio(slug, a_it.get("fechaResolucion"))
        if not na or na[1] != anio:
            continue
        n, an = na
        log.info("OARC: %d/%d solo en el buscador anual; se añade", n, an)
        resumen = limpiar(a_it.get("resumenResolucion"))
        pdf = _pdf_construido(n, an) if an > ANIO_XML_HASTA else None
        reg = Registro(
            t=TRIBUNAL["id"],
            n=numero(f"{n}/{an}"),
            f=fecha_iso(a_it.get("fechaResolucion")),
            s=_sentido(a_it.get("sentidoResolucionDesc")),
            o=limpiar(a_it.get("poderAdjudicadorDesc")),
            d=_descripcion(a_it.get("objContrato"), resumen),
            a=_acto(resumen),
            pdf=pdf,
            p2=_p2(n, an) if pdf else None,
            url=f"{BASE_CONTENIDOS}{slug}/es_def/index.shtml",
        )
        _anadir(reg, slug, n, an)

    regs = [r for _, _, r in candidatos.values()]
    regs.sort(key=lambda r: int(r.n.split("/")[0]))
    return regs


# ---------------------------------------------------------------- ejecución directa

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--sin-xml" in sys.argv:
        XML_ANTIGUOS = False
    if args and args[0] == "todos":
        ses = Sesion()
        for y in range(TRIBUNAL["desde"], date.today().year + 1):
            rs = listar(y, ses)
            print(y, len(rs), "pdf", sum(1 for r in rs if r.pdf), "p2", sum(1 for r in rs if r.p2),
                  "s", sum(1 for r in rs if r.s), "a", sum(1 for r in rs if r.a))
        sys.exit(0)
    anio = int(args[0]) if args else date.today().year

    regs = listar(anio)
    total = len(regs)
    print(f"{TRIBUNAL['siglas']} {anio}: {total} registros")
    for r in regs[:3]:
        print(" ", r.limpio())
    if total > 6:
        print("  ...")
    for r in regs[-3:] if total > 3 else []:
        print(" ", r.limpio())
    if total:
        def pct(campo):
            return 100 * sum(1 for r in regs if getattr(r, campo)) / total
        print(f"con pdf: {pct('pdf'):.0f} % | con p2 (euskera): {pct('p2'):.0f} % | con fecha: {pct('f'):.0f} % "
              f"| con sentido: {pct('s'):.0f} % | con acto: {pct('a'):.0f} % | con órgano: {pct('o'):.0f} %")
    claves = [r.clave() for r in regs]
    repetidas = sorted({c for c in claves if claves.count(c) > 1})
    print("claves repetidas:", repetidas or "ninguna")
