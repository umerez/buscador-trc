"""Pruebas de las correcciones del 17/10/2026 (Madrid, Andalucía, Cataluña) con servidores simulados.

Ejecutar: python3 -m pytest tests   (o python3 -m unittest discover tests)
"""
import logging
import random
import unittest
from datetime import date, datetime, timedelta

from scrapers import andalucia, cataluna, madrid
from scrapers.base import Registro


# ---------------------------------------------------------------- Madrid: paginación de orden inestable

class SesionMadridFalsa:
    """Imita el buscador Drupal del TACP: 5 por página y, entre resoluciones con la misma fecha, un orden
    distinto en cada petición (justo lo que hace que se repitan unas filas y se salten otras)."""

    def __init__(self, items, semilla=1):
        self.items = items          # [(número, fecha)]
        self.rng = random.Random(semilla)
        self.peticiones = 0

    def texto(self, url, params=None, **kw):
        self.peticiones += 1
        ini = datetime.strptime(params["field_fecha[date]"], "%d/%m/%Y").date()
        fin = datetime.strptime(params["field_fecha_1[date]"], "%d/%m/%Y").date()
        pagina = int(params["page"])
        sel = [it for it in self.items if ini <= it[1] <= fin]
        if not sel:
            return "<html><body><p>Sin resultados</p></body></html>"
        self.rng.shuffle(sel)
        sel.sort(key=lambda it: it[1], reverse=True)       # sort estable: los empates quedan barajados
        filas = sel[pagina * 5:(pagina + 1) * 5]
        lis = "".join(
            f'<li class="views-row"><div class="views-field views-field-field-numero-de-resolucion">'
            f'<a href="/tacp/resolucion/{n}2026">{n}/2026</a></div>'
            f'<div class="views-field views-field-field-fecha"><span class="date-display-single" '
            f'content="{f.isoformat()}T00:00:00+01:00">{f:%d/%m/%Y}</span></div></li>'
            for n, f in filas)
        return (f'<html><body><div class="view-content"><div>{len(filas)} registros de {len(sel)}</div>'
                f'<ul>{lis}</ul></div></body></html>')


def _items_madrid(total=508, semilla=7):
    rng = random.Random(semilla)
    dias, d = [], date(2026, 1, 8)
    while len(dias) < 120:
        if d.weekday() < 5:
            dias.append(d)
        d += timedelta(days=1)
    items = []
    for n in range(1, total + 1):
        items.append((n, dias[min(int(n / total * 119 + rng.choice([0, 0, 1])), 119)]))
    return items


class TestMadridRangos(unittest.TestCase):
    def test_lee_todo_aunque_el_orden_sea_inestable(self):
        items = _items_madrid()
        # hay días con muchas resoluciones el mismo día (el caso real llega a 26)
        mayor = max(sum(1 for _, f in items if f == d) for d in {f for _, f in items})
        self.assertGreaterEqual(mayor, 6)
        ses = SesionMadridFalsa(items)
        regs = madrid.listar(2026, ses, fichas=False)
        self.assertEqual(len({r.clave() for r in regs}), 508)
        self.assertEqual(len(regs), 508)

    def test_sin_resultados(self):
        self.assertEqual(madrid.listar(2026, SesionMadridFalsa([]), fichas=False), [])

    def test_dia_que_no_se_puede_completar_se_avisa(self):
        items = _items_madrid(40)
        items.append(items[0])  # misma resolución dos veces el mismo día: el contador cuenta 41 y las claves son 40
        with self.assertLogs("scrapers.madrid", level="WARNING") as cm:
            regs = madrid.listar(2026, SesionMadridFalsa(items), fichas=False)
        self.assertEqual(len(regs), 40)
        self.assertTrue(any("contador" in m for m in cm.output))


# ---------------------------------------------------------------- Andalucía: duplicados con título mal tecleado

def _reg(n, r, pdf, f="2026-06-19"):
    return Registro(t="andalucia", n=n, f=f, r=r,
                    pdf=f"https://www.juntadeandalucia.es/sites/default/files/2026-06/{pdf}")


