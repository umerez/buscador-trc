"""TACP Canarias: Tribunal Administrativo de Contratos Públicos de la Comunidad Autónoma de Canarias.

Dos fuentes, que se cruzan por número de resolución:

1. Visor JSP sobre Solr (`visor_resoluciones/index.jsp`, GET con `param_accion=buscar` y rango de
   fechas). Solr devuelve todo el año (`rows=100000000`), pero la JSP solo PINTA 200 resultados por
   página: hay que recorrer `page_buscador=2, 3...` cuando «Se han encontrado N» supera 200. El visor
   trae campos ricos (expediente, acto, tipo de contrato, procedimiento, órgano, tipo de resolución,
   objeto, CPV, precepto y href al PDF) solo para 2022-2026 (parcialmente 2020). Para 2015-2019 trae
   número, fecha, resumen y a veces el tipo de resolución, sin PDF. Y está incompleto en algunos años
   (2021: 2 resultados de 284; 2022: 235 de 253).

2. Listado anual estático (`tacp/resoluciones/resoluciones_AAAA/`, existe para 2015-2023; 2024 en
   adelante da 404). Una sola página con todas las resoluciones del año: título «Resolución N/AAAA, de
   D de mes», href al PDF, resumen, «Materia» y «Tipo de resolución». De aquí salen el PDF y la fecha
   de 2015-2021 y las resoluciones que faltan en el visor. El expediente (REMC N-AAAA) se deduce del
   nombre del PDF cuando el visor no lo da.

El registro final es la unión: el visor manda y el listado rellena lo que falte o añade lo que no esté.
Peticiones por año: 1-2 al visor + 1 al listado (hasta 2023). Sin ficha HTML por resolución (`url` vacío).
"""
from __future__ import annotations

import logging
import math
import re
import sys
from typing import Optional

from scrapers.base import Registro, Sesion, limpiar, numero, fecha_iso, absoluta, sin_acentos

log = logging.getLogger("scrapers.canarias")

TRIBUNAL = {
    "id": "canarias",
    "siglas": "TACP Canarias",
    "nombre": "Tribunal Administrativo de Contratos Públicos de la Comunidad Autónoma de Canarias",
    "ambito": "Comunidad Autónoma de Canarias",
    "buscador": "https://www.gobiernodecanarias.org/hacienda/contratacion/tacp/visor_resoluciones/index.jsp",
    "idioma": "es",
    "desde": 2015,
    "documento": "Resolución",
}

VISOR = TRIBUNAL["buscador"]
LISTADO = "https://www.gobiernodecanarias.org/hacienda/contratacion/tacp/resoluciones/resoluciones_{anio}/"
LISTADO_HASTA = 2023          # último año con listado anual estático (2024+ → 404)
POR_PAGINA = 200              # resultados que pinta la JSP por página
MAX_PAGINAS = 20
MAX_D = 300                   # longitud máxima de la descripción

PETICIONES = 0                # contador para el informe de __main__


# ---------------------------------------------------------------- HTTP

def _get(sesion: Sesion, url: str, **kw) -> str:
    global PETICIONES
    PETICIONES += 1
    return sesion.texto(url, **kw)


# ---------------------------------------------------------------- visor

_RE_TOTAL = re.compile(r"Se han encontrado\s+(\d+)\s+resultado", re.I)
_RE_H4 = re.compile(r'<h4 class="resultado_titulo">')
_RE_TITULO = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.S)
_RE_HREF = re.compile(r'href="([^"]+)"')
_RE_FECHA = re.compile(r'<span class="doc-date">(.*?)</span>', re.S)
_RE_ETIQUETA = re.compile(r'\s*<p class="doc-summay">\s*<strong>([^<]*?)\s*:?\s*</strong>(.*?)</p>', re.S)
_SEP_ETIQUETAS = "<!-- Muestra las etiquetas -->"

# etiqueta del visor (sin acentos, minúsculas) → campo interno
_CAMPOS = {
    "expediente": "expediente",
    "acto recurrido": "acto",
    "tipo contrato": "tipo_contrato",
    "tipo de procedimiento": "procedimiento",
    "organo de contratacion": "organo",
    "tipo resolucion": "tipo_resolucion",
    "objeto de contrato": "objeto",
    "codigo cpv": "cpv",
    "precepto": "precepto",
}


def _params_visor(anio: int, pagina: int) -> dict:
    p = {
        "param_page": "1",
        "param_accion": "buscar",
        "chpae_resolucion_fecharesolucion_es_dt_d": f"01/01/{anio}",
        "chpae_resolucion_fecharesolucion_es_dt": f"31/12/{anio}",
    }
    if pagina > 1:
        p["page_buscador"] = str(pagina)
    return p


