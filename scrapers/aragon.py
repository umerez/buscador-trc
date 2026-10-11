"""TACPA: Tribunal Administrativo de Contratos Públicos de Aragón.

Fuente: el CGI BRS del Gobierno de Aragón (`gd.aragon.es/cgi-bin/ACTA/BRSCGI`), que es lo que hay
detrás del formulario oficial. Un GET con `CMD=VERLST` y un filtro por fecha de adopción
(`@FERE-GE=AAAA0101`, `@FERE-LE=AAAA1231`) devuelve el año entero en páginas de 100
(`DOCS=1-100`, `DOCS=101-200`, ...). HTML declarado como ISO-8859-1 pero con caracteres de Windows-1252
(guion largo 0x97): se decodifica como cp1252.

Cada bloque trae: Título («Acuerdo 15/2024, de 16 de febrero, del Tribunal ..., por el que se resuelve
el recurso ... promovido por X»), Resumen temático, Número («15/2024», «75/2024 (Recurso 68/2024)»,
«Resolución 25/2024 (Recurso 86/2024)»), Tipo de contrato, Sentido del acuerdo (falta en las
resoluciones), Fecha de adopción del acuerdo (dd/mm/aa) y un enlace `Abrirobjeto('MLKOB=<id>')`
que se traduce a `BRSCGI?CMD=VEROBJ&MLKOB=<id>` (el PDF). No hay ficha HTML, así que `url` queda vacío.

Dos series: los «Acuerdo N/AAAA» (fondo, k=None) y las «Resolución N/AAAA» (medidas cautelares,
levantamientos de suspensión, desistimientos..., k="cautelar"). Los números de recurso solo constan en
el campo Número y solo desde 2024 («RE N/AAAA» en el PDF, «(Recurso N/AAAA)» en el índice).

Para no perder registros con la fecha mal grabada se consulta también `NUME-C=/AAAA` (coincidencia
parcial sobre el campo Número) y se une con el resultado por fecha; de la unión se conservan los
registros cuyo número normalizado es del año pedido. Cuando el campo Número y el título discrepan
(hay erratas: Número «4/2014» con título «Acuerdo 4/2012») manda el título, que es la cita oficial.

Coste: unas 4 peticiones por año (2 páginas por fecha + 2 por número). El servidor devuelve
«Error durante la búsqueda (204/110)» cuando se le aprieta; en ese caso se lanza RuntimeError
para no confundirlo con un año vacío.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Optional

from scrapers.base import Registro, Sesion, limpiar, numero, fecha_iso

log = logging.getLogger("scrapers.aragon")

PAUSA_ENTRE_ANIOS = 8   # el BRS de gd.aragon.es entra en «Error durante la búsqueda (204/110)» tras muchas peticiones seguidas

TRIBUNAL = {
    "id": "aragon",
    "siglas": "TACPA",
    "nombre": "Tribunal Administrativo de Contratos Públicos de Aragón",
    "ambito": "Aragón",
    "buscador": "https://aplicacionesportalaragon.aragon.es/formularios/acuerdos-tribunal-admninistrativo-contratos-publicos-aragon.html",
    "idioma": "es",
    "desde": 2011,
    "documento": "Acuerdo",
}

CGI = "https://gd.aragon.es/cgi-bin/ACTA/BRSCGI"
ENCODING = "cp1252"   # el servidor declara iso-8859-1, pero usa guiones largos (0x97) y comillas de Windows-1252
POR_PAGINA = 100
MAX_PAGINAS = 50          # tope de seguridad (5.000 registros por consulta)

PETICIONES = 0            # contador para el informe del __main__

_RE_BLOQUE = re.compile(r'<h2 class="azul">', re.I)
_RE_TITULO = re.compile(r"^\s*T[íi]tulo:\s*(.*?)</h2>", re.S | re.I)   # el bloque empieza tras el <h2>
_RE_CONTADOR = re.compile(r"Documentos\s+(\d+)\s+a\s+(\d+)\s+de\s+(\d+)")
_RE_MLKOB = re.compile(r"MLKOB=(\d+)")
_RE_NUM = re.compile(r"(\d{1,4})\s*/\s*(\d{4})")
_RE_TIT_NUM = re.compile(r"^\s*(Acuerdo|Resoluci[óo]n)\s+n?[ºo.]?\s*(\d{1,4})\s*/\s*(\d{4})", re.I)
_RE_TIT_FECHA = re.compile(r"/\d{4}\s*,?\s*de\s+(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)(?:\s+de\s+(\d{4}))?", re.I)
_RE_RECURSO_PAREN = re.compile(r"\(\s*Recursos?\s+([^)]*)\)", re.I)
_RE_RE = re.compile(r"\bRE\s*(\d{1,4}\s*/\s*\d{4})")
_RE_ORGANO = re.compile(
    r"(?:promovid[oa]s?|convocad[oa]s?|tramitad[oa]s?|licitad[oa]s?)\s+por\s+(?:el|la|los|las)?\s*(.+?)\s*\.?\s*$",
    re.I | re.S,
)
# lo que sigue al órgano en el título: «, denominado «...»», «, solicitada por X en el recurso...»
_RE_ORGANO_CORTE = re.compile(
    r",?\s+(?:denominad[oa]s?\b|solicitad[oa]s?\b|en el recurso\b|en relaci[óo]n\b|relativ[oa]s?\b|"
    r"para (?:la|el|los|las)\b|con destino\b|mediante\b|a trav[ée]s\b|cuyo\b|en el que\b|en la que\b)|\s+[–—]\s*",
    re.I,
)
_RE_ORGANO_ANAFORA = re.compile(r"^(?:es[aeo]s?|dich[oa]s?|cita[dn][oa]s?|mism[oa]s?|referid[oa]s?)\b", re.I)
_ERROR_BRS = "Error durante la b"


# ---------------------------------------------------------------- HTTP

def _consulta(sesion: Sesion, filtro: dict, ini: int, fin: int) -> str:
    """Una página del listado. `filtro` son los parámetros de búsqueda BRS."""
    global PETICIONES
    params = {
        "CMD": "VERLST", "BASE": "ACTA", "DOCS": f"{ini}-{fin}", "SEC": "ACTA_PUBL",
        "SORT": "@FEPU", "SEPARADOR": "",
    }
    params.update(filtro)
    r = sesion.get(CGI, params=params)
    PETICIONES += 1
    r.encoding = sesion.encoding or ENCODING
    html = r.text
    if _ERROR_BRS in html and not _RE_BLOQUE.search(html):
        raise RuntimeError(
            f"TACPA: el BRS devolvió «Error durante la búsqueda» para {filtro} ({ini}-{fin}). "
            "Suele pasar al encadenar peticiones; esperar unos minutos y reintentar."
        )
    return html


def _paginas(sesion: Sesion, filtro: dict) -> list[str]:
    """Recorre la paginación de una consulta y devuelve los bloques HTML de todos los resultados."""
    bloques: list[str] = []
    ini = 1
    for _ in range(MAX_PAGINAS):
        html = _consulta(sesion, filtro, ini, ini + POR_PAGINA - 1)
        trozos = _RE_BLOQUE.split(html)[1:]
        bloques.extend(trozos)
        m = _RE_CONTADOR.search(html)
        if not m:
            break
        _, fin, total = (int(x) for x in m.groups())
        log.debug("TACPA %s: %d-%d de %d", filtro, ini, fin, total)
        if fin >= total or not trozos:
            break
        ini = fin + 1
    return bloques


# ---------------------------------------------------------------- parseo

def _campo(bloque: str, etiqueta: str) -> Optional[str]:
    """Valor de `<strong>Etiqueta: </strong>valor</span>`. Las etiquetas vienen partidas por saltos de línea."""
    patron = r"<strong>\s*" + r"\s+".join(map(re.escape, etiqueta.split())) + r"\s*:?\s*</strong>(.*?)</span>"
    m = re.search(patron, bloque, re.S | re.I)
    return limpiar(m.group(1)) if m else None


def _recursos(num_bruto: Optional[str], *otros: Optional[str]) -> Optional[str]:
    """«75/2024 (Recurso 68/2024)» → «RE 68/2024»; «(Recursos 43 y 46/2024)» → «RE 43/2024, RE 46/2024»."""
    textos = [t for t in (num_bruto, *otros) if t]
    for texto in textos:
        m = _RE_RECURSO_PAREN.search(texto)
        if not m:
            continue
        tokens = re.findall(r"(\d{1,4})(?:\s*/\s*(\d{4}))?", m.group(1))
        if not tokens:
            continue
        # a los números sin año se les asigna el del siguiente token con año («43 y 46/2024»)
        anios = [a for _, a in tokens]
        ultimo = None
        for i in range(len(anios) - 1, -1, -1):
            if anios[i]:
                ultimo = anios[i]
            else:
                anios[i] = ultimo
        res = [f"RE {int(n)}/{a}" for (n, _), a in zip(tokens, anios) if a]
        if res:
            return ", ".join(dict.fromkeys(res))
    for texto in textos:
        encontrados = [f"RE {numero(x)}" for x in _RE_RE.findall(texto)]
        if encontrados:
            return ", ".join(dict.fromkeys(encontrados))
    return None


def _fecha_desde_titulo(titulo: str, anio_num: Optional[int]) -> Optional[str]:
    """«Acuerdo 15/2024, de 16 de febrero, del Tribunal...» → 2024-02-16 (el año sale del número)."""
    m = _RE_TIT_FECHA.search(titulo)
    if not m:
        return None
    d, mes, y = m.group(1), m.group(2), m.group(3) or (str(anio_num) if anio_num else None)
    if not y:
        return None
    return fecha_iso(f"{d} de {mes} de {y}")


def _parsear(bloque: str) -> Optional[Registro]:
    m = _RE_TITULO.search(bloque)
    titulo = limpiar(m.group(1)) if m else None
    num_bruto = _campo(bloque, "Número")
    if not titulo and not num_bruto:
        return None

    # clase de documento: serie «Resolución N/AAAA» → cautelar; «Acuerdo N/AAAA» → principal
    cabeza = (num_bruto or "") + " " + (titulo or "")
    k = "cautelar" if re.match(r"\s*Resoluci[óo]n", num_bruto or "", re.I) or re.match(r"\s*Resoluci[óo]n", titulo or "", re.I) else None

    # número: campo Número, salvo que el título lo contradiga (erratas del índice)
    n_campo = None
    if num_bruto:
        mn = _RE_NUM.search(re.sub(r"\(.*?\)", " ", num_bruto))   # fuera del paréntesis del recurso
        if mn:
            n_campo = f"{int(mn.group(1))}/{mn.group(2)}"
    n_titulo = None
    if titulo:
        mt = _RE_TIT_NUM.match(titulo)
        if mt:
            n_titulo = f"{int(mt.group(2))}/{mt.group(3)}"
    if n_titulo and n_campo and n_titulo != n_campo:
        log.debug("TACPA: Número «%s» discrepa del título «%s»; se usa el título", n_campo, n_titulo)
    n = n_titulo or n_campo
    if not n:
        log.warning("TACPA: bloque sin número: %s", (titulo or num_bruto or "")[:120])
        return None
    anio_num = int(n.split("/")[1])

    fecha = fecha_iso(_campo(bloque, "Fecha de adopción del acuerdo")) or (_fecha_desde_titulo(titulo, anio_num) if titulo else None)
    resumen = _campo(bloque, "Resumen temático")
    organo = None
    if titulo:
        mo = _RE_ORGANO.search(titulo)
        if mo:
            organo = _RE_ORGANO_CORTE.split(mo.group(1), maxsplit=1)[0]
            organo = limpiar(organo.rstrip(".,;- ")) or None
            if organo and (len(organo) > 200 or _RE_ORGANO_ANAFORA.match(organo)):
                organo = None          # «esa Entidad Local», «dicho Ayuntamiento»: no es un nombre

    mk = _RE_MLKOB.search(bloque)
    pdf = f"{CGI}?CMD=VEROBJ&MLKOB={mk.group(1)}" if mk else None

    return Registro(
        t=TRIBUNAL["id"],
        n=numero(n),
        f=fecha,
        r=_recursos(num_bruto, titulo, resumen),
        s=_campo(bloque, "Sentido del acuerdo"),
        o=organo,
        d=resumen or titulo,
        c=_campo(bloque, "Tipo de contrato"),
        k=k,
        pdf=pdf,
        url=None,
    )


# ---------------------------------------------------------------- interfaz

def listar(anio: int, sesion: Optional[Sesion] = None) -> list[Registro]:
    """Todos los acuerdos y resoluciones del TACPA del año (unión por fecha de adopción y por número)."""
    sesion = sesion or Sesion(encoding=ENCODING)
    bloques = _paginas(sesion, {"@FERE-GE": f"{anio}0101", "@FERE-LE": f"{anio}1231"})
    bloques += _paginas(sesion, {"NUME-C": f"/{anio}"})

    vistos: dict[str, Registro] = {}
    for b in bloques:
        reg = _parsear(b)
        if reg is None:
            continue
        if not reg.n.endswith(f"/{anio}"):
            continue                      # «(Recurso N/AAAA)» de un acuerdo del año siguiente, o errata
        clave = reg.clave()
        previo = vistos.get(clave)
        if previo is None:
            vistos[clave] = reg
        elif previo.pdf != reg.pdf:
            log.warning("TACPA: clave repetida %s con PDF distinto (%s / %s)", clave, previo.pdf, reg.pdf)

    def orden(r: Registro):
        return (r.k or "", int(r.n.split("/")[0]))

    return sorted(vistos.values(), key=orden)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    anio = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    regs = listar(anio)
    print(f"TACPA {anio}: {len(regs)} registros en {PETICIONES} peticiones")
    for r in regs[:3] + regs[-3:]:
        print(r.limpio())
    if regs:
        con_pdf = sum(1 for r in regs if r.pdf)
        con_fecha = sum(1 for r in regs if r.f)
        con_r = sum(1 for r in regs if r.r)
        con_s = sum(1 for r in regs if r.s)
        con_o = sum(1 for r in regs if r.o)
        caut = sum(1 for r in regs if r.k == "cautelar")
        print(f"con pdf: {100 * con_pdf / len(regs):.1f} %  con fecha: {100 * con_fecha / len(regs):.1f} %  "
              f"con recurso: {100 * con_r / len(regs):.1f} %  con sentido: {100 * con_s / len(regs):.1f} %  "
              f"con órgano: {100 * con_o / len(regs):.1f} %  cautelares: {caut}")
    claves = [r.clave() for r in regs]
    repetidas = sorted({c for c in claves if claves.count(c) > 1})
    print("claves repetidas:", repetidas or "ninguna")
