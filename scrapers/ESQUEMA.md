# Esquema común de los scrapers

Cada módulo `scrapers/<tribunal>.py` define:

```python
TRIBUNAL = {
    "id": "madrid",                       # identificador corto, el mismo que Registro.t
    "siglas": "TACP Madrid",
    "nombre": "Tribunal Administrativo de Contratación Pública de la Comunidad de Madrid",
    "ambito": "Comunidad de Madrid",
    "buscador": "https://www.comunidad.madrid/tacp/busquedaresoluciones",
    "idioma": "es",                       # idioma de los documentos: es, ca, gl, eu
    "desde": 2011,                        # primer año con resoluciones en el repositorio
    "documento": "Resolución",            # cómo llama el tribunal a sus decisiones: Resolución / Acuerdo
}

def listar(anio: int, sesion: Sesion | None = None) -> list[Registro]:
    """Devuelve TODAS las resoluciones del año (recorre la paginación). Puede devolver [] si el año no existe."""
```

Reglas:

- Importar de `scrapers.base`: `Registro, Sesion, limpiar, numero, fecha_iso, absoluta`.
- `n` siempre normalizado con `numero()` → `"400/2025"`. `f` en ISO con `fecha_iso()`.
- `pdf`, `p2` y `url` absolutas. `pdf` es la versión en castellano cuando el tribunal la ofrece (Galicia) y `p2` el original gallego; en el OARC `pdf` es el castellano y `p2` el euskera. Si el PDF no se puede conocer sin abrir la ficha y la ficha es barata, abrir la ficha; si es caro (más de ~1 petición por registro) y existe otra vía, documentarlo en el docstring.
- Un registro por resolución. Los acuerdos, rectificaciones y cautelares con serie propia llevan `k`.
- No capturar más de lo necesario: nada de texto completo de la resolución (el índice se sirve entero al navegador).
- Si un año no tiene resultados, devolver `[]`, no fallar.
- Mantener la pausa de `Sesion` (0,6 s por petición). Son servidores públicos.
- Cada módulo se puede ejecutar solo: `python3 -m scrapers.<tribunal> 2024` imprime cuántos registros ha encontrado,
  los tres primeros y los tres últimos, y comprueba que no haya claves repetidas.
