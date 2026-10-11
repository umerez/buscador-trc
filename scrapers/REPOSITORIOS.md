# Repositorios de resoluciones de los tribunales de recursos contractuales

Comprobado el 11/10/2026 con peticiones reales (`curl`, User-Agent de Chrome) desde el Mac
de Umerez. Base para el futuro script `verificar_resoluciones_trc.py`, hermano de
`Skills/verificar-sentencias/scripts/verificar_sentencias.py`. Todo lo que no se indica
como «leído» se ha ejecutado y visto. Todos los PDF descargados tienen capa de texto.

UA usado: `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36`

## Cuadro resumen

| Tribunal | Vía | Búsqueda por nº | PDF | Cobertura | Obstáculo |
| --- | --- | --- | --- | --- | --- |
| TACRC | API JSON tras SharePoint | Bloqueada: Cloudflare Turnstile validado en servidor | URL predecible solo si se conocen recurso + resolución + fecha | 2011-2026 | Turnstile |
| TACP Madrid | GET Drupal | `field_numero_de_resolucion=400/2025` | href en la ficha `/tacp/resolucion/4002025` | 2011-2026 (5.964) | ninguno |
| TARCCYL (Castilla y León) | GET Proxia (cccyl.es) | `S_RES_NUMERO_RES_min=185/2024` + `formName=searchForm` | href en ficha o listado anual | 2012-2026 | ninguno |
| Castilla-La Mancha | No tiene tribunal propio: convenio con el TACRC | Ver TACRC; recurso lleva sufijo «CLM NN-AAAA» | Ver TACRC | 2012- | Turnstile |
| TARCJA (Andalucía) | GET Drupal | `field_res_num_fecha_res=271/2024` | href del listado (carpeta por mes de subida) | 2011-2026 | ninguno |
| TACGal (Galicia) | POST Spring | `numResolucion=0100&anoResolucion=2024` (4 cifras) | `/sixtacweb/resolucions/download/{id}` | 2018-2026 | reCAPTCHA v3 solo en cliente, no exigido |
| TACPN (Navarra) | GET Liferay, sin buscador | Recorrer `/es/acuerdos-AAAA` | `/documents/880958/{0|1690342}/Acuerdo+N-AAAA.pdf` desde 2018 | 2013-2026 | HTML pesado, sin filtros |
| TCCSP (Cataluña) | GET OpenCms | `numero=352&datainf=01/01/2023&datasup=31/12/2023` | href del listado | 2017-2026 | solo catalán |
| TACPA (Aragón) | GET CGI BRS | `NUME-C=15/2024` (+ `@FERE-GE/@FERE-LE`) | `BRSCGI?CMD=VEROBJ&MLKOB=…` (del listado) | 2011-2026 | latin-1 |
| OARC/KEAO (Euskadi) | URL directa + JSON anual + Open Data | PDF directo por `{N}_{AAAA}` | `https://www.euskadi.eus/contenidos/resolucion_oarc/{N}_{AAAA}/es_def/adjuntos/Resolucion{N}_{AAAA}.pdf` | 2011-2026 | 2011-2013 nombres con tilde |
| TACP Canarias | GET/POST JSP (Solr) | `chpae_resolucion_numero_resolucion_es=238/2024` | href en el resultado desde 2019; listado anual 2015-2018 | 2015-2026 | ninguno |

No existe ningún agregador público consultable por HTTP (OBCP: solo un Google Custom Search
de 2015; PLACSP: no aloja resoluciones; OIReScon: solo informes anuales en PDF). El único
agregador real es privado (Recursio, con registro). Hay que ir tribunal a tribunal.

## Cabeceras de los PDF (ficha)

