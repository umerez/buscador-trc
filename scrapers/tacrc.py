"""TACRC (Tribunal Administrativo Central de Recursos Contractuales, Ministerio de Hacienda).

El buscador oficial exige un token de Cloudflare Turnstile validado en el servidor y no hay listados ni
sitemap de las resoluciones, así que no se puede indexar desde la propia web del tribunal. Lo que sí es
público es el nombre de cada PDF, que lleva el nº de recurso, el nº de resolución y la fecha:

    https://www.hacienda.gob.es/TACRC/Resoluciones/Año 2024/Recurso 0353-2024 (Res 992) 31-07-2024.pdf
    .../Año 2018/Recurso 0456-2018 CLM 31-2018 (Res 556) 08-06-2018.pdf      (comunidad conveniada)
    .../Año 2011/Recurso 0164 y 0173-2011 (Res 204) 07-09-11.pdf             (recursos acumulados, año de 2 cifras)
    .../tacrc/documentos/resoluciones de pleno 2022/resolución recurso 1028-2022 (res 1156) 06-10-2022.pdf

Este módulo reconstruye un índice PARCIAL a partir de las URL de PDF que conservan los archivos públicos de
la web: el índice CDX de la Wayback Machine (consulta en vivo, un GET por dominio) y una lista fija obtenida
de Common Crawl (`tacrc_urls_commoncrawl.txt`, junto a este fichero). Da nº de resolución, nº de recurso,
fecha y enlace al PDF; no da sentido, órgano ni objeto (para eso habría que leer cada PDF: véase
`enriquecer_tacrc.py`). Cobertura observada el 11/10/2026: unas 2.700 de las ~20.000 resoluciones.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

from scrapers.base import Registro, Sesion

log = logging.getLogger("scrapers.tacrc")

TRIBUNAL = {
    "id": "tacrc",
    "siglas": "TACRC",
    "nombre": "Tribunal Administrativo Central de Recursos Contractuales",
    "ambito": "Estado y comunidades conveniadas (Castilla-La Mancha, Comunitat Valenciana, Murcia, Illes Balears, Asturias, Extremadura, Cantabria, La Rioja, Ceuta y Melilla)",
    "buscador": "https://www.hacienda.gob.es/es-ES/Areas%20Tematicas/Contratacion/TACRC/Paginas/BuscadordeResoluciones.aspx",
    "idioma": "es",
    "desde": 2011,
    "documento": "Resolución",
    "parcial": "El buscador oficial del TACRC exige una comprobación anti-robots que impide indexarlo. Este índice solo contiene las resoluciones cuyos PDF conservan los archivos públicos de la web (Wayback Machine y Common Crawl): número, recurso, fecha y enlace, sin sentido ni objeto. Para el resto, use el buscador oficial o el constructor de enlaces al PDF.",
}

CDX = "http://web.archive.org/cdx/search/cdx"
DOMINIOS = ["hacienda.gob.es", "minhafp.gob.es", "minhap.gob.es"]
LISTA_CC = Path(__file__).with_name("tacrc_urls_commoncrawl.txt")
HOST = "https://www.hacienda.gob.es"

# «Recurso 0353-2024 (Res 992) 31-07-2024», «Recurso 0164 y 0173-2011 (Res 204) 07-09-11», «Recurso 0456-2018 CLM 31-2018 (Res 556) …»
RE_NOMBRE = re.compile(
    r"recurso\s+(?P<recs>[\d\s,y]+?)-(?P<anio_rec>\d{4})"
    r"(?:\s+(?P<ccaa>[A-Z]{2,4})\s+(?P<rec_ccaa>[\d\s,y]+?)-(?P<anio_ccaa>\d{4}))?"
    r"[^()]*\(res\.?\s*(?P<res>\d{1,4})\)"
    r"[^\d]*(?P<d>\d{1,2})-(?P<m>\d{1,2})-(?P<y>\d{2,4})",
    re.I,
)
RE_ANIO_CARPETA = re.compile(r"/(?:a[ñn]o|resoluciones de pleno)\s*(\d{4})/", re.I)

_cache: Dict[str, List[Registro]] = {}


def _urls_wayback(sesion: Sesion) -> List[str]:
    urls: List[str] = []
    for dom in DOMINIOS:
        try:
            txt = sesion.texto(CDX, params={
                "url": f"{dom}/tacrc/*", "output": "txt", "fl": "original", "collapse": "urlkey",
                "filter": ["mimetype:application/pdf", "statuscode:200"],
            }, timeout=180)
        except Exception as e:  # noqa: BLE001
            log.warning("TACRC: Wayback CDX no responde para %s: %s", dom, e)
            continue
        urls.extend(l.strip() for l in txt.splitlines() if l.strip())
    log.info("TACRC: %d URL de PDF en la Wayback Machine", len(urls))
    return urls


def _urls_commoncrawl() -> List[str]:
    if not LISTA_CC.exists():
        return []
    return [l.strip() for l in LISTA_CC.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def _canonica(url: str) -> str:
    """Misma ruta en el dominio actual, codificada de forma uniforme (el servidor es insensible a mayúsculas)."""
    ruta = unquote(re.sub(r"^https?://(www\.)?[^/]+", "", url.strip()))
    return HOST + quote(ruta, safe="/()")


def _registro(url: str) -> Optional[Registro]:
    ruta = unquote(url)
    nombre = ruta.rsplit("/", 1)[-1]
    m = RE_NOMBRE.search(nombre)
    if not m:
        return None
    y = int(m.group("y"))
    if y < 100:
        y += 2000
    try:
        fecha = f"{y:04d}-{int(m.group('m')):02d}-{int(m.group('d')):02d}"
    except ValueError:
        fecha = None
    mc = RE_ANIO_CARPETA.search(ruta)
    anio_res = int(mc.group(1)) if mc else y
    recs = [int(x) for x in re.findall(r"\d+", m.group("recs"))]
    anio_rec = m.group("anio_rec")
    recurso = ", ".join(f"{r}/{anio_rec}" for r in recs)
    if m.group("ccaa"):
        recs_ccaa = [int(x) for x in re.findall(r"\d+", m.group("rec_ccaa"))]
        recurso += " (" + m.group("ccaa").upper() + " " + ", ".join(f"{r}/{m.group('anio_ccaa')}" for r in recs_ccaa) + ")"
    k = None
    if re.search(r"corregid|rectific", nombre, re.I):
        k = "rectificacion"
    return Registro(t="tacrc", n=f"{int(m.group('res'))}/{anio_res}", f=fecha, r=recurso, k=k, pdf=_canonica(url))


def _todos(sesion: Optional[Sesion]) -> List[Registro]:
    if "todos" in _cache:
        return _cache["todos"]
    sesion = sesion or Sesion()
    urls = _urls_wayback(sesion) + _urls_commoncrawl()
    vistos: Dict[str, Registro] = {}
    sin_patron = 0
    for u in urls:
        r = _registro(u)
        if r is None:
            sin_patron += 1
            continue
        previo = vistos.get(r.clave())
        # entre variantes de la misma resolución (mayúsculas, dominio antiguo) vale cualquiera; se prefiere la del dominio actual
        if previo is None or ("hacienda.gob.es" in u and "hacienda.gob.es" not in (previo.pdf or "")):
            vistos[r.clave()] = r
    log.info("TACRC: %d resoluciones distintas (%d URL sin el patrón de nombre)", len(vistos), sin_patron)
    _cache["todos"] = list(vistos.values())
    return _cache["todos"]


def listar(anio: int, sesion: Optional[Sesion] = None) -> List[Registro]:
    return sorted((r for r in _todos(sesion) if r.n.endswith(f"/{anio}")), key=lambda r: int(r.n.split("/")[0]))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    anio = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    regs = listar(anio)
    print(f"{anio}: {len(regs)} registros")
    for r in regs[:3] + regs[-3:]:
        print(" ", r.limpio())
    claves = [r.clave() for r in regs]
    print("claves repetidas:", len(claves) - len(set(claves)))
    print("con fecha:", sum(1 for r in regs if r.f), "con recurso:", sum(1 for r in regs if r.r))
