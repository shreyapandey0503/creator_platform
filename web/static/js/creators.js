/* Creators view: upload + import receipts + the creator universe (clusters, facets, segments, cards). */
"use strict";

const FACET_LABEL = {
  region: "Region", city: "City", age_band: "Creator age", gender: "Gender", size_tier: "Audience size",
  budget_tier: "Price per reel", languages: "Language", engagement: "Engagement vs peers",
  primary_platform: "Platform", segment: "Smart segment", niche: "Niche", q: "Search",
};
const Lib = { batches: null, filters: {}, sort: "fit_value", offset: 0, charts: {}, imports: [] };

async function mountCreators(view) {
  view.appendChild($("#tpl-creators").content.cloneNode(true));
  Lib.filters = {};
  Lib.offset = 0;
  Lib.charts = {};
  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (ev) => { const f = ev.dataTransfer.files[0]; if (f) uploadFile(f); });
  for (const id of ["#file", "#fileTop"]) {
    $(id).addEventListener("change", (e) => { if (e.target.files[0]) uploadFile(e.target.files[0]); e.target.value = ""; });
  }
  $("#useSample").addEventListener("click", () => runImport(() => api("/api/use-sample", {})));
  $("#sort").addEventListener("change", (e) => { Lib.sort = e.target.value; refreshUniverse(); });
  $("#more").addEventListener("click", () => { Lib.offset += 24; refreshUniverse(true); });
  let t;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { e.target.value ? (Lib.filters.q = e.target.value) : delete Lib.filters.q; refreshUniverse(); }, 300);
  });
  await loadLibrary();
}

async function loadLibrary(showReceiptFor) {
  Lib.imports = await api("/api/imports");
  const empty = !Lib.imports.length;
  $("#emptyLib").hidden = !empty;
  $("#universe").hidden = empty;
  if (empty) return;
  renderImports();
  if (showReceiptFor) renderReceipt(showReceiptFor);
  await refreshUniverse();
}

function renderImports() {
  const all = Lib.batches == null;
  $("#imports").innerHTML = `<span class="muted">Showing:</span>
    <button class="chip ${all ? "on" : ""}" data-b="">All imports <i>${Lib.imports.reduce((a, b) => a + b.creators, 0)}</i></button>` +
    Lib.imports.map((b) => `<button class="chip ${Lib.batches && Lib.batches[0] === b.batch_id ? "on" : ""}" data-b="${b.batch_id}"
      title="Imported ${fmtDate(b.ingested_at)}">${esc(b.file_name)} <i>${b.creators}</i></button>`).join("") +
    `<button class="linkish" id="showReceipt">${Lib.batches ? "View import report" : ""}</button>`;
  $$("#imports .chip").forEach((c) => c.addEventListener("click", () => {
    Lib.batches = c.dataset.b ? [+c.dataset.b] : null;
    Lib.filters = {};
    $("#receipt").hidden = true;
    renderImports();
    refreshUniverse();
  }));
  const rb = $("#showReceipt");
  if (rb) rb.addEventListener("click", () => renderReceipt(Lib.imports.find((b) => b.batch_id === Lib.batches[0])));
}

function uploadFile(file) {
  if (!/\.csv$/i.test(file.name)) return toast("Please upload a .csv file", "bad");
  const fd = new FormData();
  fd.append("file", file);
  runImport(() => api("/api/upload", fd));
}

async function runImport(call) {
  const ov = $("#processing");
  const steps = $$("#procSteps li");
  steps.forEach((s) => (s.className = ""));
  ov.hidden = false;
  let i = 0;
  const tick = setInterval(() => {
    if (i > 0) steps[i - 1].className = "done";
    if (i < steps.length) steps[i].className = "on";
    i = Math.min(i + 1, steps.length);
  }, 600);
  try {
    const [report] = await Promise.all([call(), new Promise((r) => setTimeout(r, 2200))]);
    clearInterval(tick);
    steps.forEach((s) => (s.className = "done"));
    await new Promise((r) => setTimeout(r, 300));
    ov.hidden = true;
    Lib.batches = [report.batch_id];
    Lib.filters = {};
    await loadLibrary(report);
    $("#receipt").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    clearInterval(tick);
    ov.hidden = true;
    toast("Import failed: " + e.message, "bad");
  }
}