| Tribunal | Líneas de cabecera (pdftotext -layout, 1ª página) |
| --- | --- |
| TACRC | `Recurso nº 353/2024` / `Resolución nº 992/2024` / `Pleno` o `Sección …` / `En Madrid, a 31 de julio de 2024.` |
| Madrid | `Recurso nº 375/2025` / `Resolución nº 400/2025` / `En Madrid, a 25 de septiembre de 2025.` |
| Castilla y León | `RECURSO 172/2024` / `RESOLUCIÓN 185/2024` / `Resolución 185/2024, de 30 de diciembre, del Tribunal …` |
| Andalucía | `Recurso 255/2024` / `Resolución 271/2024` / `Sección Tercera` / `Sevilla, 15 de julio de 2024.` |
| Galicia | `Recurso nº 86/2024` / `Resolución nº 100/2024` / `En Santiago de Compostela, a 2 de julio de 2024` (original gallego; traducción al castellano con aviso en la primera línea) |
| Navarra | `Expediente: 121/2025` / `ACUERDO 100/2025, de 5 de diciembre, del Tribunal …` |
| Cataluña | `Barcelona, 31 de maig de 2023` / `Resolució núm.: 352/2023 (recurs N-2022-0457)` (solo catalán; también «Acord núm. 18/2026») |
| Aragón | `RE 18/2024` / `Acuerdo 15/2024, de 16 de febrero, del Tribunal …` (también «Resolución N/2024» para cautelares) |
| OARC | `EB 2023/260` / `Resolución 100/2024, de 30 de mayo, de la Titular del Órgano …` |
| Canarias | `REMC 241-2026 …` / `Resolución 263/2026, de 2 de septiembre` |

## Detalle por tribunal

### TACRC (Ministerio de Hacienda)

- Buscador: `https://www.hacienda.gob.es/es-ES/Areas%20Tematicas/Contratacion/TACRC/Paginas/BuscadordeResoluciones.aspx`. SharePoint con React (`TACRCSearcher.js`). No hay páginas por año, ni sitemap útil, ni biblioteca listable (`/_api/...`, `Forms/AllItems.aspx` → redirigen a pagenotfound).
- API: `POST https://serviciostelematicos.hacienda.gob.es/MINHAC_SP_PUBLIC_SERVICES/api/MinhacSearchController/GetResultsForFilter` (JSON). Sin token devuelve `500 {"Message":"Invalid code captcha"}`. El token es de Cloudflare Turnstile (sitekey `0x4AAAAAABe_qsis_-WAhXWD`), campo `responseCaptcha`. Campos de búsqueda: `NumeroResolucion` (`["0992","2024"]`), `NumeroExpedienteRecurso`, `FechaResolucion`, `TipoContratoTACRC`, `TipoResolucion`, `ActoRecurrido`. Resultado (inferido del JS): `Path` (URL del PDF), `Size`, `PortalFechaResolucion`, `PortalDescripcion`. 10 por página (`startRow`).
- PDF (sin captcha, 200): `https://www.hacienda.gob.es/TACRC/Resoluciones/Año AAAA/Recurso NNNN-AAAA [CCAA NN-AAAA] (Res NNN) DD-MM-AAAA.pdf`. Insensible a mayúsculas. Ejemplos comprobados:
  - `https://www.hacienda.gob.es/tacrc/resoluciones/a%C3%B1o%202024/recurso%200353-2024%20(res%20992)%2031-07-2024.pdf`
  - `https://www.hacienda.gob.es/TACRC/Resoluciones/A%C3%B1o%202018/Recurso%200456-2018%20CLM%2031-2018%20%28Res%20556%29%2008-06-2018.pdf`
  - `https://www.hacienda.gob.es/TACRC/resoluciones/a%C3%B1o%202014/recurso%200411-2014%20clm%20030-2014%20(res%20454)%2013-06-14.pdf` (año de la fecha con dos cifras en 2014)
  - Sufijos vistos: `ML`, `AST`, `VAL`, `MU`, `IB`, `CLM`, `. corregida`. Pleno 2022 en otra carpeta: `/tacrc/documentos/resoluciones de pleno 2022/resolución recurso 1028-2022 (res 1156) 06-10-2022.pdf`.
- Listas estáticas con enlaces: `Resoluciones-Pleno.aspx`, `Acuerdos-Pleno-TACRC.aspx`, boletines `actualidad-del-tribunal.aspx` (29 PDF).
- Convenios (CCAA sin tribunal propio): `Conveniossobreatribuci%C3%B3ndecompetenciasalTribunal.aspx`. Castilla-La Mancha desde 2012; convenio vigente de 25/09/2024 (BOE 03/10/2024).

### TACP Comunidad de Madrid