def _parsear_visor(html: str) -> tuple[int, list[dict]]:
    """Devuelve (total anunciado, lista de dicts con los campos crudos de cada resultado)."""
    m = _RE_TOTAL.search(html)
    total = int(m.group(1)) if m else 0
    ini = html.find('<ul class="list">')
    if ini < 0:
        return total, []
    fin = html.find('<div class="contenedor-pagination">', ini)
    zona = html[ini:fin if fin > 0 else None]
    trozos = _RE_H4.split(zona)[1:]
    filas = []
    for trozo in trozos:
        fila: dict = {}
        mt = _RE_TITULO.search(trozo)
        if not mt:
            continue
        fila["numero"] = limpiar(mt.group(2))
        mh = _RE_HREF.search(mt.group(1))
        if mh and mh.group(1).lower().endswith(".pdf"):
            fila["pdf"] = absoluta(VISOR, mh.group(1))
        mf = _RE_FECHA.search(trozo)
        if mf:
            fila["fecha"] = fecha_iso(mf.group(1))
        for parte in trozo.split(_SEP_ETIQUETAS)[1:]:
            me = _RE_ETIQUETA.match(parte)
            if me:
                etiqueta = sin_acentos(limpiar(me.group(1)) or "").lower()
                campo = _CAMPOS.get(etiqueta)
                if campo:
                    fila[campo] = limpiar(me.group(2))
                else:
                    log.debug("etiqueta desconocida en el visor: %r", etiqueta)
            else:
                fila["resumen_html"] = parte
        filas.append(fila)
    return total, filas


def _buscar_visor(sesion: Sesion, anio: int) -> list[dict]:
    html = _get(sesion, VISOR, params=_params_visor(anio, 1))
    total, filas = _parsear_visor(html)
    paginas = min(MAX_PAGINAS, math.ceil(total / POR_PAGINA)) if total else 1
    for pagina in range(2, paginas + 1):
        html = _get(sesion, VISOR, params=_params_visor(anio, pagina))
        _, mas = _parsear_visor(html)
        if not mas:
            break
        filas.extend(mas)
    if len(filas) < total:
        log.warning("canarias %d: el visor anuncia %d y pinta %d", anio, total, len(filas))
    return filas


# ---------------------------------------------------------------- listado anual (2015-2023)

_RE_EVENTO = re.compile(r'<li class="evento">')
_RE_H5 = re.compile(r'<h5[^>]*>\s*<a\b([^>]*)>(.*?)</a>', re.S)
_RE_TEXTO = re.compile(r'<div class="\s*textoNovedad">(.*?)</div>', re.S)
_RE_RES_TITULO = re.compile(r"Resol[uú]ci[oó]n\s+(\d{1,4})\s*/\s*(\d{4})", re.I)
_RE_RES_DIA = re.compile(r",?\s*(?:de\s+)?(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)", re.I)
_RE_RES_FICHERO = re.compile(r"RES[A-Z]*[._xº\-]*\s*(?:N[ºx°.]*[._\-]*)?(\d{1,3})[._\-]+(20\d\d)", re.I)
# expediente en el nombre del PDF: «REMC-104-Y-111-2017», «REMC_Nx_42-2015», «RCLSE-003-Y-004-2023», «REC_27-2015»
_RE_EXP_FICHERO = re.compile(
    r"(REMC|REmc|RMC|REM|RECURSOS?|REC|RCLSE|RECLSE|RLCSE|RCL|RECLAMAC)\.?[._\s\-]*(?:N[ºx°.]*[._\-]*)?"
    r"((?:\d{1,4}(?:BIS)?[._\s\-]*(?:[yYaA][._\s\-]*)?)+?)(20\d\d)(?!\d)")
_PREFIJOS_EXP = {"RCLSE": "RCLSE", "RECLSE": "RCLSE", "RLCSE": "RCLSE", "RCL": "RCLSE", "RECLAMAC": "RCLSE"}