function renderReceipt(r) {
  if (!r) return;
  const fixes = r.fixes.map((f) => `<span class="fix" title="${esc(f.issue)}"><b>${f.count}</b>${esc(f.label)}</span>`).join("");
  const bad = r.rejected_reasons.map((f) => `<span class="fix bad"><b>${f.count}</b>${esc(f.label)}</span>`).join("");
  const cols = Object.entries(r.columns).map(([k, v]) => `<code>${esc(v)}</code> → ${esc(k)}`).join(" · ");
  $("#receiptBody").innerHTML = `
    <div class="receipt-top"><p class="eyebrow" style="margin:0">Import report</p><h3>${esc(r.file_name)}</h3>
      ${r.already_imported ? '<span class="muted">(this file was already imported)</span>' : ""}
      <button class="linkish" style="margin-left:auto" onclick="this.closest('#receipt').hidden=true">Close ✕</button></div>
    <div class="flow">
      <div class="node"><b>${r.rows}</b><span>rows in the file</span></div><span class="arrow">→</span>
      <div class="node"><b>${r.rejected}</b><span>rejected (unusable)</span></div><span class="arrow">→</span>
      <div class="node"><b>${r.duplicates_merged}</b><span>duplicates merged</span></div><span class="arrow">→</span>
      <div class="node hot"><b>${r.creators}</b><span>unique creators</span></div>
      <div class="node"><b>${r.total_fixes}</b><span>values cleaned</span></div>
    </div>
    <div><div class="muted" style="font-size:12px;margin-bottom:6px">What we fixed</div><div class="fixes">${fixes}${bad}</div></div>
    <div class="mapping">Columns understood: ${cols}${r.ignored_columns.length ? ` · ignored: ${r.ignored_columns.map(esc).join(", ")}` : ""}</div>`;
  $("#receipt").hidden = false;
}

async function refreshUniverse(append = false) {
  if (!append) Lib.offset = 0;
  const data = await api("/api/universe", { batches: Lib.batches, filters: Lib.filters, sort: Lib.sort, limit: 24, offset: Lib.offset });
  if (!data.total) return;
  if (append) {
    $("#cards").insertAdjacentHTML("beforeend", data.creators.map(cardHTML).join(""));
  } else {
    const c = data.coverage;
    $("#uniLede").innerHTML = `<b>${data.total.toLocaleString()}</b> creators, clustered by niche, place, age and price.
      Coverage: city ${c.city}% · age ${c.age}% · rate card ${c.rate}% · views ${c.views}%.`;
    renderNiches(data.niches);
    renderFacets(data.facets);
    renderActive();
    renderStats(data);
    renderSegments(data.segments);
    renderCharts(data);
    $("#cards").innerHTML = data.creators.map(cardHTML).join("") || '<p class="muted">No creators match these filters.</p>';
  }
  $("#gridTitle").textContent = `Creators · ${data.matched.toLocaleString()} match`;
  $("#more").hidden = Lib.offset + 24 >= data.matched;
}

function toggleFilter(field, value) {
  const cur = new Set(Lib.filters[field] || []);
  cur.has(value) ? cur.delete(value) : cur.add(value);
  Lib.filters[field] = [...cur];
  if (!Lib.filters[field].length) delete Lib.filters[field];
  refreshUniverse();
}

function renderNiches(tiles) {
  const on = new Set(Lib.filters.niche || []);
  $("#niches").innerHTML = tiles.map((t) => `
    <div class="niche ${on.has(t.niche) ? "on" : ""}" style="--c:${nc(t.niche)}" data-niche="${esc(t.niche)}">
      <span class="emo">${ne(t.niche)}</span><h4>${esc(t.niche)}</h4>
      <div class="count">${t.count}<small>creators</small></div>
      <div class="facts"><span><b>${fmtINR(t.median_rate)}</b> median per reel · <b>${t.median_er != null ? t.median_er.toFixed(1) + "%" : "—"}</b> ER</span>
        <span>${t.top_cities.map(esc).join(" · ") || "&nbsp;"}</span></div>
      <div class="tags">${t.top_tags.slice(0, 3).map((x) => `<span>${esc(x)}</span>`).join("")}</div>
    </div>`).join("");
  $$("#niches .niche").forEach((el) => el.addEventListener("click", () => toggleFilter("niche", el.dataset.niche)));
}

