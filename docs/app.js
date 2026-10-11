/* Buscador de resoluciones de los tribunales de recursos contractuales.
   Carga el índice (docs/data/*.json) y busca en el navegador. Sin dependencias. */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const PAGINA = 100;
  const estado = { meta: null, registros: [], filtrados: [], mostrados: 0, orden: { campo: "f", asc: false }, estadoCarga: null };

  // ------------------------------------------------------------ utilidades
  const quitarAcentos = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const norm = (s) => quitarAcentos(String(s || "").toLowerCase());
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fechaES = (iso) => (iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(0, 4) : "");
  const anioDe = (n) => parseInt(String(n).split("/")[1], 10) || 0;
  const numDe = (n) => parseInt(String(n).split("/")[0], 10) || 0;
  const soloDigitos = (s) => String(s || "").replace(/\D+/g, "");

  function clasificar(s) {
    const t = norm(s);
    if (!t) return "";
    if (/parcial/.test(t)) return "parcial";
    if (/desestim/.test(t)) return "desestima";
    if (/inadmi|inadmet|inadmis/.test(t)) return "inadmite";
    if (/desist|perd(a|ida)|perdua|archiv|arquiv|conclus|sin objeto|sense objecte|terminaci|finalitz|renunci/.test(t)) return "archivo";
    if (/estim/.test(t)) return "estima";
    return "otros";
  }
  const ETIQUETA = { estima: "Estimatoria", parcial: "Estimación parcial", desestima: "Desestimatoria", inadmite: "Inadmisión", archivo: "Desistimiento / pérdida de objeto", otros: "Otros" };

  function normalizarNumero(texto) {
    const t = String(texto || "").trim().replace(/\s+/g, "");
    if (!t) return null;
    const m = t.match(/^(\d{1,4})[\/\-_](\d{2,4})$/);
    if (m) {
      let a = parseInt(m[2], 10); if (a < 100) a += 2000;
      return { num: parseInt(m[1], 10), anio: a };
    }
    const n = t.match(/^\d{1,4}$/);
    return n ? { num: parseInt(n[0], 10), anio: null } : { texto: norm(t) };
  }

  function terminos(q) {
    const out = [];
    const re = /"([^"]+)"|(\S+)/g;
    let m;
    while ((m = re.exec(q || "")) !== null) out.push(norm(m[1] || m[2]));
    return out.filter(Boolean);
  }

  const CLASES = { a: "[aáàâä]", e: "[eéèêë]", i: "[iíìîï]", o: "[oóòôö]", u: "[uúùûü]", n: "[nñ]", c: "[cç]" };
  function regexResaltado(terms) {
    if (!terms.length) return null;
    const partes = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/[aeiounc]/g, (c) => CLASES[c]));
    return new RegExp("(" + partes.join("|") + ")", "gi");
  }
  function resaltar(texto, re) {
    const e = esc(texto);
    return re ? e.replace(re, "<mark>$1</mark>") : e;
  }

  // ------------------------------------------------------------ carga
  async function cargar() {
    const meta = await (await fetch("data/meta.json", { cache: "no-cache" })).json();
    estado.meta = meta;
    pintarTribunales(meta.tribunales);
    const porId = Object.fromEntries(meta.tribunales.map((t) => [t.id, t]));
    const ficheros = meta.tribunales.filter((t) => t.fichero);
    let cargados = 0;
    const partes = await Promise.all(ficheros.map(async (t) => {
      try {
        const datos = await (await fetch(t.fichero, { cache: "no-cache" })).json();
        cargados++;
        $("#subtitulo").textContent = `Cargando el índice… ${cargados}/${ficheros.length} tribunales`;
        return datos;
      } catch (e) {
        console.error("No se pudo cargar", t.fichero, e);
        return [];
      }
    }));
    const registros = [];
    for (const parte of partes) for (const r of parte) {
      r._a = anioDe(r.n);
      r._nn = numDe(r.n);
      r._c = clasificar(r.s);
      r._h = norm([r.n, r.r, r.d, r.o, r.a, r.s, r.c, porId[r.t] && porId[r.t].siglas].filter(Boolean).join(" \u0001 "));
      r._rd = soloDigitos(r.r);
      registros.push(r);
    }
    estado.registros = registros;
    pintarAnios(registros);
    try { estado.estadoCarga = await (await fetch("data/estado.json", { cache: "no-cache" })).json(); } catch (e) { /* opcional */ }
    pintarEstado();
    const fecha = meta.actualizado ? fechaES(meta.actualizado.slice(0, 10)) : "";
    $("#subtitulo").textContent = `${registros.length.toLocaleString("es-ES")} resoluciones de ${ficheros.length} tribunales. Índice actualizado el ${fecha}.`;
    leerURL();
    buscar();
  }

  function pintarTribunales(tribunales) {
    const fs = $("#tribunales");
    for (const t of tribunales) {
      const lab = document.createElement("label");
      lab.title = t.nombre + (t.ambito ? " · " + t.ambito : "");
      const sin = !t.fichero;
      if (sin) lab.classList.add("sin-datos");
      lab.innerHTML = `<input type="checkbox" name="t" value="${t.id}" ${sin ? "disabled" : "checked"}> ${esc(t.siglas)} <small>${sin ? "sin índice" : t.total.toLocaleString("es-ES")}</small>`;
      fs.appendChild(lab);
    }
  }

  function pintarAnios(registros) {
    const anios = [...new Set(registros.map((r) => r._a).filter(Boolean))].sort((a, b) => b - a);
    const sel = $("#anio");
    for (const a of anios) { const o = document.createElement("option"); o.value = a; o.textContent = a; sel.appendChild(o); }
  }

  function pintarEstado() {
    const e = estado.estadoCarga;
    if (!e) return;
    const problemas = Object.entries(e).filter(([, v]) => v && v.ok === false);
    const porId = Object.fromEntries((estado.meta.tribunales || []).map((t) => [t.id, t]));
    let txt = "";
    if (problemas.length) {
      txt = "Última pasada con incidencias en: " + problemas.map(([k, v]) => `${porId[k] ? porId[k].siglas : k} (${v.error || "error"})`).join("; ") + ".";
    } else {
      txt = "La última actualización nocturna terminó sin incidencias en todos los tribunales.";
    }
    $("#estado").textContent = txt;
  }

  // ------------------------------------------------------------ filtros
  function leerFiltros() {
    const t = [...document.querySelectorAll('#tribunales input[name="t"]:checked')].map((i) => i.value);
    return {
      q: $("#q").value.trim(), num: $("#num").value.trim(), rec: $("#rec").value.trim(),
      anio: $("#anio").value, desde: $("#desde").value, hasta: $("#hasta").value, sentido: $("#sentido").value, t,
    };
  }

  function escribirURL(f) {
    const p = new URLSearchParams();
    for (const k of ["q", "num", "rec", "anio", "desde", "hasta", "sentido"]) if (f[k]) p.set(k, f[k]);
    const todos = document.querySelectorAll('#tribunales input[name="t"]:not(:disabled)').length;
    if (f.t.length && f.t.length < todos) p.set("t", f.t.join(","));
    const qs = p.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  function leerURL() {
    const p = new URLSearchParams(location.search);
    for (const k of ["q", "num", "rec", "anio", "desde", "hasta", "sentido"]) if (p.get(k)) $("#" + k).value = p.get(k);
    if (p.get("t")) {
      const set = new Set(p.get("t").split(","));
      document.querySelectorAll('#tribunales input[name="t"]').forEach((i) => { if (!i.disabled) i.checked = set.has(i.value); });
    }
  }

  function filtrar(f) {
    const terms = terminos(f.q);
    const numF = normalizarNumero(f.num);
    const recRaw = norm(f.rec), recDig = soloDigitos(f.rec);
    const anio = parseInt(f.anio, 10) || 0;
    const trib = new Set(f.t);
    return estado.registros.filter((r) => {
      if (!trib.has(r.t)) return false;
      if (anio && r._a !== anio) return false;
      if (f.desde && (!r.f || r.f < f.desde)) return false;
      if (f.hasta && (!r.f || r.f > f.hasta)) return false;
      if (f.sentido && r._c !== f.sentido) return false;
      if (numF) {
        if (numF.texto) { if (!norm(r.n).includes(numF.texto)) return false; }
        else if (r._nn !== numF.num || (numF.anio && r._a !== numF.anio)) return false;
      }
      if (recRaw) {
        const okRaw = r.r && norm(r.r).includes(recRaw);
        const okDig = recDig.length >= 3 && r._rd && (r._rd === recDig || (recDig.length >= 5 && r._rd.includes(recDig)));
        if (!okRaw && !okDig) return false;
      }
      for (const t of terms) if (!r._h.includes(t)) return false;
      return true;
    });
  }

  function ordenar(lista) {
    const { campo, asc } = estado.orden;
    const sig = asc ? 1 : -1;
    const porId = Object.fromEntries(estado.meta.tribunales.map((t) => [t.id, t.siglas]));
    lista.sort((a, b) => {
      let va, vb;
      if (campo === "n") { va = a._a * 10000 + a._nn; vb = b._a * 10000 + b._nn; }
      else if (campo === "t") { va = porId[a.t] || a.t; vb = porId[b.t] || b.t; }
      else { va = a[campo] || ""; vb = b[campo] || ""; }
      if (va < vb) return -sig;
      if (va > vb) return sig;
      // desempate: fecha desc, número desc
      if ((a.f || "") !== (b.f || "")) return (a.f || "") < (b.f || "") ? 1 : -1;
      return b._a * 10000 + b._nn - (a._a * 10000 + a._nn);
    });
  }

  function buscar() {
    const f = leerFiltros();
    escribirURL(f);
    estado.filtrados = filtrar(f);
    ordenar(estado.filtrados);
    estado.mostrados = 0;
    $("#cuerpo").innerHTML = "";
    mostrarMas(f);
    const n = estado.filtrados.length;
    const hayFiltro = f.q || f.num || f.rec || f.anio || f.desde || f.hasta || f.sentido;
    $("#resumen").textContent = n === 0 ? "Ninguna resolución coincide." : `${n.toLocaleString("es-ES")} resoluciones` + (hayFiltro ? "" : " (las más recientes primero)");
    pintarEnlacesOficiales(f);
    const aviso = $("#aviso-tacrc");
    if (hayFiltro && (f.t.length === 0 || f.t.includes("tacrc") || document.querySelector('#tribunales input[value="tacrc"]'))) {
      aviso.hidden = false;
      aviso.innerHTML = "Las resoluciones del <strong>TACRC</strong> (y de las comunidades que tiene conveniadas) no están en este índice: su buscador exige una comprobación anti-robots. Use el enlace al buscador oficial o el constructor de enlaces al PDF, más abajo.";
    } else aviso.hidden = true;
  }

  function mostrarMas(f) {
    f = f || leerFiltros();
    const re = regexResaltado(terminos(f.q));
    const porId = Object.fromEntries(estado.meta.tribunales.map((t) => [t.id, t]));
    const trozo = estado.filtrados.slice(estado.mostrados, estado.mostrados + PAGINA);
    const html = trozo.map((r) => fila(r, porId[r.t], re)).join("");
    if (estado.mostrados === 0 && !trozo.length) {
      $("#cuerpo").innerHTML = '<tr class="vacio"><td colspan="7">Sin resultados. Pruebe con menos filtros o busque en las webs oficiales (abajo).</td></tr>';
    } else {
      $("#cuerpo").insertAdjacentHTML("beforeend", html);
    }
    estado.mostrados += trozo.length;
    $("#mas").hidden = estado.mostrados >= estado.filtrados.length;
  }

  const CLASE_DOC = { acuerdo: "Acuerdo", cautelar: "cautelar / desistimiento", rectificacion: "Rectificación" };
  function fila(r, trib, re) {
    let doc = trib ? trib.documento : "Resolución";
    if (r.k === "acuerdo") doc = "Acuerdo";
    if (r.k === "cautelar" || r.k === "rectificacion") doc = "Resolución";
    const clase = r.k ? ` <span class="marca otros">${CLASE_DOC[r.k] || r.k}</span>` : "";
    const sent = r.s ? `<span class="marca ${r._c}">${esc(ETIQUETA[r._c] || "")}</span><br><small>${resaltar(r.s, re)}</small>` : "";
    const extra = [r.a, r.c].filter(Boolean).join(" · ");
    const enlaces = [];
    if (r.pdf) enlaces.push(`<a href="${esc(r.pdf)}" target="_blank" rel="noopener">PDF${r.p2 ? (r.t === "oarc" ? " (es)" : " (es)") : ""}</a>`);
    if (r.p2) enlaces.push(`<a href="${esc(r.p2)}" target="_blank" rel="noopener">${r.t === "oarc" ? "PDF (eu)" : "PDF (gl)"}</a>`);
    if (r.url) enlaces.push(`<a href="${esc(r.url)}" target="_blank" rel="noopener">Ficha</a>`);
    return `<tr>
      <td class="trib" title="${esc(trib ? trib.nombre : r.t)}">${esc(trib ? trib.siglas : r.t)}</td>
      <td class="num">${doc} ${resaltar(r.n, re)}${clase}</td>
      <td class="fecha">${fechaES(r.f)}</td>
      <td class="rec">${resaltar(r.r || "", re)}</td>
      <td class="sent">${sent}</td>
      <td class="desc">${r.o ? `<span class="org">${resaltar(r.o, re)}</span>` : ""}<span class="obj">${resaltar(r.d || "", re)}</span>${extra ? `<span class="extra">${resaltar(extra, re)}</span>` : ""}</td>
      <td class="enl">${enlaces.join("")}</td>
    </tr>`;
  }

  // ------------------------------------------------------------ enlaces a los buscadores oficiales
  function enlaceOficial(t, f) {
    const numF = normalizarNumero(f.num) || {};
    const num = numF.num || null;
    const anio = numF.anio || parseInt(f.anio, 10) || null;
    const na = num && anio ? `${num}/${anio}` : "";
    const q = f.q || "";
    const u = (base, params) => {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
      const qs = p.toString();
      return base + (qs ? (base.includes("?") ? "&" : "?") + qs : "");
    };
    switch (t.id) {
      case "madrid": return u("https://www.comunidad.madrid/tacp/busquedaresoluciones", { field_numero_de_resolucion: na, field_numero_de_expediente: f.rec, search_api_views_fulltext: q });
      case "cyl": return u("https://www.cccyl.es/es/tribunal-administrativo-recursos-contractuales-castilla-leo/resoluciones.buscar", { formName: "searchForm", S_RES_NUMERO_RES_min: na, S_RES_NUM_RECURSO_min: f.rec, pattern: q });
      case "andalucia": return u("https://www.juntadeandalucia.es/organismos/tarc/servicios/resoluciones.html", { field_res_num_fecha_res: na, field_expediente_oc: f.rec, text: q, items_per_page: "50" });
      case "galicia": return null; // formulario POST (se genera aparte)
      case "navarra": return anio ? `https://portalcontratacion.navarra.es/es/acuerdos-${anio}` : "https://portalcontratacion.navarra.es/es/todos-acuerdos";
      case "cataluna": return u("https://contractacio.gencat.cat/ca/contacte/tccsp/cercador-resolucions/index.html", { numero: num ? String(num) : "", datainf: anio ? `01/01/${anio}` : "", datasup: anio ? `31/12/${anio}` : "", text: q });
      case "aragon": return u("https://gd.aragon.es/cgi-bin/ACTA/BRSCGI?CMD=VERLST&BASE=ACTA&DOCS=1-100&SEC=ACTA_PUBL&SORT=@FEPU&SEPARADOR=", { "NUME-C": na, "@FERE-GE": anio ? `${anio}0101` : "", "@FERE-LE": anio ? `${anio}1231` : "", "TEMA-C": q });
      case "oarc": return na ? `https://www.euskadi.eus/contenidos/resolucion_oarc/${num}_${anio}/es_def/index.shtml` : "https://www.contratacion.euskadi.eus/webkpe00-kpeoarc/es/y96aResolucionesWar/busqueda/listado";
      case "canarias": return u("https://www.gobiernodecanarias.org/hacienda/contratacion/tacp/visor_resoluciones/index.jsp?param_page=1&param_accion=buscar", { chpae_resolucion_numero_resolucion_es: na, chpae_resolucion_numero_expediente_es: f.rec, chpae_resolucion_texto_libre_es: q });
      case "tacrc": return t.buscador;
      default: return t.buscador;
    }
  }

  function pintarEnlacesOficiales(f) {
    const ul = $("#enlaces-oficiales");
    const numF = normalizarNumero(f.num) || {};
    const anio = numF.anio || parseInt(f.anio, 10) || "";
    ul.innerHTML = estado.meta.tribunales.map((t) => {
      const href = enlaceOficial(t, f);
      let cuerpo;
      if (t.id === "galicia") {
        const n4 = numF.num ? String(numF.num).padStart(4, "0") : "";
        cuerpo = `<form method="post" action="https://tacgal.xunta.gal/sixtacweb/resolucions/" target="_blank" style="display:inline">
          <input type="hidden" name="locale" value="es"><input type="hidden" name="numResolucion" value="${esc(n4)}"><input type="hidden" name="anoResolucion" value="${esc(anio)}"><input type="hidden" name="contenido" value="${esc(f.q || "")}">
          <button type="submit" class="enlace">${esc(t.siglas)}</button></form>`;
      } else {
        cuerpo = `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(t.siglas)}</a>`;
      }
      return `<li>${cuerpo}<small>${esc(t.nombre)}${t.idioma && t.idioma !== "es" ? " · " + (t.idioma === "ca" ? "en catalán" : t.idioma === "gl" ? "en gallego y castellano" : "") : ""}</small></li>`;
    }).join("");
  }

  function urlTACRC(rec, suf, res, fechaISO) {
    const r = normalizarNumero(rec), s = normalizarNumero(res);
    if (!r || !r.num || !s || !s.num || !fechaISO) return null;
    const anioRec = r.anio || parseInt(fechaISO.slice(0, 4), 10);
    const anioRes = s.anio || anioRec;
    const recurso = String(r.num).padStart(4, "0") + "-" + anioRec;
    const fecha = fechaISO.slice(8, 10) + "-" + fechaISO.slice(5, 7) + "-" + fechaISO.slice(0, 4);
    const sufijo = suf ? ` ${suf} ${String(r.num).padStart(3, "0")}-${anioRec}` : "";
    const nombre = `Recurso ${recurso}${sufijo} (Res ${s.num}) ${fecha}.pdf`;
    return `https://www.hacienda.gob.es/TACRC/Resoluciones/${encodeURIComponent("Año " + anioRes)}/${encodeURIComponent(nombre)}`;
  }

  // ------------------------------------------------------------ eventos
  $("#filtros").addEventListener("submit", (e) => { e.preventDefault(); buscar(); });
  for (const id of ["anio", "sentido", "desde", "hasta"]) $("#" + id).addEventListener("change", buscar);
  $("#tribunales").addEventListener("change", buscar);
  $("#q").addEventListener("input", debounce(buscar, 250));
  $("#num").addEventListener("input", debounce(buscar, 250));
  $("#rec").addEventListener("input", debounce(buscar, 250));
  $("#todos").addEventListener("click", () => { document.querySelectorAll('#tribunales input:not(:disabled)').forEach((i) => (i.checked = true)); buscar(); });
  $("#ninguno").addEventListener("click", () => { document.querySelectorAll('#tribunales input').forEach((i) => (i.checked = false)); buscar(); });
  $("#limpiar").addEventListener("click", () => {
    for (const id of ["q", "num", "rec", "anio", "desde", "hasta", "sentido"]) $("#" + id).value = "";
    document.querySelectorAll('#tribunales input:not(:disabled)').forEach((i) => (i.checked = true));
    buscar();
  });
  $("#mas").addEventListener("click", () => mostrarMas());
  document.querySelectorAll("th[data-orden]").forEach((th) => th.addEventListener("click", () => {
    const campo = th.dataset.orden;
    if (estado.orden.campo === campo) estado.orden.asc = !estado.orden.asc; else estado.orden = { campo, asc: campo !== "f" && campo !== "n" };
    document.querySelectorAll("th[data-orden]").forEach((x) => x.classList.remove("activa", "asc", "desc"));
    th.classList.add("activa", estado.orden.asc ? "asc" : "desc");
    buscar();
  }));
  $("#form-tacrc").addEventListener("submit", (e) => {
    e.preventDefault();
    const url = urlTACRC($("#tacrc-rec").value, $("#tacrc-suf").value, $("#tacrc-res").value, $("#tacrc-fecha").value);
    const p = $("#tacrc-url");
    if (!url) { p.textContent = "Faltan datos: hacen falta el número de recurso, el de resolución y la fecha."; return; }
    p.innerHTML = `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(decodeURIComponent(url))}</a><br><small>Si el enlace da error, el tribunal pudo usar otra variante del nombre (sufijo de comunidad, «corregida», año de dos cifras en 2014): búsquela en el buscador oficial.</small>`;
    window.open(url, "_blank", "noopener");
  });

  function debounce(fn, ms) { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; }

  cargar().catch((e) => { $("#subtitulo").textContent = "No se pudo cargar el índice: " + e.message; console.error(e); });
})();