class TestAndaluciaDuplicados(unittest.TestCase):
    def test_gana_la_fila_cuyo_pdf_cuadra(self):
        # 401/2026: dos filas con el mismo recurso, una enlaza al PDF de la 396 (error de origen)
        mala = _reg("401/2026", "353/2026", "Resoluci%C3%B3n_396_2026_Recurso_368_2026.pdf")
        buena = _reg("401/2026", "353/2026", "Resoluci%C3%B3n_401_2026_Recurso_353_2026.pdf", f="2026-06-18")
        for orden in ([mala, buena], [buena, mala]):
            out = andalucia._deduplicar(list(orden), 2026)
            self.assertEqual(len(out), 1)
            self.assertIn("401_2026_Recurso_353", out[0].pdf)

    def test_titulo_equivocado_se_reubica_si_su_numero_esta_libre(self):
        a = _reg("369/2026", "332/2026", "Resoluci%C3%B3n_369_2026_Recurso_332_2026.pdf")
        b = _reg("369/2026", "368/2026", "Resoluci%C3%B3n_396_2026_Recurso_368_2026.pdf")
        out = andalucia._deduplicar([a, b], 2026)
        self.assertEqual(sorted(r.n for r in out), ["369/2026", "396/2026"])
        self.assertEqual(len({r.clave() for r in out}), 2)

    def test_sin_arreglo_no_deja_claves_repetidas_y_avisa(self):
        a = _reg("589/2026", "590/2026", "Resoluci%C3%B3n_589_2026_Recurso_590_2026_0.pdf")
        b = _reg("589/2026", "577/2026", "Resoluci%C3%B3n_589_2026_Recurso_577_2026.pdf")
        with self.assertLogs("scrapers.andalucia", level="WARNING") as cm:
            out = andalucia._deduplicar([a, b], 2026)
        self.assertEqual(len(out), 1)
        self.assertTrue(any("589/2026" in m and "descarta" in m for m in cm.output))

    def test_resubidas_conservan_la_de_fecha_mas_reciente(self):
        a = _reg("63/2026", "19/2026", "Resoluci%C3%B3n_63_2026_Recurso_19_2026.pdf", f="2026-02-10")
        b = _reg("63/2026", "19/2026", "Resoluci%C3%B3n_63_2026_Recurso_19_2026_0.pdf", f="2026-02-12")
        out = andalucia._deduplicar([a, b], 2026)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].pdf.endswith("_0.pdf"))


# ---------------------------------------------------------------- Cataluña: relectura mes a mes

def _articulo(n, f):
    return (f'<article class="llistat_cerca_avancada"><a title="Resolució núm. {n}/2026, de {f.day} de març" '
            f'href="/ca/contacte/tccsp/cercador-resolucions/resolucio/r{n}">x</a>'
            f'<a href="/.content/contacte/tccsp/resolucions/2026/resolucio-num-{n}-2026.pdf">pdf</a>'
            f'<span>{f:%d/%m/%Y}</span><div class="descripcio">Estimació. Algo.</div></article>')


class SesionCatalunaFalsa:
    """El año entero devuelve 10 resoluciones menos de las que declara; por meses salen todas."""

    def __init__(self, n=40):
        self.items = [(i, date(2026, 1 + (i - 1) * 12 // n, 15)) for i in range(1, n + 1)]
        self.ocultas = {i for i, _ in self.items[:10]}

    def texto(self, url, params=None, **kw):
        ini = datetime.strptime(params["datainf"], "%d/%m/%Y").date()
        fin = datetime.strptime(params["datasup"], "%d/%m/%Y").date()
        sel = [(i, f) for i, f in self.items if ini <= f <= fin]
        anual = (fin - ini).days > 200
        visibles = [(i, f) for i, f in sel if not (anual and i in self.ocultas)]
        if "page74bdffe4-cd83-11ea-a60c-005056924a59" in params:
            visibles = []          # la paginación clásica tampoco los devuelve
        return (f'<html><body><p class="txt_result">S\'han trobat <span>{len(sel)}</span> resultats</p>'
                + "".join(_articulo(i, f) for i, f in visibles) + "</body></html>")


class TestCatalunaMeses(unittest.TestCase):
    def test_relee_mes_a_mes_si_el_contador_no_cuadra(self):
        regs = cataluna._listado(SesionCatalunaFalsa(), 2026)
        self.assertEqual(len(regs), 40)


if __name__ == "__main__":
    unittest.main()