function renderFacets(facets) {
  const order = ["segment", "region", "city", "budget_tier", "size_tier", "age_band", "gender", "languages", "engagement", "primary_platform"];
  $("#facets").innerHTML = order.filter((f) => facets[f] && facets[f].length).map((f) => {
    const sel = new Set(Lib.filters[f] || []);
    const chips = facets[f].map((v) => {
      const label = f === "primary_platform" ? (PLAT[v.value] || v.value) : v.value;
      return `<button class="chip ${sel.has(v.value) ? "on" : ""} ${v.count ? "" : "zero"}" data-f="${f}" data-v="${esc(v.value)}">${esc(label)} <i>${v.count}</i></button>`;
    }).join("");
    return `<div class="facet"><h5>${FACET_LABEL[f]}${sel.size ? `<button data-clear="${f}">clear</button>` : ""}</h5><div class="chips">${chips}</div></div>`;
  }).join("");
  $$("#facets .chip").forEach((b) => b.addEventListener("click", () => toggleFilter(b.dataset.f, b.dataset.v)));
  $$("#facets [data-clear]").forEach((b) => b.addEventListener("click", () => { delete Lib.filters[b.dataset.clear]; refreshUniverse(); }));
}

function renderActive() {
  const chips = [];
  for (const [f, vals] of Object.entries(Lib.filters)) {
    if (f === "q") { if (vals) chips.push(`<button class="chip on" data-f="q">Search: ${esc(vals)} ✕</button>`); continue; }
    vals.forEach((v) => chips.push(`<button class="chip" data-f="${f}" data-v="${esc(v)}">${FACET_LABEL[f]}: <b>${esc(v)}</b> ✕</button>`));
  }
  if (chips.length) chips.push('<button class="chip" data-all="1">Clear all</button>');
  $("#activeBar").innerHTML = chips.join("");
  $$("#activeBar .chip").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.all) { Lib.filters = {}; $("#q").value = ""; return refreshUniverse(); }
    if (b.dataset.f === "q") { delete Lib.filters.q; $("#q").value = ""; return refreshUniverse(); }
    toggleFilter(b.dataset.f, b.dataset.v);
  }));
}

function renderStats(d) {
  const s = d.stats;
  $("#statStrip").innerHTML = [
    [d.matched.toLocaleString(), "creators in view"], [fmtN(s.median_followers), "median followers"],
    [s.median_er != null ? s.median_er.toFixed(1) + "%" : "—", "median engagement"],
    [fmtINR(s.median_rate), "median price / reel"], [s.median_cpv != null ? "₹" + s.median_cpv.toFixed(2) : "—", "median ₹ per view"],
    [s.cities, "cities"], [s.languages, "languages"],
  ].map(([b, l]) => `<div class="stat"><b>${b}</b><span>${l}</span></div>`).join("");
}

function renderSegments(segs) {
  const on = new Set(Lib.filters.segment || []);
  $("#segments").innerHTML = segs.map((s) => `
    <div class="seg ${on.has(s.name) ? "on" : ""}" data-seg="${esc(s.name)}">
      <h4>${esc(s.name)}</h4><p>${esc(s.description)}</p>
      <div class="nums"><div><b>${s.count}</b>creators</div><div><b>${fmtN(s.median_followers)}</b>followers</div><div><b>${fmtINR(s.median_rate)}</b>per reel</div>
        <div><b>${s.median_er != null ? s.median_er.toFixed(1) + "%" : "—"}</b>ER</div><div><b>${s.median_cpv != null ? "₹" + s.median_cpv.toFixed(2) : "—"}</b>per view</div><div><b>${s.median_age ?? "—"}</b>age</div></div>
      <div class="seg-foot">${s.top_niches.map(esc).join(" · ")}${s.in_filter !== s.count ? ` · <b style="color:var(--marigold)">${s.in_filter} in view</b>` : ""}</div>
    </div>`).join("");
  $$("#segments .seg").forEach((el) => el.addEventListener("click", () => toggleFilter("segment", el.dataset.seg)));
}

