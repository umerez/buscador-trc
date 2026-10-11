"""TARCCYL: Tribunal Administrativo de Recursos Contractuales de Castilla y León (alojado en cccyl.es).

Fuente: listados anuales del gestor de contenidos Proxia del Consejo Consultivo
    https://www.cccyl.es/es/tribunal-administrativo-recursos-contractuales-castilla-leo/resoluciones/resoluciones-ano-AAAA
con paginación `.nodos,OFFSET,10` (verificado el 11/10/2026):

- El listado trae por cada resolución el título («Resolución 185/2024»), el href de la ficha, el párrafo
  «Fundamentos» (resumen doctrinal) y el href del PDF (`<ficha>.ficheros/<ID>-Resolución 185-2024 .pdf`).
  No trae fecha, nº de recurso, órgano, acto ni tipo de resolución: eso solo está en la ficha, así que se
  abre una ficha por registro (1 petición/registro; unas 2.000 fichas en todo el repositorio). Con
  `fichas=False` se obtiene el índice solo con lo que da el listado (n, d, pdf, url) en un 10 % del tiempo.
- Tamaño de página fijo: 10 en los años recientes (`.nodos,10,100` sigue devolviendo 10). En 2012 y 2013 el
  listado sale entero en una sola página y sin paginador.
- Un OFFSET más allá del final NO devuelve vacío: recicla resultados. Por eso el recorrido se corta por el
  mayor offset que anuncia el paginador (la primera página ya enlaza al último) y se deduplica por número.
- Año inexistente (p. ej. 2011) → 404 → se devuelve [].
- El buscador (`resoluciones.buscar?formName=searchForm&S_RES_FECHA_min=1/1/24&S_RES_FECHA_max=31/12/24`)
  devuelve los mismos ítems con los mismos campos, también de 10 en 10 (`.buscar,0,50` ignora el 50), así que
  no aporta nada sobre el listado anual y no se usa.
- Las fichas de los primeros años traen además «Tipo de procedimiento» (en realidad el objeto del contrato) y
  el tipo de resolución en minúsculas («desestimatoria»); se normaliza la inicial.
- TLS: www.cccyl.es no envía el certificado intermedio (Sectigo Public Server Authentication CA DV R36). curl y
  los navegadores lo resuelven por AIA, pero el OpenSSL de Python no, y `requests` falla con
  CERTIFICATE_VERIFY_FAILED. `_preparar_ssl()` lo rodea sin tocar base.py: descarga el intermedio de la URL
  AIA del certificado del servidor y lo añade a certifi en un bundle cacheado en el directorio temporal.
"""
from __future__ import annotations

import logging
import os
import re
import socket
import ssl
import sys
import tempfile
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scrapers.base import Registro, Sesion, limpiar, numero, fecha_iso, absoluta

log = logging.getLogger("scrapers.cyl")

BASE = "https://www.cccyl.es"
HOST = urlparse(BASE).hostname
RAIZ = BASE + "/es/tribunal-administrativo-recursos-contractuales-castilla-leo/resoluciones"
AIA_RESPALDO = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"
BUNDLE_CA = os.path.join(tempfile.gettempdir(), "buscador-trc-cyl-ca.pem")

TRIBUNAL = {
    "id": "cyl",
    "siglas": "TARCCYL",
    "nombre": "Tribunal Administrativo de Recursos Contractuales de Castilla y León",
    "ambito": "Castilla y León",
    "buscador": RAIZ + ".buscar?formName=searchForm",
    "idioma": "es",
    "desde": 2012,
    "documento": "Resolución",
}

POR_PAGINA = 10
RE_FICHA = re.compile(r"/resoluciones-ano-(\d{4})/resolucion-(\d{1,4})-(\d{4})/?$")


# ---------------------------------------------------------------- TLS (cadena incompleta del servidor)

def _handshake_ok(cafile: Optional[str] = None) -> bool:
    """¿Supera www.cccyl.es la verificación TLS? Solo handshake, sin petición HTTP."""
    ctx = ssl.create_default_context(cafile=cafile)
    try:
        with socket.create_connection((HOST, 443), timeout=15) as raw:
            with ctx.wrap_socket(raw, server_hostname=HOST):
                return True
    except ssl.SSLCertVerificationError:
        return False


