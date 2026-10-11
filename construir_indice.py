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
        try:
            nuevos = mod.listar(anio, sesion) if sesion is not None else mod.listar(anio)
        except Exception as e:  # noqa: BLE001
            log.error("%s %d: %s", tid, anio, e)
            resumen["ok"] = False
            resumen["error"] = f"{anio}: {e}"
            resumen["anios"][str(anio)] = {"error": str(e)}
            continue
        nuevos_d = [r.limpio() for r in nuevos]
        antiguos_anio = [k for k, r in por_clave.items() if anio_de(r["n"]) == anio]
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
    registros = sorted(por_clave.values(), key=orden, reverse=True)
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
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if args.solo_meta:
        meta = escribir_meta()
        print(f"meta.json: {meta['total']} registros")
        return 0

    hoy = date.today()
    ids = args.tribunal or [t for t in TRIBUNALES if t != "tacrc"]
    estado = leer_json(DATOS / "estado.json", {})
    fallos = 0
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
        if not hasattr(mod, "listar") or tid == "tacrc":
            continue
        log.info("== %s: años %s", tid, anios)
        res = actualizar_tribunal(tid, anios, estado)
        if not res["ok"]:
            fallos += 1
        escribir_json(DATOS / "estado.json", estado, compacto=False)
    meta = escribir_meta()
    print(f"Índice: {meta['total']} registros. Tribunales con incidencias: {fallos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
