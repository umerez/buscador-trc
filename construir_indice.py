#!/usr/bin/env python3
"""Construye o actualiza el índice de resoluciones que sirve la página web (docs/data/*.json).

Uso:
  python3 construir_indice.py --actual                 # año en curso (y el anterior en enero-febrero): lo que corre cada noche
  python3 construir_indice.py --completo               # todos los años de todos los tribunales (backfill)
  python3 construir_indice.py --tribunal madrid --desde 2020 --hasta 2024
  python3 construir_indice.py --tribunal oarc --completo

Para cada tribunal y año recorrido, sustituye en docs/data/<tribunal>.json los registros de ese año por los
recién obtenidos (salvo que el nuevo recuento sea sospechosamente bajo, en cuyo caso conserva los antiguos y avisa).
Escribe también docs/data/meta.json (tribunales, recuentos por año, fecha) y docs/data/estado.json (resultado de la
última pasada por tribunal).
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import re
import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "docs" / "data"
TRIBUNALES = ["tacrc", "madrid", "cyl", "andalucia", "galicia", "navarra", "cataluna", "aragon", "oarc", "canarias"]
UMBRAL_SOSPECHA = 0.5   # si el año nuevo trae menos de la mitad que el guardado, no se sustituye

log = logging.getLogger("indice")


class ContadorAvisos(logging.Handler):
    """Cuenta los WARNING de cada tribunal para que el resumen final no diga «0 incidencias» con avisos pendientes.

    Los reintentos de red («intento 1/3 falló») no cuentan: si los tres fallan, el tribunal ya se marca como fallido.
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.mensajes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if not msg.startswith("intento "):
            self.mensajes.append(msg)

    def reiniciar(self) -> list[str]:
        previos, self.mensajes = self.mensajes, []
        return previos


def cargar_modulo(tid: str):
    return importlib.import_module(f"scrapers.{tid}")


