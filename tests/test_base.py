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
