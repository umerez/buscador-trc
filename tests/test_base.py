"""Pruebas de los normalizadores comunes. Ejecutar: python3 -m unittest discover tests"""
import unittest

from scrapers.base import Registro, fecha_iso, limpiar, numero


class TestNormalizadores(unittest.TestCase):
    def test_numero(self):
        self.assertEqual(numero("0100/2024"), "100/2024")
        self.assertEqual(numero("Resolución nº 400-2025"), "400/2025")
        self.assertEqual(numero("352", 2023), "352/2023")
        self.assertEqual(numero("185/24"), "185/2024")
        self.assertEqual(numero("001/2024"), "1/2024")

    def test_fecha(self):
        self.assertEqual(fecha_iso("En Madrid, a 25 de septiembre de 2025."), "2025-09-25")
        self.assertEqual(fecha_iso("31 de maig de 2023"), "2023-05-31")
        self.assertEqual(fecha_iso("15/07/2024"), "2024-07-15")
        self.assertEqual(fecha_iso("2024-07-15"), "2024-07-15")
        self.assertEqual(fecha_iso("2 de xullo de 2024"), "2024-07-02")
        self.assertIsNone(fecha_iso("de 5 de diciembre"))
        self.assertIsNone(fecha_iso("31/02/2024"))

    def test_limpiar(self):
        self.assertEqual(limpiar('<a href="x">Hola &amp; adiós</a>  '), "Hola & adiós")
        self.assertIsNone(limpiar("  "))

    def test_registro(self):
        r = Registro(t="madrid", n="400/2025", f="2025-09-25", pdf="https://x/y.pdf")
        self.assertEqual(r.limpio(), {"t": "madrid", "n": "400/2025", "f": "2025-09-25", "pdf": "https://x/y.pdf"})
        self.assertEqual(r.clave(), "madrid|resolucion|400/2025")
        self.assertEqual(Registro(t="aragon", n="15/2024", k="cautelar").clave(), "aragon|cautelar|15/2024")


if __name__ == "__main__":
    unittest.main()


class TestSaneado(unittest.TestCase):
    def test_sanear(self):
        from datetime import date
        import construir_indice as ci
        hoy = date(2026, 10, 11)
        regs = [
            {"t": "madrid", "n": "522/2025", "f": "2026-12-09", "pdf": "https://x/resolucion_522-2025_expte_528-2025_.pdf"},
            {"t": "madrid", "n": "411/2023", "f": "2026-07-30", "pdf": "https://x/resolucion_411-2026_expediente_379-2026_.pdf"},
            {"t": "andalucia", "n": "230/200", "f": "2020-07-02", "pdf": "https://x/Resolucion230.pdf"},
            {"t": "cataluna", "n": "144/2010", "f": "2020-04-07", "pdf": "https://x/resolucio-num-144-2020.pdf"},
            {"t": "canarias", "n": "171/2016", "f": "2016-05-02", "pdf": "https://x/RES-171-2016-REMC-41-2016-L.pdf"},
            {"t": "madrid", "n": "122/2026", "f": "2026-12-03", "pdf": "https://x/resolucion_122-2026_expediente_096-2026_0.pdf"},
        ]
        out = {r["t"] + r["n"]: r for r in ci.sanear(regs, hoy)}
        self.assertEqual(out["madrid522/2025"]["f"], "2025-12-09")
        self.assertIn("madrid411/2026", out)
        self.assertIn("andalucia230/2020", out)
        self.assertIn("cataluna144/2020", out)
        self.assertEqual(out["canarias171/2016"]["f"], "2016-05-02")
        self.assertEqual(out["madrid122/2026"]["f"], "2026-12-03")  # no se puede resolver: se deja