- Buscador GET: `https://www.comunidad.madrid/tacp/busquedaresoluciones`. Parámetros: `field_numero_de_resolucion` (exacto, `400/2025`), `field_numero_de_expediente` (nº de recurso), `field_fecha[date]` / `field_fecha_1[date]` (dd/mm/aaaa), `search_api_views_fulltext`, `im_field_tipo_de_resolucion` (35 Desestimatoria, 41 Estimatoria, 10 Parcial, 53 Inadmisión, 45 Otros), `page` (0-based, 5 por página).
- Ficha: `https://www.comunidad.madrid/tacp/resolucion/NNNAAAA` (nº a 3 cifras + año, p. ej. `4002025`, `0012025`, `0892011`).
- Parseo: contador «N registros de M» y filas dentro de `class="view-content"`. Ojo: el megamenú trae tres enlaces fijos a resoluciones destacadas fuera del `view-content`.
- PDF: href en ficha o listado. Nombres variables: `files/resolucion_400-2025_expediente_375-2025.pdf`, `files/resolucion-238-2020.pdf`, `files/Resoluci%C3%B3n-089-2011.pdf`.
- `curl -sS -G -A "$UA" --data-urlencode "field_numero_de_resolucion=400/2025" https://www.comunidad.madrid/tacp/busquedaresoluciones`

### TARCCYL (Castilla y León, en cccyl.es)

- Buscador GET: `https://www.cccyl.es/es/tribunal-administrativo-recursos-contractuales-castilla-leo/resoluciones.buscar`. Obligatorio `formName=searchForm`. Parámetros: `S_RES_NUMERO_RES_min` (`185/2024`), `S_RES_NUM_RECURSO_min` (`172/2024`), `S_RES_FECHA_min` / `S_RES_FECHA_max` (`d/M/yy`, p. ej. `1/1/24`), `pattern` (texto), `S_RES_TIPO_RESOL_min`, etc. Paginación `resoluciones.buscar,OFFSET,10?...`.
- Listados anuales: `.../resoluciones/resoluciones-ano-AAAA` (2012-2026), paginación `.nodos,OFFSET,10`. Ficha: `.../resoluciones-ano-2024/resolucion-185-2024` (campos: nº resolución, nº recurso, fecha, órgano, acto, tipo).
- PDF: `<ficha>.ficheros/<ID>-Resolución 185-2024 .pdf` (ID no deducible; leer href). Ejemplo: `.../resolucion-185-2024.ficheros/93806-Resoluci%C3%B3n%20185-2024%20.pdf`.
- Las fichas citan «RRTARCYL nº 127/2024».
- `curl -sS -G -A "$UA" --data-urlencode "formName=searchForm" --data-urlencode "S_RES_NUMERO_RES_min=185/2024" https://www.cccyl.es/es/tribunal-administrativo-recursos-contractuales-castilla-leo/resoluciones.buscar`

### TARCJA (Andalucía)

- Buscador GET (Drupal): `https://www.juntadeandalucia.es/organismos/tarc/servicios/resoluciones.html`. Parámetros: `field_res_num_fecha_res=271/2024` (exacto; `271` solo devuelve todas las 271/AAAA), `field_expediente_oc=255/2024` (nº de recurso), `date-year=2&field_res_num_fecha_fecha_value=2024-07-15&field_res_num_fecha_fecha_value_1=2024-07-15` (entre fechas), `text=` (texto; entrecomillado para frase), `items_per_page=50`, `page` (0-based). El filtro por año (`date-year=1&field_res_num_fecha_fecha=N`) usa un índice que se desplaza cada año: leer el `<select>`.
- Parseo: `(?s)<div class="views-field views-field-title"><span class="field-content"><a href="\s*([^"]*?)\s*">([^<]*)</a>` (el href lleva espacios y saltos dentro de las comillas).
- PDF: href del listado; carpeta por mes de subida y nombre variable (`2024-07/Resolucion_271_24_Recurso_255_24.pdf`, 2026 con tilde y año de 4 cifras, 2011 `resolucion_01_11.pdf`). Existen «Resoluciones de rectificación» con serie propia.
- `curl -sS -L -A "$UA" -G "https://www.juntadeandalucia.es/organismos/tarc/servicios/resoluciones.html" --data-urlencode "field_res_num_fecha_res=271/2024"`

### TACGal (Galicia)