function cardHTML(c) {
  const meta = [c.city, c.age ? c.age + " yrs" : null, c.gender, (c.languages || []).slice(0, 2).join(", ")].filter(Boolean).map(esc).join(" · ");
  const tags = (c.tags || []).slice(0, 2).map((t) => `<span>${esc(t)}</span>`).join("");
  const eng = c.engagement ? `<span class="badge ${c.engagement}">${c.engagement}</span>` : "";
  const warn = c.suspicious_er ? '<span class="badge warn" title="Engagement spike — verify">verify ER</span>' : "";
  return `<article class="card" style="--c:${nc(c.niche)}">
    <div class="card-top"><div class="avatar">${esc(initials(c.name))}</div>
      <div><div class="nm">${esc(c.name)}</div><div class="hd">${c.handle ? "@" + esc(c.handle) : ""}<span class="plat">${PLAT[c.primary_platform] || esc(c.primary_platform)}</span></div></div></div>
    <div class="meta">${meta || "&nbsp;"}</div>
    <div class="ctags"><span class="n">${ne(c.niche)} ${esc(c.niche)}</span>${tags}</div>
    <div class="nums">
      <div><b>${fmtN(c.followers)}</b><span>followers</span></div>
      <div><b>${c.er != null ? c.er.toFixed(1) + "%" : "—"}</b><span>ER ${eng}</span></div>
      <div><b>${fmtINR(c.rate_reel)}</b><span>per reel</span></div>
    </div>
    <div class="value"><span>${c.cpv != null ? `₹${c.cpv.toFixed(2)} per view` : "no rate card"} ${warn}</span><span>${esc(c.segment_name || "")}</span></div>
  </article>`;
}

function renderCharts(d) {
  if (!window.echarts) return;
  const txt = "#b3a9cf";
  Lib.charts.sun = echarts.getInstanceByDom($("#sunburst")) || echarts.init($("#sunburst"));
  Lib.charts.sc = echarts.getInstanceByDom($("#scatter")) || echarts.init($("#scatter"));
  Lib.charts.sun.setOption({
    tooltip: { formatter: (p) => `${esc(p.treePathInfo.slice(1).map((x) => x.name).join(" › "))}<br><b>${p.value}</b> creators` },
    series: [{
      type: "sunburst", data: d.sunburst.map((n) => ({ ...n, itemStyle: { color: nc(n.name) } })), radius: ["14%", "92%"],
      sort: null, nodeClick: "rootToNode", itemStyle: { borderColor: "#0d0a1c", borderWidth: 1.5 },
      label: { color: "#fff", fontSize: 10, minAngle: 12, fontFamily: "Inter" },
      levels: [{}, { r0: "14%", r: "58%", label: { rotate: "radial", fontWeight: 700, fontSize: 11, minAngle: 10 } },
        { r0: "58%", r: "92%", itemStyle: { opacity: .72 }, label: { fontSize: 9.5, minAngle: 9, color: "#fff" } }],
      emphasis: { focus: "ancestor" },
    }],
  }, true);
  const byNiche = {};
  d.scatter.forEach((p) => (byNiche[p.niche] = byNiche[p.niche] || []).push(p));
  Lib.charts.sc.setOption({
    grid: { left: 50, right: 20, top: 20, bottom: 70 },
    legend: { bottom: 0, textStyle: { color: txt, fontSize: 11 }, icon: "circle", itemWidth: 8, type: "scroll", pageTextStyle: { color: txt } },
    tooltip: { formatter: (p) => { const v = p.data.raw; return `<b>${esc(v.name)}</b><br>${esc(v.niche)} · ${esc(v.city || "")}<br>${fmtN(v.followers)} followers · ${v.er.toFixed(1)}% ER<br>${fmtINR(v.rate_reel)} per reel`; } },
    xAxis: { type: "log", name: "followers", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: txt }, axisLabel: { color: txt, formatter: (v) => fmtN(v) }, splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } } },
    yAxis: { type: "value", name: "ER %", max: (v) => Math.min(20, Math.ceil(v.max)), nameTextStyle: { color: txt }, axisLabel: { color: txt }, splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } } },
    series: Object.entries(byNiche).map(([n, pts]) => ({
      name: n, type: "scatter", itemStyle: { color: nc(n), opacity: .78, borderColor: "rgba(0,0,0,.35)" },
      data: pts.map((p) => ({ value: [Math.max(p.followers, 100), Math.min(p.er, 20)], raw: p, symbolSize: Math.max(5, Math.min(38, Math.sqrt((p.rate_reel || 2000) / 150))) })),
      emphasis: { focus: "series" },
    })),
  }, true);
}