def _listado_anual(sesion: Sesion, anio: int) -> dict[str, dict]:
    """Resoluciones del listado anual indexadas por número normalizado. {} si no existe."""
    if anio > LISTADO_HASTA:
        return {}
    try:
        html = _get(sesion, LISTADO.format(anio=anio))
    except RuntimeError as e:  # 404 u otro fallo: Sesion agota reintentos y lanza RuntimeError
        log.warning("canarias %d: sin listado anual (%s)", anio, e)
        return {}
    res: dict[str, dict] = {}
    for trozo in _RE_EVENTO.split(html)[1:]:
        mh = _RE_H5.search(trozo)
        if not mh:
            continue
        titulo = limpiar(mh.group(2)) or ""
        href = _RE_HREF.search(mh.group(1))
        pdf = absoluta(LISTADO.format(anio=anio), href.group(1)) if href else None
        nombre = pdf.rsplit("/", 1)[-1] if pdf else ""
        mn = _RE_RES_TITULO.search(titulo) or _RE_RES_FICHERO.search(nombre)
        if not mn:
            log.debug("listado %d: sin número en %r / %r", anio, titulo, nombre)
            continue
        n = numero(f"{mn.group(1)}/{mn.group(2)}")
        fila: dict = {"numero": n, "pdf": pdf}
        md = _RE_RES_DIA.search(titulo, mn.end()) if mn.re is _RE_RES_TITULO else None
        if md:
            fila["fecha"] = fecha_iso(f"{md.group(1)} de {md.group(2)} de {mn.group(2)}")
        fila["expediente"] = _expediente_fichero(nombre)
        mt = _RE_TEXTO.search(trozo)
        if mt:
            fila["resumen_html"] = mt.group(1)
        if n in res:
            # el mismo número repetido (dos PDF): nos quedamos con el primero y completamos huecos
            for k, v in fila.items():
                res[n].setdefault(k, v)
        else:
            res[n] = fila
    return res


def _expediente_fichero(nombre: str) -> Optional[str]:
    """«RES-132-REMC-104-Y-111-2017.pdf» → «REMC 104 y 111-2017». None si no se reconoce."""
    m = _RE_EXP_FICHERO.search(nombre)
    if not m:
        return None
    prefijo = _PREFIJOS_EXP.get(m.group(1).upper(), "REMC")
    nums = [str(int(x)) if x.isdigit() else x for x in re.findall(r"\d{1,4}(?:BIS)?", m.group(2).upper())]
    return f"{prefijo} {_unir(nums)}-{m.group(3)}"


def _unir(nums: list) -> str:
    """['10', '11', '16'] → '10, 11 y 16'."""
    return nums[0] if len(nums) == 1 else ", ".join(nums[:-1]) + " y " + nums[-1]


def _expediente_visor(s: Optional[str]) -> Optional[str]:
    """Normaliza «REMC  071-2023», «REMC 005 - 024 - 2022», «RECLSE 002-2022» → «REMC 71-2023», «REMC 5 y 24-2022», «RCLSE 2-2022»."""
    s = limpiar(s)
    if not s:
        return None
    m = re.match(r"(?:(REMC|RCLSE|RECLSE|RLCSE)\s*)?((?:\d{1,4}\s*[-\s]*(?:y\s*)?)+?)(20\d\d)$", s, re.I)
    if not m:
        return re.sub(r"\s+", " ", s)
    prefijo = _PREFIJOS_EXP.get((m.group(1) or "REMC").upper(), "REMC")
    nums = [str(int(x)) for x in re.findall(r"\d{1,4}", m.group(2))]
    return f"{prefijo} {_unir(nums)}-{m.group(3)}"


# ---------------------------------------------------------------- resumen antiguo → d, s, a

_RE_MATERIA = re.compile(r"<strong>\s*Materia\s*:?\s*</strong>\s*:?\s*(?:<br\s*/?>|</p>\s*<p>|\s)*(.*?)(?=</p>|<strong>|$)", re.S | re.I)
_RE_TIPO = re.compile(r"<strong>\s*Tipo de [Rr]esoluci[oó]n\s*:?\s*</strong>\s*:?\s*(?:<br\s*/?>|</p>\s*<p>|\s)*(.*?)(?=</p>|<strong>|$)", re.S | re.I)
_RE_CORTE = re.compile(r"<p[^>]*>\s*<strong>\s*(?:Materia|Tipo de [Rr]esoluci[oó]n)", re.I)