- Buscador: `https://tacgal.xunta.gal/sixtacweb/resolucions/` (POST; GET no filtra). Campos: `locale` (gl|es), `numResolucion` (**4 cifras**: `0100`), `anoResolucion`, `numRecurso` (4 cifras), `anoRecurso`, `fechaResolucionDesde/Hasta` (dd-mm-aaaa), `contenido`, `descripcionGl`, `decision`, `tipoContrato`, `actoRecorrido`. Paginación `?page=N` (0-based, 20 por página) repitiendo el POST.
- Parseo: tabla Nº Resolución | Nº Recurso | Fecha | Decisión | Tipo | Acto | Descripción | Archivo; `<a id="8576" class="descargaDocumento">`: el `id` es el idDocumento. Con `locale=gl` el id es el original gallego (8567 para 100/2024); con `locale=es`, la traducción automática (8576).
- PDF: `https://tacgal.xunta.gal/sixtacweb/resolucions/download/{id}` (GET directo, sin token; el cliente ejecuta reCAPTCHA v3 pero el servidor no lo exige hoy).
- Repositorio antiguo 2018-2019: `https://ficheiros-web.xunta.gal/tacgal/resolucions/resolucion_69-2019_do_recurso_70-2019_para_web.pdf` (`_es.pdf` traducción). No sirve para años recientes.
- `curl -sS -L -A "$UA" "https://tacgal.xunta.gal/sixtacweb/resolucions/" --data-urlencode "locale=es" --data-urlencode "numResolucion=0100" --data-urlencode "anoResolucion=2024"`

### TACPN (Navarra)

- Sin buscador. Listados Liferay: `https://portalcontratacion.navarra.es/es/acuerdos-AAAA` (2013-2026) y `/es/todos-acuerdos` (57 páginas de 20). Paginación con parámetros del asset publisher (`..._cur=2`, 1-based; `delta` se ignora; el id de instancia del portlet cambia por página: tomar los enlaces de paginación del HTML).
- Cada ítem: título «Acuerdo N/AAAA, de D de mes.», resumen, fecha de publicación, materias y `<div class="boton-ver"><a href="/documents/880958/0/Acuerdo+100-2025.pdf/...">`.
- PDF semipredecible desde 2018: `https://portalcontratacion.navarra.es/documents/880958/{0|1690342}/Acuerdo+{N}-{AAAA}.pdf` (probar `0` y luego `1690342`; algunos con sufijo `+(1)`). 2013-2017 nombres irregulares: solo por listado. Descargas grandes pueden cortarse (`curl: (18)`): reintentar.
- Cita: «Acuerdo 100/2025, de 5 de diciembre, del TACPN» y «Expediente 121/2025» (serie propia).

### TCCSP (Cataluña)

- Buscador GET (solo catalán): `https://contractacio.gencat.cat/ca/contacte/tccsp/cercador-resolucions/index.html`. Parámetros: `numero` (sin año: `352` devuelve todas las 352/AAAA), `datainf` / `datasup` (dd/mm/aaaa) para acotar el año, `text`, `admin`, `sentit`, paginación `page74bdffe4-cd83-11ea-a60c-005056924a59=N` (1-based, 10 por página).
- Parseo: `<p class="txt_result"> S'han trobat <span>1</span> resultats</p>`; cada `<article class='llistat_cerca_avancada'>` con `<a title="Resolució núm. 352/2023, de 31 de maig" href="/ca/contacte/tccsp/cercador-resolucions/resolucio/...">`, segundo `<a href="/.content/contacte/tccsp/resolucions/2023/resolucio-num-352-2023.pdf">`, `<span>31/05/2023</span>`. Sin resultados: «No s'han trobat resultats.».
- Ficha HTML con nº de recurso, administración, sentido, palabras clave y texto completo: `/ca/contacte/tccsp/cercador-resolucions/resolucio/Resolucio-num.-352-2023-de-31-de-maig`.
- PDF: href del listado; nombres cambiantes por año (`resolucio_num_352_2019.pdf`, `resolucio-num-352-2023.pdf`, `resolucio_num._352_2024.pdf`, acuerdos en `/resolucions/acords/AAAA/acord_num._18_2026.pdf`).
- Cobertura 2017-2026 (4.132). 2012-2016 solo en el índice Socrata `https://analisi.transparenciacatalunya.cat/resource/dkrd-id95.json` (sin PDF accesible).
- `curl -sS -L -A "$UA" -G "https://contractacio.gencat.cat/ca/contacte/tccsp/cercador-resolucions/index.html" --data-urlencode "numero=352" --data-urlencode "datainf=01/01/2023" --data-urlencode "datasup=31/12/2023"`

### TACPA (Aragón)