def _url_aia() -> str:
    """URL «CA Issuers» del certificado del servidor; si no se puede leer, la conocida de Sectigo."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID
        pem = ssl.get_server_certificate((HOST, 443))
        cert = x509.load_pem_x509_certificate(pem.encode())
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
        for desc in aia:
            if desc.access_method == AuthorityInformationAccessOID.CA_ISSUERS:
                return desc.access_location.value
    except Exception as e:  # noqa: BLE001
        log.info("TARCCYL: no se pudo leer la AIA del certificado (%s); se usa la URL de respaldo", e)
    return AIA_RESPALDO


def _construir_bundle() -> str:
    """certifi + certificado intermedio descargado de la URL AIA → BUNDLE_CA."""
    import certifi
    url = _url_aia()
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    der = r.content
    pem = der.decode() if der.lstrip().startswith(b"-----BEGIN") else ssl.DER_cert_to_PEM_cert(der)
    with open(certifi.where(), encoding="ascii") as f:
        base = f.read()
    tmp = BUNDLE_CA + ".tmp"
    with open(tmp, "w", encoding="ascii") as f:
        f.write(base.rstrip("\n") + "\n" + pem.strip() + "\n")
    os.replace(tmp, BUNDLE_CA)
    log.info("TARCCYL: bundle CA con el intermedio de %s guardado en %s", url, BUNDLE_CA)
    return BUNDLE_CA


def _preparar_ssl(sesion: Sesion) -> None:
    """Si la cadena del servidor está incompleta, verifica con un bundle certifi + intermedio.

    Nunca desactiva la verificación: si tampoco así se completa la cadena, lanza RuntimeError.
    """
    if getattr(sesion, "_cyl_ssl", False):
        return
    sesion._cyl_ssl = True  # type: ignore[attr-defined]
    if sesion.s.verify is not True:  # el llamante ya ha fijado su propio bundle
        return
    try:
        if _handshake_ok():
            return
        if not (os.path.exists(BUNDLE_CA) and _handshake_ok(BUNDLE_CA)):
            _construir_bundle()
            if not _handshake_ok(BUNDLE_CA):
                os.remove(BUNDLE_CA)
                raise RuntimeError(f"la cadena TLS de {HOST} sigue sin verificar con el intermedio de {_url_aia()}")
    except OSError as e:
        raise RuntimeError(f"TARCCYL: no se pudo comprobar o completar la cadena TLS de {HOST}: {e}") from e
    sesion.s.verify = BUNDLE_CA
    log.info("TARCCYL: cadena TLS incompleta en el servidor; se verifica con %s", BUNDLE_CA)


# ---------------------------------------------------------------- listado anual

def _url_pdf(href: str) -> str:
    """URL absoluta del PDF con el path bien codificado.

    En 2024+ el href ya viene codificado (`93806-Resoluci%C3%B3n%20185-2024%20.pdf`); en 2012-2013 viene en
    claro (`21354-Resolución 01-2013.pdf`). `requote_uri` codifica lo que falta sin tocar lo ya codificado.
    """
    return requests.utils.requote_uri(absoluta(BASE, href))


def _url_listado(anio: int, offset: int = 0) -> str:
    u = f"{RAIZ}/resoluciones-ano-{anio}"
    return u if offset == 0 else f"{u}.nodos,{offset},{POR_PAGINA}"


def _parsear_listado(html: str, anio: int) -> tuple[list[dict], int]:
    """Devuelve (ítems de la página, mayor offset anunciado por el paginador)."""
    sopa = BeautifulSoup(html, "lxml")
    cont = sopa.select_one("#cmBodyContentChildrens")
    if cont is None:
        return [], 0
    items = []
    for li in cont.select("li.cmContentItem"):
        a = li.select_one("a.cmContentLink[href]")
        if a is None or not RE_FICHA.search(a["href"]):
            continue  # enlaces del menú lateral u otros subcontenidos
        titulo = limpiar(a.get_text(" ")) or ""
        p = li.select_one("p.cmParagraph")
        pdf = li.select_one("a[href*='.ficheros/']")
        items.append({
            "titulo": titulo,
            "url": absoluta(BASE, a["href"]),
            "d": limpiar(p.get_text(" ")) if p else None,
            "pdf": _url_pdf(pdf["href"]) if pdf else None,
        })
    pag = re.compile(rf"resoluciones-ano-{anio}\.nodos,(\d+),\d+")
    offsets = [int(m) for m in pag.findall(str(cont))]
    return items, (max(offsets) if offsets else 0)


def _listado_anual(anio: int, sesion: Sesion) -> list[dict]:
    try:
        r = sesion.get(_url_listado(anio))
    except (RuntimeError, requests.HTTPError) as e:
        if _es_404(e):
            log.info("TARCCYL %d: el listado anual no existe (404)", anio)
            return []
        raise
    items, max_offset = _parsear_listado(r.text, anio)
    vistos = {it["url"] for it in items}
    offset = POR_PAGINA
    while offset <= max_offset:
        pagina, mo = _parsear_listado(sesion.texto(_url_listado(anio, offset)), anio)
        max_offset = max(max_offset, mo)
        nuevos = [it for it in pagina if it["url"] not in vistos]
        if not pagina:
            break
        for it in nuevos:
            vistos.add(it["url"])
        items.extend(nuevos)
        offset += POR_PAGINA
    return items


def _es_404(e: Exception) -> bool:
    resp = getattr(e, "response", None)
    if resp is not None and resp.status_code == 404:
        return True
    return "404" in str(e)


# ---------------------------------------------------------------- ficha

def _parsear_ficha(html: str) -> dict:
    """Pares «Título: valor» de los paramBox de la ficha (claves en minúsculas, sin dos puntos)."""
    sopa = BeautifulSoup(html, "lxml")
    cuerpo = sopa.select_one("#bodyContentDiv") or sopa
    campos: dict[str, Optional[str]] = {}
    for titulo in cuerpo.select(".paramTitle"):
        clave = (limpiar(titulo.get_text(" ")) or "").rstrip(":").strip().lower()
        if not clave:
            continue
        # <div class="paramBox"><span class="paramTitle">Fecha de resolución: </span>30/12/2024</div>
        # <div class="paramBox"><div class="paramTitle">Fundamentos: </div><div><p>…</p></div></div>
        campos[clave] = limpiar("".join(str(x) for x in titulo.next_siblings))
    pdf = cuerpo.select_one("a[href*='.ficheros/']")
    campos["_pdf"] = _url_pdf(pdf["href"]) if pdf else None
    return campos


def _capitalizar(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return s[0].upper() + s[1:]


def _completar_con_ficha(reg: Registro, sesion: Sesion) -> None:
    try:
        campos = _parsear_ficha(sesion.texto(reg.url))
    except (RuntimeError, requests.HTTPError) as e:
        log.warning("TARCCYL: no se pudo abrir la ficha %s: %s", reg.url, e)
        return
    reg.f = fecha_iso(campos.get("fecha de resolución"))
    reg.r = campos.get("número de recurso")
    reg.s = _capitalizar(campos.get("tipo de resolución"))
    reg.o = campos.get("órgano de contratación")
    reg.a = _capitalizar(campos.get("acto recurrido"))
    reg.c = _capitalizar(campos.get("tipo de contrato"))
    if not reg.d:
        reg.d = campos.get("fundamentos") or campos.get("tipo de procedimiento") or campos.get("breve reseña")
    if not reg.pdf:
        reg.pdf = campos.get("_pdf")
    n_ficha = campos.get("número de resolución")
    if n_ficha and numero(n_ficha) != reg.n:
        log.warning("TARCCYL: el nº de la ficha (%s) no coincide con el del listado (%s)", n_ficha, reg.n)


# ---------------------------------------------------------------- interfaz

def listar(anio: int, sesion: Optional[Sesion] = None, fichas: bool = True, omitir=None) -> list[Registro]:
    """Devuelve TODAS las resoluciones del año (recorre la paginación del listado anual).

    Con `fichas=True` (por defecto) abre la ficha de cada resolución para rellenar f, r, s, o, a y c
    (1 petición por registro). Con `fichas=False` se queda con n, d, pdf y url del listado.
    """
    sesion = sesion or Sesion()
    _preparar_ssl(sesion)
    items = _listado_anual(anio, sesion)
    registros: list[Registro] = []
    vistos: set[str] = set()
    for it in items:
        m = RE_FICHA.search(it["url"])
        n = numero(f"{m.group(2)}/{m.group(3)}") if m else numero(it["titulo"], anio)
        reg = Registro(t=TRIBUNAL["id"], n=n, d=it["d"], pdf=it["pdf"], url=it["url"])
        if reg.clave() in vistos:
            log.warning("TARCCYL %d: resolución repetida en el listado: %s", anio, reg.n)
            continue
        vistos.add(reg.clave())
        registros.append(reg)
    if fichas:
        for i, reg in enumerate(registros, 1):
            if omitir and reg.clave() in omitir:   # ya indexada: el orquestador conserva sus campos de ficha
                continue
            _completar_con_ficha(reg, sesion)
            if i % 25 == 0:
                log.info("TARCCYL %d: %d/%d fichas", anio, i, len(registros))
    registros.sort(key=lambda r: int(r.n.split("/")[0]))
    return registros


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    anio = int(args[0]) if args else 2024
    sin_fichas = "--sin-fichas" in sys.argv
    maximo = next((int(a.split("=", 1)[1]) for a in sys.argv[1:] if a.startswith("--max=")), None)

    ses = Sesion()
    peticiones = 0
    _get = ses.get

    def _contar(url, **kw):
        global peticiones
        peticiones += 1
        return _get(url, **kw)
    ses.get = _contar  # type: ignore[assignment]

    if maximo:
        regs = listar(anio, ses, fichas=False)[:maximo]
        if not sin_fichas:
            for r in regs:
                _completar_con_ficha(r, ses)
            regs.sort(key=lambda r: int(r.n.split("/")[0]))
    else:
        regs = listar(anio, ses, fichas=not sin_fichas)

    print(f"TARCCYL {anio}: {len(regs)} registros en {peticiones} peticiones HTTP")
    for r in regs[:3] + (regs[-3:] if len(regs) > 3 else []):
        print(r.limpio())
    if regs:
        con = lambda campo: sum(1 for r in regs if getattr(r, campo)) * 100 // len(regs)  # noqa: E731
        print(f"con pdf: {con('pdf')} %  con fecha: {con('f')} %  con recurso: {con('r')} %  "
              f"con tipo: {con('s')} %  con órgano: {con('o')} %  con acto: {con('a')} %  con descripción: {con('d')} %")
    claves = [r.clave() for r in regs]
    repetidas = {c for c in claves if claves.count(c) > 1}
    print("claves repetidas:", sorted(repetidas) if repetidas else "ninguna")
