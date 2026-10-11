"""TACGal - Tribunal Administrativo de Contratación Pública de la Comunidad Autónoma de Galicia.

Fuente: buscador Spring `https://tacgal.xunta.gal/sixtacweb/resolucions/` (solo filtra por POST; el GET
devuelve el fondo completo sin filtrar, aunque lleve parámetros).

Cómo se obtiene el año completo (verificado el 11/10/2026):

- POST con `locale`, `anoResolucion` y `size`. El servidor acepta `size` grande (probado 200 y 1000), así que
  un año entero cabe en UNA petición por idioma (el año más largo ronda las 250 resoluciones). Si algún día
  el servidor acortase `size`, se recorre la paginación repitiendo el POST en `?page=N` (0-based), guiándose
  por el texto «Mostrando del X al Y de Z resultados».
- Dos pasadas por año, una por `locale`: con `es` el enlace `<a id="NNNN" class="descargaDocumento">` apunta a
  la traducción automática al castellano y con `gl` al original gallego. Se cruzan por (nº resolución, nº recurso).
  Cuando la traducción está pendiente (`<div id="pteTraducir">`) el id de `es` coincide con el de `gl`: entonces
  `pdf` es el original gallego y `p2` queda vacío (no hay segundo documento).
- Los textos (decisión, tipo, acto, descripción) se toman de la pasada en castellano. Algunos valores de
  catálogo salen en gallego aunque se pida `locale=es` («Contrato de subministración», «Acordo de adxudicación»,
  «Outros actos de tramite»); se normalizan con `_TIPO` y `_ACTO`.
- PDF: `https://tacgal.xunta.gal/sixtacweb/resolucions/download/{id}` (GET directo; el cliente ejecuta reCAPTCHA v3
  pero el servidor no lo exige). No hay ficha HTML por resolución (`url` vacío).

Particularidades del origen:

- La tabla tiene UNA FILA POR RECURSO. Cuando una resolución resuelve varios recursos acumulados (frecuente en
  2018) el número de resolución se repite con distinto nº de recurso y, a veces, distinto id de documento (el
  mismo PDF subido dos veces). Aquí se funde en un registro por resolución: `r` concatena los recursos
  («149/2018, 145/2018») y `pdf`/`p2` son los de la primera fila. Si las filas fundidas discrepan en decisión,
  tipo, acto o descripción (en 2024 hay tres números repetidos que parecen errores de carga: 0195, 0165 y
  0163/2024), los valores distintos se unen con « / » para no perder información.
- Números en origen con 4 cifras («0100/2024»); se normalizan con `numero()`.
- Cobertura 2018-2026. El repositorio antiguo `ficheiros-web.xunta.gal/tacgal/resolucions/...` de 2018-2019 no
  hace falta: sixtacweb ya cubre 2018 entero (148 filas).

Coste: 2 peticiones por año (sin PDFs). Backfill 2018-2026 ≈ 18 peticiones, menos de un minuto.
"""
from __future__ import annotations

import logging
import re
import sys
from collections import OrderedDict
from typing import Dict, Iterator, List, Optional, Tuple

from bs4 import BeautifulSoup

from scrapers.base import Registro, Sesion, limpiar, numero, fecha_iso, absoluta

log = logging.getLogger("scrapers.galicia")

TRIBUNAL = {
    "id": "galicia",
    "siglas": "TACGal",
    "nombre": "Tribunal Administrativo de Contratación Pública de la Comunidad Autónoma de Galicia",
    "ambito": "Galicia",
    "buscador": "https://tacgal.xunta.gal/sixtacweb/resolucions/",
    "idioma": "gl",
    "desde": 2018,
    "documento": "Resolución",
}

URL = "https://tacgal.xunta.gal/sixtacweb/resolucions/"
DESCARGA = "https://tacgal.xunta.gal/sixtacweb/resolucions/download/{id}"
TAMANO = 500            # filas por página pedidas al servidor (lo acepta; el año más largo ronda 250)
MAX_PAGINAS = 50        # tope de seguridad por si el servidor ignorase el filtro de año

# Valores de catálogo que salen en gallego aunque se pida locale=es (o en castellano defectuoso en el <select>).
_TIPO = {
    "Contrato de subministración": "Contrato de suministro",
    "Contrato de suministración": "Contrato de suministro",
    "Contrato de servizos": "Contrato de servicios",
    "Concesión de servizos": "Concesión de servicios",
    "Acordo marco": "Acuerdo marco",
    "Encomenda": "Encomienda",
}
_ACTO = {
    "Acordo de adxudicación": "Acuerdo de adjudicación",
    "Adxudicación": "Adjudicación",
    "Pregos": "Pliegos",
    "Outros actos de tramite": "Otros actos de trámite",
    "Outros actos de trámite": "Otros actos de trámite",
    "Outros": "Otros",
    "Desistencia da licitación": "Desistencia de la licitación",
    "Acto trámite non cualificado": "Acto trámite no cualificado",
    "Anuncio Licitación": "Anuncio de licitación",
}

