"""TACRC (Tribunal Administrativo Central de Recursos Contractuales, Ministerio de Hacienda).

Sin scraper: el buscador oficial exige un token de Cloudflare Turnstile validado en servidor,
y no hay listados ni sitemap con las resoluciones. El buscador web solo ofrece el enlace al
buscador oficial y el constructor de la URL del PDF (predecible si se conocen nº de recurso,
nº de resolución y fecha). Véase REPOSITORIOS.md en Skills/_en-desarrollo/verificar-resoluciones-trc.
"""
from __future__ import annotations

TRIBUNAL = {
    "id": "tacrc",
    "siglas": "TACRC",
    "nombre": "Tribunal Administrativo Central de Recursos Contractuales",
    "ambito": "Estado y comunidades conveniadas (Castilla-La Mancha, Comunitat Valenciana, Murcia, Illes Balears, Asturias, Extremadura, Cantabria, La Rioja, Ceuta y Melilla)",
    "buscador": "https://www.hacienda.gob.es/es-ES/Areas%20Tematicas/Contratacion/TACRC/Paginas/BuscadordeResoluciones.aspx",
    "idioma": "es",
    "desde": 2011,
    "documento": "Resolución",
    "sin_indice": "El buscador oficial del TACRC exige una comprobación anti-robots (Cloudflare Turnstile) que impide indexar sus resoluciones. Busque directamente en la web del tribunal o construya el enlace al PDF si conoce el número de recurso, el de resolución y la fecha.",
}


def listar(anio, sesion=None):
    return []