def _desglosar_resumen(html: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(resumen, tipo de resolución, materia) a partir del HTML del resumen de 2015-2021."""
    if not html:
        return None, None, None
    tipo = materia = None
    m = _RE_TIPO.search(html)
    if m:
        tipo = _valor(m.group(1))
    m = _RE_MATERIA.search(html)
    if m:
        materia = _valor(m.group(1))
    corte = _RE_CORTE.search(html)
    resumen = limpiar(html[:corte.start()] if corte else html)
    if resumen:
        resumen = re.sub(r"^Resumen\s*:\s*", "", resumen)
        # a veces las etiquetas van sin <p> propio: quitar lo que quede de ellas al final
        resumen = re.sub(r"\s*(Materia|Tipo de [Rr]esoluci[oó]n)\s*:.*$", "", resumen).strip() or None
    return resumen, tipo, materia


def _valor(s: str) -> Optional[str]:
    v = limpiar(s)
    if not v:
        return None
    v = v.strip(" .:")
    return v or None


def _recortar(s: Optional[str], n: int = MAX_D) -> Optional[str]:
    if not s or len(s) <= n:
        return s
    corte = s.rfind(" ", 0, n - 1)
    return s[: corte if corte > n // 2 else n - 1].rstrip(" ,;:") + "…"


# ---------------------------------------------------------------- unión

def _registro(anio: int, fila: dict) -> Registro:
    resumen, tipo_viejo, materia = _desglosar_resumen(fila.get("resumen_html"))
    # Objeto del contrato y resumen doctrinal: los dos interesan para buscar; se recorta el conjunto.
    objeto = fila.get("objeto")
    descripcion = f"{objeto.rstrip('.')}. {resumen}" if objeto and resumen and objeto != resumen else (objeto or resumen)
    return Registro(
        t=TRIBUNAL["id"],
        n=numero(fila["numero"], anio),
        f=fila.get("fecha"),
        r=_expediente_visor(fila.get("expediente")),
        s=fila.get("tipo_resolucion") or tipo_viejo,
        o=fila.get("organo"),
        d=_recortar(descripcion, 400),
        a=fila.get("acto") or materia,
        c=fila.get("tipo_contrato"),
        pdf=fila.get("pdf"),
        url=None,
    )


def _completar(destino: Registro, origen: Registro) -> None:
    for campo in ("f", "r", "s", "o", "d", "a", "c", "pdf", "url"):
        if not getattr(destino, campo) and getattr(origen, campo):
            setattr(destino, campo, getattr(origen, campo))


def listar(anio: int, sesion: Optional[Sesion] = None) -> list[Registro]:
    """Devuelve TODAS las resoluciones del año: visor (1-2 páginas) + listado anual (hasta 2023)."""
    sesion = sesion or Sesion(encoding="utf-8")
    por_numero: dict[str, Registro] = {}
    for fila in _buscar_visor(sesion, anio):
        reg = _registro(anio, fila)
        if reg.n in por_numero:
            _completar(por_numero[reg.n], reg)        # Solr devuelve algún documento duplicado
        else:
            por_numero[reg.n] = reg
    sin_pdf = sum(1 for r in por_numero.values() if not r.pdf)
    if anio <= LISTADO_HASTA or sin_pdf:
        listado = _listado_anual(sesion, anio)
        nuevos = 0
        for n, fila in listado.items():
            reg = _registro(anio, fila)
            if n in por_numero:
                _completar(por_numero[n], reg)
            else:
                por_numero[n] = reg
                nuevos += 1
        if listado:
            log.info("canarias %d: visor %d, listado %d (%d solo en el listado)",
                     anio, len(por_numero) - nuevos, len(listado), nuevos)
    return sorted(por_numero.values(), key=_orden)


def _orden(r: Registro) -> tuple:
    m = re.match(r"(\d+)/(\d+)", r.n)
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


# ---------------------------------------------------------------- prueba manual

if __name__ == "__main__":
    import time
    from collections import Counter

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    anio = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    t0 = time.monotonic()
    regs = listar(anio)
    dt = time.monotonic() - t0
    print(f"{TRIBUNAL['siglas']} {anio}: {len(regs)} registros en {PETICIONES} peticiones ({dt:.0f} s)")
    for r in regs[:3]:
        print(" ", r.limpio())
    if len(regs) > 6:
        print("  ...")
    for r in regs[-3:]:
        print(" ", r.limpio())
    if regs:
        tot = len(regs)
        print(f"con pdf: {sum(1 for r in regs if r.pdf) * 100 / tot:.0f} %   con fecha: {sum(1 for r in regs if r.f) * 100 / tot:.0f} %"
              f"   con expediente: {sum(1 for r in regs if r.r) * 100 / tot:.0f} %   con tipo: {sum(1 for r in regs if r.s) * 100 / tot:.0f} %"
              f"   con órgano: {sum(1 for r in regs if r.o) * 100 / tot:.0f} %   con d: {sum(1 for r in regs if r.d) * 100 / tot:.0f} %")
    repetidas = [k for k, v in Counter(r.clave() for r in regs).items() if v > 1]
    print("claves repetidas:", repetidas or "ninguna")