peticiones = 0  # contador de peticiones HTTP de la última ejecución (lo usa el bloque __main__)


# ---------------------------------------------------------------- parseo

_RE_TOTAL = re.compile(r"(?:Mostrando|Amosando)\s+d\w+\s+([\d.]+)\s+a\w*\s+([\d.]+)\s+de\s+([\d.]+)", re.I)


def _entero(s: str) -> int:
    return int(s.replace(".", ""))


def _total(html: str) -> Optional[Tuple[int, int, int]]:
    """(desde, hasta, total) del rótulo «Mostrando del 1 al 20 de 198 resultados» / «Amosando do 1 ao 20 de 198»."""
    m = _RE_TOTAL.search(html)
    if not m:
        return None
    return _entero(m.group(1)), _entero(m.group(2)), _entero(m.group(3))


def _filas(html: str) -> List[dict]:
    """Filas de la tabla de resultados: n, r, f, s, c, a, d (texto crudo), id (documento) y pte (traducción pendiente)."""
    soup = BeautifulSoup(html, "lxml")
    tabla = soup.find("table", id="tablaResultados")
    if tabla is None:
        return []
    filas = []
    for tr in tabla.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 7:
            continue
        celdas = [limpiar(td.get_text(" ")) for td in tds[:7]]
        if not celdas[0] or not re.search(r"\d", celdas[0]):
            continue
        enlace = tr.find("a", class_="descargaDocumento")
        id_doc = None
        if enlace is not None:
            id_attr = enlace.get("id") or ""
            if id_attr.isdigit():
                id_doc = id_attr
        filas.append({
            "n": celdas[0], "r": celdas[1], "f": celdas[2], "s": celdas[3],
            "c": celdas[4], "a": celdas[5], "d": celdas[6],
            "id": id_doc,
            "pte": tr.find(id="pteTraducir") is not None,
        })
    return filas


# ---------------------------------------------------------------- HTTP

def _pasada(sesion: Sesion, anio: int, locale: str) -> Iterator[dict]:
    """Recorre el año en el idioma pedido. Normalmente una sola petición (TAMANO grande); si el servidor
    devolviese menos filas de las que anuncia, sigue por `?page=N` repitiendo el POST."""
    global peticiones
    datos = {"locale": locale, "anoResolucion": str(anio), "size": str(TAMANO)}
    vistos = 0
    for pagina in range(MAX_PAGINAS):
        url = URL if pagina == 0 else f"{URL}?page={pagina}"
        # La cookie CookieLocaleResolver.LOCALE que fija el servidor podría imponerse al parámetro: se borra.
        sesion.s.cookies.clear()
        html = sesion.post(url, data=datos).text
        peticiones += 1
        filas = _filas(html)
        rango = _total(html)
        log.debug("TACGal %s %s page=%d: %d filas, rótulo %s", anio, locale, pagina, len(filas), rango)
        for fila in filas:
            yield fila
        vistos += len(filas)
        if not filas:
            break
        if rango is None or vistos >= rango[2] or rango[1] >= rango[2]:
            break
    else:
        log.warning("TACGal %s %s: alcanzado el tope de %d páginas", anio, locale, MAX_PAGINAS)


def _clave_fila(fila: dict, anio: int) -> Tuple[str, str]:
    return numero(fila["n"], anio), numero(fila["r"], anio)


def _unir(valores: List[Optional[str]]) -> Optional[str]:
    """Une valores distintos no vacíos conservando el orden; None si no hay ninguno."""
    vistos: "OrderedDict[str, None]" = OrderedDict()
    for v in valores:
        if v:
            vistos.setdefault(v, None)
    if not vistos:
        return None
    return " / ".join(vistos) if len(vistos) > 1 else next(iter(vistos))


def _orden(n: str) -> Tuple[int, int]:
    m = re.match(r"(\d+)/(\d+)", n)
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


# ---------------------------------------------------------------- interfaz

