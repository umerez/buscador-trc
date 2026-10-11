# Buscador de resoluciones de los tribunales de recursos contractuales

Página estática (GitHub Pages) que permite buscar, desde un único formulario, las resoluciones de los
tribunales y órganos de recursos contractuales de España: número de resolución, número de recurso,
fecha, sentido y texto libre sobre el objeto del contrato, el órgano de contratación y el acto recurrido.
Cada resultado enlaza al PDF y a la ficha oficial del tribunal.

No es una fuente oficial. Es un índice que se reconstruye cada noche a partir de los repositorios
públicos de cada tribunal; la resolución hay que comprobarla siempre en la web del tribunal, a la que
la página enlaza en todos los casos.

## Cómo funciona

```
scrapers/<tribunal>.py   →  construir_indice.py  →  docs/data/<tribunal>.json  →  docs/index.html + app.js
   (uno por tribunal)        (GitHub Actions,          (metadatos: nº, fecha,         (búsqueda en el navegador,
                              cada noche)               recurso, sentido, objeto,       sin servidor)
                                                        órgano, URL del PDF)
```

- Los scrapers solo recogen metadatos, nunca el texto completo de las resoluciones. El índice entero pesa
  unos pocos megabytes y se carga al abrir la página; a partir de ahí todo ocurre en el navegador.
- El workflow `.github/workflows/actualizar.yml` ejecuta `construir_indice.py --actual` (año en curso) cada
  noche y publica los cambios en `docs/data/`. También se puede lanzar a mano en modo `completo`.
- `docs/data/meta.json` lleva los recuentos por tribunal y año; `docs/data/estado.json`, el resultado de la
  última pasada (la página lo muestra en el pie).

## Tribunales

| Tribunal | Id | Cobertura | Fuente |
| --- | --- | --- | --- |
| Tribunal Administrativo Central de Recursos Contractuales (TACRC) | `tacrc` | sin índice | Su buscador exige Cloudflare Turnstile. La página enlaza al buscador oficial y construye la URL del PDF a partir de recurso, resolución y fecha. |
| TACP Comunidad de Madrid | `madrid` | 2011- | Buscador Drupal |
| TARCCYL Castilla y León | `cyl` | 2012- | Listados anuales de cccyl.es |
| TARCJA Andalucía | `andalucia` | 2011- | Buscador Drupal |
| TACGal Galicia | `galicia` | 2018- | Buscador Spring (POST); PDF en castellano y original gallego |
| TACPN Navarra | `navarra` | 2013- | Listados Liferay por año |
| TCCSP Cataluña | `cataluna` | 2017- | Buscador OpenCms (solo catalán) |
| TACPA Aragón | `aragon` | 2011- | CGI BRS de gd.aragon.es |
| OARC / KEAO Euskadi | `oarc` | 2011- | Catálogo Open Data Euskadi (castellano y euskera) |
| TACP Canarias | `canarias` | 2015- | Visor JSP (Solr) |

Castilla-La Mancha, Comunitat Valenciana, Murcia, Illes Balears, Asturias, Extremadura, Cantabria,
La Rioja, Ceuta y Melilla tienen atribuida la competencia al TACRC por convenio, así que sus resoluciones
tampoco están en el índice.

El detalle de cada repositorio (URLs, parámetros, formatos de las cabeceras, trampas) está en
`scrapers/REPOSITORIOS.md`.

## Uso local

```bash
pip install -r requirements.txt
python3 construir_indice.py --tribunal oarc --completo      # un tribunal, todos los años
python3 construir_indice.py --actual                        # todos los tribunales, año en curso
python3 -m scrapers.madrid 2024                             # probar un scraper suelto
python3 -m http.server -d docs 8000                         # abrir http://localhost:8000
```

## Esquema de los datos

Cada registro de `docs/data/<tribunal>.json` tiene estas claves (las vacías se omiten):

| Clave | Contenido |
| --- | --- |
| `t` | id del tribunal |
| `n` | nº de resolución normalizado, `400/2025` |
| `f` | fecha ISO de la resolución |
| `r` | nº de recurso o expediente, tal como lo cita el tribunal |
| `s` | sentido o tipo de resolución, tal como lo publica el tribunal |
| `o` | órgano de contratación o poder adjudicador |
| `d` | objeto del contrato, resumen o título |
| `a` | acto recurrido |
| `c` | tipo de contrato |
| `k` | clase de documento cuando no es la serie principal: `acuerdo`, `cautelar`, `rectificacion` |
| `pdf` | URL del PDF (castellano si el tribunal lo ofrece) |
| `p2` | URL del PDF en el otro idioma oficial (gallego, euskera) |
| `url` | URL de la ficha HTML |

## Licencia

Código bajo licencia MIT. Los datos pertenecen a los tribunales que los publican y se reproducen aquí solo
como índice de acceso a las fuentes oficiales.
