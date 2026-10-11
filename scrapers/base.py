"""Utilidades comunes de los scrapers: sesión HTTP, pausas, reintentos, normalización y esquema."""
from __future__ import annotations

import html as _html
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Iterable, Optional

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
PAUSA = 0.6          # segundos entre peticiones a un mismo servidor
REINTENTOS = 3
TIMEOUT = 60

log = logging.getLogger("scrapers")


@dataclass
class Registro:
    """Una resolución (o acuerdo) de un tribunal de recursos contractuales.

    Campos cortos a propósito: el JSON resultante se sirve entero al navegador.
    """
    t: str                      # id del tribunal (madrid, cyl, andalucia, galicia, navarra, cataluna, aragon, oarc, canarias, tacrc)
    n: str                      # nº de resolución normalizado "400/2025" (sin ceros a la izquierda)
    f: Optional[str] = None     # fecha de la resolución ISO "2025-09-25" (None si no consta)
    r: Optional[str] = None     # nº de recurso / expediente tal como lo cita el tribunal ("375/2025", "RE 18/2024", "EB 2023/260", "REMC 241-2026", "N-2022-0457")
    s: Optional[str] = None     # sentido / tipo de resolución (Estimatoria, Desestimatoria, Estimación parcial, Inadmisión, Desistimiento, ...)
    o: Optional[str] = None     # órgano de contratación / poder adjudicador / administración recurrida
    d: Optional[str] = None     # descripción: objeto del contrato, resumen o título
    a: Optional[str] = None     # acto recurrido (adjudicación, pliegos, exclusión, ...)
    c: Optional[str] = None     # tipo de contrato (servicios, obras, suministros, ...)
    k: Optional[str] = None     # clase de documento: "resolucion" (por defecto), "acuerdo", "rectificacion", "cautelar"
    pdf: Optional[str] = None   # URL absoluta del PDF (versión principal: castellano si existe; si no, el original)
    p2: Optional[str] = None    # URL del PDF en el otro idioma oficial (Galicia: original gallego; OARC: euskera)
    url: Optional[str] = None   # URL absoluta de la ficha HTML (si existe)

    def clave(self) -> str:
        return f"{self.t}|{self.k or 'resolucion'}|{self.n}"

    def limpio(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if v not in (None, "", [])}
        if d.get("k") == "resolucion":
            del d["k"]
        return d


# ---------------------------------------------------------------- HTTP

class Sesion:
    """requests.Session con User-Agent de navegador, pausa entre peticiones y reintentos."""

    def __init__(self, pausa: float = PAUSA, encoding: Optional[str] = None):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9,eu;q=0.8,ca;q=0.8,gl;q=0.8"})
        self.pausa = pausa
        self.encoding = encoding
        self._ultima = 0.0

    def _espera(self):
        dt = time.monotonic() - self._ultima
        if dt < self.pausa:
            time.sleep(self.pausa - dt)
        self._ultima = time.monotonic()

    def _pedir(self, metodo: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", TIMEOUT)
        ultimo = None
        for intento in range(1, REINTENTOS + 1):
            self._espera()
            try:
                r = self.s.request(metodo, url, **kw)
                if r.status_code >= 500:
                    raise requests.HTTPError(f"{r.status_code} en {url}", response=r)
                if 400 <= r.status_code < 500:
                    # Los 4xx son definitivos: no se reintentan. El mensaje lleva el código para que el
                    # scraper pueda tratar un 404 (año inexistente) como lista vacía.
                    err = RuntimeError(f"{r.status_code} en {url}")
                    err.status_code = r.status_code
                    raise err
                if self.encoding:
                    r.encoding = self.encoding
                return r
            except (requests.RequestException, ConnectionError) as e:  # noqa: PERF203
                ultimo = e
                log.warning("intento %d/%d falló: %s", intento, REINTENTOS, e)
                time.sleep(2 * intento)
        raise RuntimeError(f"Sin respuesta de {url}: {ultimo}")

    def get(self, url: str, **kw) -> requests.Response:
        return self._pedir("GET", url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        return self._pedir("POST", url, **kw)

    def texto(self, url: str, **kw) -> str:
        return self.get(url, **kw).text

    def json(self, url: str, **kw):
        return self.get(url, **kw).json()


# ---------------------------------------------------------------- normalización

MESES = {
    # castellano
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    # catalán
    "gener": 1, "febrer": 2, "març": 3, "maig": 5, "juny": 6, "juliol": 7, "agost": 8,
    "setembre": 9, "novembre": 11, "desembre": 12,
    # gallego
    "xaneiro": 1, "febreiro": 2, "marzo_gl": 3, "xuño": 6, "xullo": 7, "setembro": 9, "outubro": 10, "decembro": 12,
    # euskera
    "urtarrila": 1, "otsaila": 2, "martxoa": 3, "apirila": 4, "maiatza": 5, "ekaina": 6, "uztaila": 7,
    "abuztua": 8, "iraila": 9, "urria": 10, "azaroa": 11, "abendua": 12,
}


def limpiar(s: Optional[str]) -> Optional[str]:
    """Quita etiquetas, entidades HTML y espacios sobrantes."""
    if s is None:
        return None
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def numero(n: str, anio: Optional[int] = None) -> str:
    """Normaliza '0100/2024', '100-2024', '100_2024', '100/24' → '100/2024'. Si solo hay número, añade el año."""
    n = limpiar(n) or ""
    m = re.search(r"(\d{1,4})\s*[/\-_]\s*(\d{2,4})", n)
    if m:
        num, an = int(m.group(1)), int(m.group(2))
        if an < 100:
            an += 2000
        return f"{num}/{an}"
    m = re.search(r"\d{1,4}", n)
    if m and anio:
        return f"{int(m.group(0))}/{anio}"
    return n


def fecha_iso(s: Optional[str]) -> Optional[str]:
    """Acepta dd/mm/aaaa, dd-mm-aaaa, aaaa-mm-dd, 'a 25 de septiembre de 2025', '31 de maig de 2023', 'de 5 de diciembre' + año aparte no."""
    if not s:
        return None
    s = limpiar(s) or ""
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return _iso(y, mo, d)
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", s)
    if m:
        d, mo, y = map(int, m.groups())
        if y < 100:
            y += 2000
        return _iso(y, mo, d)
    m = re.search(r"(\d{1,2})\s+(?:de\s+|d')?([a-zA-Zçñáéíóúü]+)\s+(?:de\s+|del\s+)?(\d{4})", s)
    if m:
        d, mes, y = int(m.group(1)), sin_acentos(m.group(2).lower()), int(m.group(3))
        for k, v in MESES.items():
            if sin_acentos(k.split("_")[0]) == mes:
                return _iso(y, v, d)
    return None


def _iso(y: int, mo: int, d: int) -> Optional[str]:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def absoluta(base: str, href: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base, _html.unescape(href.strip()))


# ---------------------------------------------------------------- persistencia

def guardar(registros: Iterable[Registro], ruta) -> int:
    datos = [r.limpio() for r in registros]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    return len(datos)
