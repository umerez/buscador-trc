"""Scrapers de los repositorios públicos de resoluciones de los tribunales de recursos contractuales.

Cada módulo expone:
    TRIBUNAL: dict con id, nombre, siglas, ámbito, url del buscador oficial, idioma, cobertura (año inicial)
    listar(anio: int) -> list[Registro]   # todas las resoluciones del año (recorre la paginación)

El esquema del registro está en scrapers/base.py (clase Registro).
"""