def anio_de(n: str) -> int | None:
    try:
        return int(n.rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return None


def leer_json(ruta: Path, defecto):
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    return defecto


def escribir_json(ruta: Path, datos, compacto=True):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        if compacto:
            json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        f.write("\n")


# ---------------------------------------------------------------- saneamiento

RE_PDF_NUM = re.compile(r"(?:resoluci[oó]n?|resolucio|acuerdo|acord|res)[^\d/]{0,8}(\d{1,4})[-_](\d{2}|\d{4})(?![\d])", re.I)


def _anio_valido(a: int, hoy: date) -> bool:
    return 2010 <= a <= hoy.year + 1


def _num_anio_pdf(pdf: str | None, hoy: date):
    """(número, año) que sugiere el nombre del PDF, o None."""
    if not pdf:
        return None
    nombre = pdf.rsplit("/", 1)[-1]
    m = RE_PDF_NUM.search(nombre)
    if not m:
        return None
    num, an = int(m.group(1)), int(m.group(2))
    if an < 100:
        an += 2000
    return (num, an) if _anio_valido(an, hoy) else None


def sanear(registros: list[dict], hoy: date | None = None) -> list[dict]:
    """Corrige errores evidentes de origen (año imposible en el número, fecha en el futuro o a años del número)
    cuando el nombre del PDF o la propia fecha lo resuelven sin ambigüedad. Lo que no se puede resolver se deja.
    Después deduplica por clave quedándose con el registro más completo."""
    hoy = hoy or date.today()
    limite = hoy.toordinal() + 7
    salida: dict[str, dict] = {}
    # fechas por (tribunal, año del número) → {nº: fecha}, para comprobar que una fecha corregida encaja con sus vecinas
    vecinas: dict[tuple, dict[int, str]] = {}
    for r in registros:
        try:
            ns, an_ = r["n"].split("/")
            if r.get("f") and not r.get("k") and ns.isdigit():
                vecinas.setdefault((r["t"], int(an_)), {})[int(ns)] = r["f"]
        except ValueError:
            continue
    for r in registros:
        r = dict(r)
        try:
            num_s, an_s = r["n"].split("/")
            num, an = int(num_s), int(an_s)
        except ValueError:
            salida.setdefault(f"{r['t']}|{r.get('k', 'resolucion')}|{r['n']}", r)
            continue
        pista = _num_anio_pdf(r.get("pdf"), hoy)
        f_an = int(r["f"][:4]) if r.get("f") else None
        original = r["n"]
        # A) año imposible en el número → el del PDF (mismo número) o, si no, el de la fecha
        if not _anio_valido(an, hoy):
            if pista and pista[0] == num:
                an = pista[1]
            elif f_an and _anio_valido(f_an, hoy):
                an = f_an
        # B) el PDF (mismo número) y la fecha coinciden en otro año → el número lleva el año mal
        elif pista and pista[0] == num and pista[1] != an and f_an == pista[1]:
            an = pista[1]
        if an != int(an_s):
            r["n"] = f"{num}/{an}"
            log.info("saneado %s: número %s → %s (pdf %s)", r["t"], original, r["n"], (r.get("pdf") or "").rsplit("/", 1)[-1])
        # C) fecha a más de un año del número, o en el futuro, con el PDF de acuerdo con el número → año de la fecha mal
        if r.get("f") and f_an is not None:
            lejos = abs(f_an - an) > 1
            futura = date.fromisoformat(r["f"]).toordinal() > limite and f_an != an
            if (lejos or futura) and (pista is None or pista[1] == an):
                try:
                    nueva = date(an, int(r["f"][5:7]), int(r["f"][8:10])).isoformat()
                except ValueError:
                    nueva = None
                if nueva and date.fromisoformat(nueva).toordinal() <= limite:
                    log.info("saneado %s %s: fecha %s → %s", r["t"], r["n"], r["f"], nueva)
                    r["f"] = nueva
        # D) fecha futura aunque sea del mismo año del número (12/03 leída como 03/12): se corrige solo si intercambiar
        #    día y mes la deja en el pasado Y encaja entre las fechas de las resoluciones de número anterior y posterior;
        #    si no, se deja y se avisa
        if r.get("f") and date.fromisoformat(r["f"]).toordinal() > limite:
            fd = date.fromisoformat(r["f"])
            alt = None
            if fd.day <= 12:
                try:
                    alt = date(fd.year, fd.day, fd.month)
                except ValueError:
                    alt = None
            ok = False
            if alt is not None and alt.toordinal() <= limite:
                tabla = vecinas.get((r["t"], an), {})
                ant = [tabla[i] for i in range(num - 1, max(num - 4, 0), -1) if i in tabla]
                pos = [tabla[i] for i in range(num + 1, num + 4) if i in tabla]
                if ant and pos:
                    ok = ant[0] <= alt.isoformat() <= pos[0]
            if ok:
                log.info("saneado %s %s: fecha futura %s → %s (día y mes intercambiados; encaja con las vecinas)", r["t"], r["n"], r["f"], alt.isoformat())
                r["f"] = alt.isoformat()
            else:
                log.warning("%s %s: fecha futura %s sin corrección posible", r["t"], r["n"], r["f"])
        k = f"{r['t']}|{r.get('k', 'resolucion')}|{r['n']}"
        previo = salida.get(k)
        if previo is None or len(r) > len(previo):
            if previo is not None:
                log.info("saneado %s: %s duplicado tras corregir; se conserva el más completo", r["t"], r["n"])
            salida[k] = r
    return list(salida.values())


def orden(reg: dict):
    return (reg.get("f") or "", anio_de(reg["n"]) or 0, int(reg["n"].split("/")[0]) if reg["n"].split("/")[0].isdigit() else 0)


def actualizar_tribunal(tid: str, anios: list[int], estado: dict) -> dict:
    mod = cargar_modulo(tid)
    ruta = DATOS / f"{tid}.json"
    existentes = leer_json(ruta, [])
    por_clave = {f"{r['t']}|{r.get('k', 'resolucion')}|{r['n']}": r for r in existentes}
    t0 = time.monotonic()
    resumen = {"ok": True, "anios": {}, "error": None}
    sesion = None
    try:
        from scrapers.base import Sesion
        sesion = Sesion(encoding=getattr(mod, "ENCODING", None))
    except Exception:  # pragma: no cover
        sesion = None
    pausa_anios = getattr(mod, "PAUSA_ENTRE_ANIOS", 0)
    for i, anio in enumerate(anios):
        if anio < mod.TRIBUNAL["desde"]:
            continue
        if i and pausa_anios:
            time.sleep(pausa_anios)
        antiguos_anio = [k for k, r in por_clave.items() if anio_de(r["n"]) == anio]
        acepta_omitir = "omitir" in inspect.signature(mod.listar).parameters
        try:
            if acepta_omitir:
                # Scrapers con ficha por registro: no reabren las fichas ya indexadas; sus campos se conservan abajo.
                nuevos = mod.listar(anio, sesion, omitir=set(antiguos_anio))
            else:
                nuevos = mod.listar(anio, sesion) if sesion is not None else mod.listar(anio)
        except Exception as e:  # noqa: BLE001
            log.error("%s %d: %s", tid, anio, e)
            resumen["ok"] = False
            resumen["error"] = f"{anio}: {e}"
            resumen["anios"][str(anio)] = {"error": str(e)}
            continue
        nuevos_d = [r.limpio() for r in nuevos]
        if acepta_omitir:
            fusionados = []
            for r in nuevos_d:
                k = f"{r['t']}|{r.get('k', 'resolucion')}|{r['n']}"
                viejo = por_clave.get(k)
                if viejo:
                    # lo nuevo del listado manda, salvo el PDF (la ficha suele dar la URL directa) y los campos que el listado no trae
                    r = {**viejo, **r, **({"pdf": viejo["pdf"]} if viejo.get("pdf") else {})}
                fusionados.append(r)
            nuevos_d = fusionados
        if antiguos_anio and len(nuevos_d) < UMBRAL_SOSPECHA * len(antiguos_anio):
            log.warning("%s %d: solo %d registros nuevos frente a %d guardados; se conservan los guardados",
                        tid, anio, len(nuevos_d), len(antiguos_anio))
            resumen["anios"][str(anio)] = {"conservado": len(antiguos_anio), "obtenido": len(nuevos_d)}
            resumen["ok"] = False
            resumen["error"] = f"{anio}: recuento sospechoso ({len(nuevos_d)} < {len(antiguos_anio)})"
            continue
        for k in antiguos_anio:
            del por_clave[k]
        for r in nuevos_d:
            por_clave[f"{r['t']}|{r.get('k', 'resolucion')}|{r['n']}"] = r
        resumen["anios"][str(anio)] = {"registros": len(nuevos_d)}
        log.info("%s %d: %d registros", tid, anio, len(nuevos_d))
    registros = sorted(sanear(list(por_clave.values())), key=orden, reverse=True)
    escribir_json(ruta, registros)
    resumen["total"] = len(registros)
    resumen["segundos"] = round(time.monotonic() - t0, 1)
    resumen["fecha"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    estado[tid] = resumen
    return resumen


def escribir_meta():
    tribunales = []
    total = 0
    for tid in TRIBUNALES:
        try:
            mod = cargar_modulo(tid)
        except ModuleNotFoundError:
            log.warning("sin scraper para %s; se omite en meta.json", tid)
            continue
        info = dict(mod.TRIBUNAL)
        registros = leer_json(DATOS / f"{tid}.json", [])
        por_anio: dict[str, int] = {}
        for r in registros:
            a = anio_de(r["n"])
            if a:
                por_anio[str(a)] = por_anio.get(str(a), 0) + 1
        info["total"] = len(registros)
        info["anios"] = dict(sorted(por_anio.items()))
        info["fichero"] = f"data/{tid}.json" if registros else None
        total += len(registros)
        tribunales.append(info)
    meta = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": total,
        "tribunales": tribunales,
    }
    escribir_json(DATOS / "meta.json", meta, compacto=False)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tribunal", action="append", help="id del tribunal (repetible); por defecto todos")
    ap.add_argument("--desde", type=int)
    ap.add_argument("--hasta", type=int)
    ap.add_argument("--actual", action="store_true", help="año en curso, y el anterior si estamos en enero o febrero")
    ap.add_argument("--completo", action="store_true", help="desde el primer año de cada tribunal")
    ap.add_argument("--solo-meta", action="store_true", help="no recorre nada; regenera meta.json")
    ap.add_argument("--sanear", action="store_true", help="no recorre nada; aplica el saneamiento a los ficheros guardados y regenera meta.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if args.sanear:
        for tid in TRIBUNALES:
            ruta = DATOS / f"{tid}.json"
            if ruta.exists():
                regs = leer_json(ruta, [])
                escribir_json(ruta, sorted(sanear(regs), key=orden, reverse=True))
        meta = escribir_meta()
        print(f"meta.json: {meta['total']} registros")
        return 0
    if args.solo_meta:
        meta = escribir_meta()
        print(f"meta.json: {meta['total']} registros")
        return 0

    hoy = date.today()
    ids = args.tribunal or list(TRIBUNALES)
    estado = leer_json(DATOS / "estado.json", {})
    fallos = 0
    con_avisos: dict[str, int] = {}
    contador = ContadorAvisos()
    logging.getLogger().addHandler(contador)
    for tid in ids:
        mod = cargar_modulo(tid)
        if args.completo:
            anios = list(range(mod.TRIBUNAL["desde"], hoy.year + 1))
        elif args.actual:
            anios = [hoy.year] if hoy.month > 2 else [hoy.year - 1, hoy.year]
        else:
            desde = args.desde or hoy.year
            hasta = args.hasta or desde
            anios = list(range(desde, hasta + 1))
        if not hasattr(mod, "listar"):
            continue
        log.info("== %s: años %s", tid, anios)
        contador.reiniciar()
        res = actualizar_tribunal(tid, anios, estado)
        avisos = contador.reiniciar()
        if avisos:
            res["avisos"] = len(avisos)
            res["avisos_detalle"] = [a[:220] for a in avisos[:6]]
            con_avisos[tid] = len(avisos)
        if not res["ok"]:
            fallos += 1
        escribir_json(DATOS / "estado.json", estado, compacto=False)
    meta = escribir_meta()
    extra = ", ".join(f"{t} {n}" for t, n in con_avisos.items()) or "ninguno"
    print(f"Índice: {meta['total']} registros. Tribunales con incidencias: {fallos}. Tribunales con avisos: {len(con_avisos)} ({extra})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