- Formulario: `https://aplicacionesportalaragon.aragon.es/formularios/acuerdos-tribunal-admninistrativo-contratos-publicos-aragon.html` (sic). CGI BRS: `https://gd.aragon.es/cgi-bin/ACTA/BRSCGI?CMD=VERLST&BASE=ACTA&DOCS=1-100&SEC=ACTA_PUBL&SORT=@FEPU&SEPARADOR=&NUME-C=15%2F2024`. HTML en ISO-8859-1. `NUME-C` hace coincidencia parcial (15/2024 devuelve también 15/2025 y la «Resolución 15/2024» de cautelares): filtrar por el campo «Número» del HTML. `@FERE-GE=AAAA0101` / `@FERE-LE=AAAA1231` (fecha completa), `TEMA-C` (texto), `TIPO-C`, `SENA-C`. Paginación `DOCS=101-200`.
- Cada resultado: Título, Resumen temático, Número, Tipo de contrato, Sentido, Fecha de adopción y enlace `Abrirobjeto('MLKOB=1319491823333')`.
- PDF: `https://gd.aragon.es/cgi-bin/ACTA/BRSCGI?CMD=VEROBJ&MLKOB=<id>` (regex `MLKOB=\d+`).
- Cita: «Acuerdo 15/2024, de 16 de febrero, del TACPA»; recurso «RE 18/2024».

### OARC / KEAO (Euskadi)

- PDF directo: `https://www.euskadi.eus/contenidos/resolucion_oarc/{N}_{AAAA}/es_def/adjuntos/Resolucion{N}_{AAAA}.pdf` (sin ceros; euskera `eu_def/adjuntos/Erabakia{N}_{AAAA}.pdf`; también en `www.contratacion.euskadi.eus`). 2011-2013: nombres con tilde y espacio (`Resoluci%C3%B3n%2011_2012.pdf`); lo robusto es leer la ficha `.../{N}_{AAAA}/es_def/index.shtml` y seguir el href de `adjuntos/`.
- JSON anual: `https://www.contratacion.euskadi.eus/webkpe00-kpeoarc/es/y96aResolucionesWar/busqueda/buscarListado?anio=2024&idSubcriterio=` (campos `numResolucion` «001/2024», `fechaResolucion`, `poderAdjudicadorDesc`, `objContrato`, `resumenResolucion`, `sentidoResolucionDesc`, `urlFichaResolucion`). Búsqueda por expediente: `.../busqueda/tabla?numExp=2023%2F260`. No hay campo de nº de resolución.
- Open Data Euskadi (catálogo completo 2011-2026, 2.643 registros, 3,4 MB, un GET): `https://opendata.euskadi.eus/contenidos/ds_juridicos/resoluciones_oarc/opendata/documentacion.json`. Es lo que usa `~/Scripts/DescargaOarc/descarga_oarc.py` (corpus local con PDF y texto desde 2022).
- XML r01: `https://www.euskadi.eus/r01hSearchResultWar/r01hPresentationXML.jsp?r01kQry=tC%3Aeuskadi%3BtF%3Adocumentacion_juridica%3BtT%3Aresolucion_oarc%3Bm%3AdocumentLanguage.EQ.es%2CcontentName.EQ.100_2024%3B`.
- Cita: «Resolución 100/2024, de 30 de mayo, del OARC/KEAO»; expediente «EB 2023/260».

### TACP Canarias

- Visor: `https://www.gobiernodecanarias.org/hacienda/contratacion/tacp/visor_resoluciones/index.jsp?param_page=1&param_accion=buscar&chpae_resolucion_numero_resolucion_es=238%2F2024` (GET o POST; `238` solo devuelve todas las 238/AAAA). Fechas: `chpae_resolucion_fecharesolucion_es_dt_d=01%2F01%2F2024&chpae_resolucion_fecharesolucion_es_dt=31%2F12%2F2024`. Otros: `_numero_expediente_es`, `_resumen_es`, `_texto_libre_es`, etc. Sin paginación real (Solr `rows=100000000`).
- Resultado: número, fecha, expediente, resumen, acto, tipo, procedimiento, órgano, tipo de resolución, objeto, CPV, precepto y, desde 2019, href al PDF.
- PDF: `https://www.gobiernodecanarias.org/cmsgob1/export/sites/hacienda/contratacion/tacp/TACP_{AAAA}/RES-{NNN}-{AAAA}-REMC-{EEE}-{AAAA}.pdf` (depende del expediente; nombres irregulares antes de 2019). 2015-2018: listados anuales `.../tacp/resoluciones/resoluciones_{AAAA}/` (2024-2026 dan 404).
- Cita: «Resolución 263/2026, de 2 de septiembre» del TACP de Canarias; expediente «REMC 241-2026».