def listar(anio: int, sesion: Optional[Sesion] = None) -> List[Registro]:
    """Devuelve TODAS las resoluciones del año: dos pasadas (castellano y gallego) cruzadas por (nº resolución, nº recurso)."""
    global peticiones
    peticiones = 0
    sesion = sesion or Sesion()

    # Pasada en gallego: solo necesitamos el id del documento original por (resolución, recurso).
    ids_gl: Dict[Tuple[str, str], str] = {}
    for fila in _pasada(sesion, anio, "gl"):
        if fila["id"]:
            ids_gl.setdefault(_clave_fila(fila, anio), fila["id"])

    # Pasada en castellano: textos + id de la traducción. Se agrupa por nº de resolución (una fila por recurso en origen).
    grupos: "OrderedDict[str, List[dict]]" = OrderedDict()
    for fila in _pasada(sesion, anio, "es"):
        n = numero(fila["n"], anio)
        grupos.setdefault(n, []).append(fila)

    registros: List[Registro] = []
    for n, filas in grupos.items():
        # Filas repetidas exactas (mismo recurso y mismo documento) se descartan.
        unicas: List[dict] = []
        vistas = set()
        for fila in filas:
            marca = (numero(fila["r"], anio), fila["id"])
            if marca in vistas:
                continue
            vistas.add(marca)
            unicas.append(fila)
        if len(unicas) > 1:
            # Si las filas discrepan en fecha (error de carga del origen), manda la que cae dentro del año.
            unicas.sort(key=lambda f: 0 if (fecha_iso(f["f"]) or "").startswith(str(anio)) else 1)
            log.info("TACGal %s: %d filas para la resolución %s (recursos %s)", anio, len(unicas), n,
                     ", ".join(numero(f["r"], anio) for f in unicas))

        principal = unicas[0]
        clave = _clave_fila(principal, anio)
        id_es = principal["id"]
        id_gl = ids_gl.get(clave)
        if id_es is None and id_gl is None:
            # Alguna otra fila del grupo puede tener documento.
            for fila in unicas[1:]:
                id_es = id_es or fila["id"]
                id_gl = id_gl or ids_gl.get(_clave_fila(fila, anio))

        pdf = p2 = None
        if id_es:
            pdf = DESCARGA.format(id=id_es)
            if id_gl and id_gl != id_es:
                p2 = DESCARGA.format(id=id_gl)
        elif id_gl:
            pdf = DESCARGA.format(id=id_gl)

        registros.append(Registro(
            t=TRIBUNAL["id"],
            n=n,
            f=next((fi for fi in (fecha_iso(f["f"]) for f in unicas) if fi), None),
            r=", ".join(OrderedDict((numero(f["r"], anio), None) for f in unicas if f["r"])) or None,
            s=_unir([f["s"] for f in unicas]),
            c=_unir([_TIPO.get(f["c"] or "", f["c"]) for f in unicas]),
            a=_unir([_ACTO.get(f["a"] or "", f["a"]) for f in unicas]),
            d=_unir([f["d"] for f in unicas]),
            pdf=pdf,
            p2=p2,
            url=None,
        ))

    registros.sort(key=lambda r: _orden(r.n))
    log.info("TACGal %s: %d resoluciones (%d filas es, %d ids gl, %d peticiones)",
             anio, len(registros), sum(len(v) for v in grupos.values()), len(ids_gl), peticiones)
    return registros


# ---------------------------------------------------------------- ejecución directa

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    anio = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    regs = listar(anio)
    total = len(regs)
    print(f"\nTACGal {anio}: {total} resoluciones en {peticiones} peticiones")
    if regs:
        print("\nPrimeros 3:")
        for r in regs[:3]:
            print("  ", r.limpio())
        print("\nÚltimos 3:")
        for r in regs[-3:]:
            print("  ", r.limpio())
        con_pdf = sum(1 for r in regs if r.pdf)
        con_p2 = sum(1 for r in regs if r.p2)
        con_f = sum(1 for r in regs if r.f)
        print(f"\nCon pdf: {con_pdf} ({100 * con_pdf / total:.1f} %)  "
              f"con p2: {con_p2} ({100 * con_p2 / total:.1f} %)  "
              f"con fecha: {con_f} ({100 * con_f / total:.1f} %)")
        for campo in ("r", "s", "c", "a", "d"):
            k = sum(1 for r in regs if getattr(r, campo))
            print(f"  {campo}: {k} ({100 * k / total:.1f} %)")
    claves = [r.clave() for r in regs]
    repetidas = sorted({c for c in claves if claves.count(c) > 1})
    if repetidas:
        print(f"\nCLAVES REPETIDAS ({len(repetidas)}): {repetidas}")
        sys.exit(1)
    print("\nSin claves repetidas.")
