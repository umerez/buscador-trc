"""Buscador de resoluciones de los tribunales de recursos contractuales, versión Streamlit.

Lee el mismo índice que la página estática (docs/data/*.json) y ofrece los mismos filtros:
texto libre, número de resolución, número de recurso, año, fechas, sentido y tribunales.

Ejecutar en local:
    .venv/bin/streamlit run app_streamlit.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

DATOS = Path(__file__).parent / "docs" / "data"

st.set_page_config(page_title="Resoluciones contractuales", page_icon="⚖️", layout="wide")


# ---------------------------------------------------------------- utilidades

def _norm(s) -> str:
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _clasificar(s) -> str:
    t = _norm(s)
    if not t:
        return ""
    if "parcial" in t:
        return "Estimación parcial"
    if "desestim" in t:
        return "Desestimatoria"
    if re.search(r"inadmi|inadmet|inadmis", t):
        return "Inadmisión"
    if re.search(r"desist|perd(a|ida)|perdua|archiv|arquiv|conclus|sin objeto|sense objecte|terminaci|finalitz|renunci", t):
        return "Desistimiento / pérdida de objeto"
    if "estim" in t:
        return "Estimatoria"
    return "Otros"


def _terminos(q: str) -> list[str]:
    return [_norm(a or b) for a, b in re.findall(r'"([^"]+)"|(\S+)', q or "") if (a or b)]


def _numero(texto: str):
    t = re.sub(r"\s+", "", texto or "")
    if not t:
        return None
    m = re.fullmatch(r"(\d{1,4})[/\-_](\d{2,4})", t)
    if m:
        a = int(m.group(2))
        return {"num": int(m.group(1)), "anio": a + 2000 if a < 100 else a}
    if re.fullmatch(r"\d{1,4}", t):
        return {"num": int(t), "anio": None}
    return {"texto": _norm(t)}


# ---------------------------------------------------------------- datos

@st.cache_data(show_spinner="Cargando el índice…")
def cargar():
    meta = json.loads((DATOS / "meta.json").read_text(encoding="utf-8"))
    tribunales = {t["id"]: t for t in meta["tribunales"]}
    filas = []
    for t in meta["tribunales"]:
        if not t.get("fichero"):
            continue
        for r in json.loads((DATOS / Path(t["fichero"]).name).read_text(encoding="utf-8")):
            filas.append(r)
    df = pd.DataFrame(filas)
    for col in ("f", "r", "s", "o", "d", "a", "c", "k", "pdf", "p2", "url"):
        if col not in df.columns:
            df[col] = None
        # las claves ausentes en el JSON llegan como NaN (float): se dejan como None para poder hacer `if x`
        df[col] = df[col].astype(object).where(df[col].notna(), None)
    df["anio"] = df["n"].str.split("/").str[1].astype(int)
    df["num"] = df["n"].str.split("/").str[0].astype(int)
    df["fecha"] = pd.to_datetime(df["f"], errors="coerce")
    df["sentido"] = df["s"].map(_clasificar)
    df["siglas"] = df["t"].map(lambda x: tribunales[x]["siglas"])
    df["haystack"] = (
        df[["n", "r", "d", "o", "a", "s", "c", "siglas"]].fillna("").astype(str).agg(" \u0001 ".join, axis=1).map(_norm)
    )
    df["rdig"] = df["r"].fillna("").astype(str).str.replace(r"\D+", "", regex=True)
    return meta, tribunales, df


meta, TRIBUNALES, df = cargar()
con_indice = [t for t in meta["tribunales"] if t.get("fichero")]
sin_indice = [t for t in meta["tribunales"] if not t.get("fichero")]

# ---------------------------------------------------------------- cabecera y barra lateral

st.title("Buscador de resoluciones de los tribunales de recursos contractuales")
actualizado = meta["actualizado"][:10]
st.caption(
    f"{len(df):,} resoluciones de {len(con_indice)} tribunales. Índice actualizado el "
    f"{actualizado[8:10]}/{actualizado[5:7]}/{actualizado[:4]}. "
    "No es una fuente oficial: compruebe siempre la resolución en la web del tribunal.".replace(",", ".")
)

with st.sidebar:
    st.header("Sobre esta aplicación")
    st.markdown(
        "Busca en un único formulario las resoluciones de los tribunales y órganos de recursos "
        "contractuales de España. El índice se reconstruye cada noche a partir de los repositorios "
        "públicos de cada tribunal y contiene solo metadatos: número, fecha, recurso, sentido, órgano, "
        "objeto y enlace al PDF oficial."
    )
    for t in sin_indice:
        st.warning(f"**{t['siglas']}**: {t.get('sin_indice', 'sin índice')} [Buscador oficial]({t['buscador']})")
    for t in con_indice:
        if t.get("parcial"):
            st.warning(f"**{t['siglas']}** (índice parcial): {t['parcial']} [Buscador oficial]({t['buscador']})")
    st.markdown("---")
    st.markdown("**Tribunales**")
    seleccion = []
    for t in con_indice:
        etiqueta = f"{t['siglas']} · {t['total']:,}".replace(",", ".") + (" (parcial)" if t.get("parcial") else "")
        if st.checkbox(etiqueta, value=True, key=f"t_{t['id']}", help=t["nombre"]):
            seleccion.append(t["id"])
    st.markdown("---")
    st.caption(
        "Herramienta de uso libre y sin garantía, con finalidad orientativa. Los datos pertenecen a los tribunales "
        "que los publican. [Código y datos en GitHub](https://github.com/umerez/buscador-trc)."
    )

# ---------------------------------------------------------------- filtros

q = st.text_input("Texto libre", placeholder="objeto del contrato, órgano, acto recurrido, palabras del resumen… (entre comillas para frase exacta)")
c1, c2, c3 = st.columns(3)
num = c1.text_input("Nº de resolución", placeholder="400/2025 o 400")
rec = c2.text_input("Nº de recurso", placeholder="375/2025")
anios = ["Todos"] + [str(a) for a in sorted(df["anio"].unique().tolist(), reverse=True)]
anio = c3.selectbox("Año", anios)
c4, c5, c6 = st.columns(3)
desde = c4.date_input("Desde", value=None, min_value=date(2010, 1, 1), format="DD/MM/YYYY")
hasta = c5.date_input("Hasta", value=None, min_value=date(2010, 1, 1), format="DD/MM/YYYY")
sentidos = ["Todos", "Estimatoria", "Estimación parcial", "Desestimatoria", "Inadmisión", "Desistimiento / pérdida de objeto", "Otros"]
sentido = c6.selectbox("Sentido", sentidos)

# ---------------------------------------------------------------- búsqueda

mask = df["t"].isin(seleccion)
if anio != "Todos":
    mask &= df["anio"] == int(anio)
if desde:
    mask &= df["fecha"] >= pd.Timestamp(desde)
if hasta:
    mask &= df["fecha"] <= pd.Timestamp(hasta)
if sentido != "Todos":
    mask &= df["sentido"] == sentido
nf = _numero(num)
if nf:
    if "texto" in nf:
        mask &= df["n"].map(_norm).str.contains(nf["texto"], regex=False)
    else:
        mask &= df["num"] == nf["num"]
        if nf["anio"]:
            mask &= df["anio"] == nf["anio"]
if rec.strip():
    raw = _norm(rec)
    dig = re.sub(r"\D+", "", rec)
    m_raw = df["r"].fillna("").map(_norm).str.contains(raw, regex=False)
    m_dig = (df["rdig"] == dig) if len(dig) >= 3 else pd.Series(False, index=df.index)
    if len(dig) >= 5:
        m_dig |= df["rdig"].str.contains(dig, regex=False)
    mask &= m_raw | m_dig
for termino in _terminos(q):
    mask &= df["haystack"].str.contains(termino, regex=False)

res = df[mask].sort_values(["fecha", "anio", "num"], ascending=False, na_position="last")
hay_filtro = bool(q or num or rec or anio != "Todos" or desde or hasta or sentido != "Todos")

st.markdown(f"**{len(res):,} resoluciones**".replace(",", ".") + ("" if hay_filtro else " (las más recientes primero)"))

# ---------------------------------------------------------------- tabla

CLASE = {"acuerdo": "Acuerdo", "cautelar": "Resolución (cautelar / desistimiento)", "rectificacion": "Resolución (rectificación)"}


def _documento(fila) -> str:
    doc = TRIBUNALES[fila["t"]].get("documento", "Resolución")
    if fila["k"] in CLASE:
        doc = CLASE[fila["k"]]
    return f"{doc} {fila['n']}"



MAX = 200
vista = res.head(MAX)
if len(res) > MAX:
    st.info(f"Se muestran las {MAX} más recientes. Afine la búsqueda para ver el resto.")

tabla = pd.DataFrame({
    "Tribunal": vista["siglas"],
    "Resolución": vista.apply(_documento, axis=1),
    "Fecha": vista["fecha"].dt.strftime("%d/%m/%Y"),
    "Recurso": vista["r"],
    "Sentido": vista["sentido"],
    "Órgano y objeto": vista.apply(lambda f: " · ".join(x for x in (f["o"], f["d"]) if x), axis=1),
    "PDF": vista["pdf"],
    "Otro idioma": vista["p2"],
    "Ficha": vista["url"],
})
st.dataframe(
    tabla,
    hide_index=True,
    width="stretch",
    column_config={
        "PDF": st.column_config.LinkColumn("PDF", display_text="PDF"),
        "Otro idioma": st.column_config.LinkColumn("Otro idioma", display_text="PDF"),
        "Ficha": st.column_config.LinkColumn("Ficha", display_text="Ficha"),
        "Órgano y objeto": st.column_config.TextColumn("Órgano y objeto", width="large"),
    },
    height=min(38 * (len(tabla) + 1), 900),
)

st.download_button(
    "Descargar estos resultados (CSV)",
    data=res.drop(columns=["haystack", "rdig", "fecha", "num"]).to_csv(index=False).encode("utf-8"),
    file_name="resoluciones.csv",
    mime="text/csv",
    disabled=res.empty,
)

# ---------------------------------------------------------------- buscadores oficiales

with st.expander("Buscar en las webs oficiales"):
    st.markdown(
        "Los enlaces abren el buscador oficial de cada tribunal. Las resoluciones del TACRC y de las comunidades "
        "que tiene conveniadas no están en este índice porque su buscador exige una comprobación anti-robots."
    )
    cols = st.columns(2)
    for i, t in enumerate(meta["tribunales"]):
        cols[i % 2].markdown(f"- [{t['siglas']}]({t['buscador']}): {t['nombre']}")

with st.expander("TACRC: construir el enlace al PDF de una resolución"):
    st.markdown(
        "La dirección de los PDF del TACRC es predecible si se conocen el número de recurso, el de resolución y la "
        "fecha (los tres figuran en la cabecera de la resolución)."
    )
    t1, t2, t3, t4, t5 = st.columns(5)
    rec_t = t1.text_input("Nº de recurso", placeholder="353/2024", key="tacrc_rec")
    suf = t2.selectbox("Sufijo CCAA", ["", "CLM", "VAL", "MU", "IB", "AST", "ML", "EXT", "CANT", "RIO", "CEU"], key="tacrc_suf")
    rec_ccaa = t3.text_input("Nº recurso autonómico", placeholder="31/2018", key="tacrc_recccaa", disabled=not suf)
    res_t = t4.text_input("Nº de resolución", placeholder="992/2024", key="tacrc_res")
    fecha_t = t5.date_input("Fecha", value=None, min_value=date(2011, 1, 1), format="DD/MM/YYYY", key="tacrc_fecha")
    nr, ns, nc = _numero(rec_t), _numero(res_t), _numero(rec_ccaa)
    if nr and nr.get("num") and ns and ns.get("num") and fecha_t and (not suf or (nc and nc.get("num"))):
        from urllib.parse import quote
        anio_rec = nr["anio"] or fecha_t.year
        anio_res = ns["anio"] or anio_rec
        sufijo = f" {suf} {nc['num']}-{nc['anio'] or anio_rec}" if suf else ""
        nombre = f"Recurso {nr['num']:04d}-{anio_rec}{sufijo} (Res {ns['num']}) {fecha_t:%d-%m-%Y}.pdf"
        url = f"https://www.hacienda.gob.es/TACRC/Resoluciones/{quote('Año ' + str(anio_res))}/{quote(nombre)}"
        st.markdown(f"[Abrir el PDF]({url})  \n`{url}`")
        st.caption("Si el enlace falla, el tribunal pudo usar otra variante del nombre (sufijo de comunidad, «corregida», año de dos cifras en 2014): búsquelo en el buscador oficial.")