## Tribunales no cubiertos (fuera de la lista pedida)

Comunidad Valenciana (TACPCV, desde 2023), Extremadura, Murcia, Baleares, Asturias, Cantabria y La Rioja: no investigados. Varias de estas comunidades están conveniadas con el TACRC (sufijos `VAL`, `MU`, `IB`, `AST` en los nombres de archivo del TACRC).

## Hallazgos de la implementación de los scrapers (11/10/2026)

Comprobados al escribir `scrapers/*.py` con peticiones reales. Corrigen o amplían lo anterior.

- **TACP Madrid.** El listado es de 5 por página, fijo (`items_per_page` se ignora). Solo trae nº, fecha, descripción y PDF por `/tacp/file/NNNN/download?token=…`; recurso, sentido, contrato, acto y procedencia solo están en la ficha (`div.field-name-field-*`), que da además la URL directa del PDF. No publica el órgano concreto: solo la categoría «Procedencia» (Consejerías, Hospitales, Municipios…). Algunas fichas enlazadas dan 404 (2024: 293, 364 y 416). Hay más filtros: `field_tipo_contrato`, `field_acto_recurrido`, `field_objeto`, `field_procedencia`, `field_temas_resoluciones`. Backfill 2011-2026: unas 7.200 peticiones, dos horas.
- **TARCCYL.** Página fija de 10 (`.nodos,10,100` sigue dando 10; `.nodos,0,50` redirige). Un OFFSET pasado el final recicla resultados: cortar por el mayor offset del paginador. 2012-2019 salen enteros en una sola página sin paginador. El listado trae ya el href del PDF y los «Fundamentos»; la ficha aporta fecha, recurso, tipo, órgano, acto y contrato. Los href antiguos vienen sin codificar (tildes y espacios): `requests.utils.requote_uri`. El servidor no envía el certificado intermedio (Sectigo DV R36): `requests` falla la verificación; `cyl.py` descarga el intermedio de la URL AIA y lo añade al bundle de certifi (nunca desactiva la verificación). 2019 tiene 193 ítems y el número mayor es 194.
- **TARCJA.** `.view-header` da el total («N recursos disponibles»). Cada `<li>` trae observaciones, fecha (`<time datetime>`), recurso, tipo de contrato, acto y tipo de resolución; no hay órgano ni ficha HTML (el título enlaza al PDF). Datos sucios: filas duplicadas por resubida del PDF (`_0.pdf`, `_6.pdf`), títulos con nº erróneo (463/2024 es la 563/2024, 614/2025 la 714/2025), «Resolución 5/2005» por 5/2025, dos títulos al mismo PDF (484 y 492/2025), fechas imposibles (46/2020 fechada en 2010). Rectificaciones con serie propia solo desde 2026. Totales: 6.926 filas brutas; 2024: 670; 2025: 796. Backfill: 155 peticiones, 3-4 minutos.
- **TACGal.** Acepta `size=1000`: un año entero en una petición por idioma. Con `locale=es`, si la traducción está pendiente (`<div id="pteTraducir">`) el id coincide con el gallego. Algunos valores de catálogo salen en gallego aunque se pida castellano («Contrato de subministración», «Pregos»). Una fila por recurso: las resoluciones con recursos acumulados aparecen repetidas (se funden). 2024: faltan en origen los números 10, 28, 114, 167, 173 y 184. Backfill: 18 peticiones.
- **TACPN.** El id de instancia del portlet cambia por año, no por página (seguir el enlace «Siguiente»). Título y resumen van juntos en `h2.titulo-acuerdos`; la primera frase tras la fecha suele ser el sentido. La «Fecha de publicación» va meses por detrás de la del acuerdo. Servidor irregular (1 a 40 s por página de 400 KB). 2013-2017 PDF en `/documents/880958/1690342/` con nombres irregulares; el Acuerdo 40/2014 enlaza a `navarra.es/NR/rdonlyres/…`, que da 502. Unos 1.130 acuerdos en total.
- **TCCSP.** Acepta `rows=1000`: el año entero en una página (~900 KB). La paginación `page74bdffe4…=N` ignora `rows` y se solapa: no combinar. El listado trae `div.descripcio` con el resumen (empieza por el sentido). Nº de recurso, administración y sentido normalizado solo en la ficha; en 2017 la ficha no da el nº de recurso. El `select` «Sentit» del formulario solo tiene una opción. 204/2024 y 152/2024 enlazan al PDF de otra resolución. Backfill con fichas: 4.140 peticiones, 45-50 minutos.
- **TACPA.** El servidor declara ISO-8859-1 pero usa Windows-1252 (guiones 0x97): decodificar como `cp1252`. El campo Número lleva el recurso entre paréntesis solo desde mediados de 2024 («75/2024 (Recurso 68/2024)»). Erratas en Número («4/2014» para el Acuerdo 4/2012): manda el título. La serie «Resolución N/AAAA» no es solo de cautelares: también desistimientos y archivos. Las etiquetas vienen partidas por saltos de línea. **Tras unas 15 peticiones seguidas el BRS devuelve «Error durante la búsqueda (204/110)» para todo y tarda más de 25 minutos en recuperarse**: pausa de 8 s entre años en el orquestador.
- **OARC/KEAO.** El catálogo Open Data no trae nº de resolución (sale del slug `{N}_{AAAA}`), ni sentido, ni expediente (`numExp` siempre null), ni URL del PDF; `legalDocTitle` está truncado a 250 (usar `documentName`). Se complementa con el JSON anual del buscador (`buscarListado?anio=AAAA`, 300 KB), que da sentido y resumen y añade resoluciones que el catálogo aún no tiene (va semanas por detrás). PDF predecible desde 2015; 2011-2014 irregular (leer el dataXML de cada registro). Euskera (`Erabakia{N}_{AAAA}.pdf`) solo desde la 10/2019. Duplicados y fechas con año imposible en el catálogo (4/2013 «21/01/2103», 82/2013 «05/03/0012»). Total 2.651.
- **TACP Canarias.** La JSP pinta 200 por página; las siguientes con `page_buscador=N` (`param_page` no hace nada). Campos completos (PDF, expediente, órgano, acto…) solo en 2022-2026 (2020 parcial). El visor está incompleto (2021: 2 de 284; 2022: 235 de 253): hay que cruzar con el listado anual estático `tacp/resoluciones/resoluciones_AAAA/` (2015-2023), que da PDF, fecha, resumen, materia y tipo; el expediente se deduce del nombre del PDF (`RES-171-2016-REMC-41-2016-L.pdf`). La 8/2024 está duplicada en Solr. Unos 2.500 registros.
- **TACRC (vías alternativas al buscador, probadas el 11/10/2026).** El script del buscador (`/Style Library/MINHAC.SP.Portal/APPS/BuscadorTACRC/TACRCSearcher.js`) solo usa dos métodos de `serviciostelematicos.hacienda.gob.es/MINHAC_SP_PUBLIC_SERVICES/api/MinhacSearchController/`: `FilterFieldsPostResponse` (campos del filtro) y `GetResultsForFilter` (resultados); el token de Turnstile va en `responseCaptcha` cuando `captchaSettings.visible` es verdadero, y lo valida el servidor. No sirven como fuente: el buscador interno de SharePoint del ministerio (no indexa los PDF), los boletines «Actualidad del TACRC» (29 PDF, solo seis resoluciones comentadas cada uno), las memorias anuales (estadísticas) ni datos.gob.es (sin conjunto de datos). Sí sirve, parcialmente, el archivo público de la web: el índice CDX de la Wayback Machine (`http://web.archive.org/cdx/search/cdx?url=hacienda.gob.es/tacrc/*&output=txt&fl=original&collapse=urlkey&filter=mimetype:application/pdf`, también en `minhafp.gob.es` y `minhap.gob.es`) devuelve unas 2.800 URL de PDF, de las que salen 2.400 resoluciones distintas 2011-2026 (número, recurso, fecha y enlace, que sigue vivo en hacienda.gob.es); Common Crawl (`index.commoncrawl.org/CC-MAIN-AAAA-NN-index?url=hacienda.gob.es/TACRC/Resoluciones/*`) añade solo 7 en 70 índices y da 504 a menudo. Son unas 2.400 de las ~20.000 resoluciones (el TACRC llega a 1.700-1.900 al año). Implementado en `buscador-trc/scrapers/tacrc.py`. Umerez optó el 11/10/2026 por pedir el conjunto de datos al Ministerio (solicitud Ley 19/2013 + Ley 37/2007).
