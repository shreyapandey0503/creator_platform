/* Campaigns: list, studio (brief -> matched pool -> save), campaign detail (pipeline, tracking, billing). */
"use strict";

const STATUS_PILL = { draft: "Draft", active: "Active", completed: "Completed", cancelled: "Cancelled" };
const CC_STATUS = [["shortlisted", "Shortlisted"], ["contacted", "Contacted"], ["negotiating", "Negotiating"],
  ["confirmed", "Confirmed"], ["submitted", "Content submitted"], ["live", "Live"], ["completed", "Completed"]];
const CC_LABEL = Object.fromEntries([...CC_STATUS, ["dropped", "Dropped"]]);
const COMMITTED = new Set(["confirmed", "submitted", "live", "completed"]);
const fee = (c) => (c.agreed_fee != null ? c.agreed_fee : c.quoted_fee);

/* ============================================================== list */
async function mountCampaigns(view) {
  const list = await api("/api/campaigns");
  const tabs = ["all", "draft", "active", "completed", "cancelled"];
  let tab = "all";
  const render = () => {
    const rows = list.filter((c) => tab === "all" || c.status === tab);
    $("#cList").innerHTML = rows.length ? rows.map(campaignCard).join("") :
      `<div class="empty glass"><div class="empty-art">◎</div><p>No ${tab === "all" ? "" : tab + " "}campaigns yet.</p>
       <a class="btn" href="#/campaigns/new">Create a campaign</a></div>`;
    $$("#cTabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === tab));
  };
  view.innerHTML = `
    <header class="page-head"><div><p class="eyebrow">Campaigns</p><h1>Your campaigns</h1></div>
      <div class="head-actions"><a class="btn sm" href="#/campaigns/new">+ New campaign</a></div></header>
    <div class="seg-ctl tabs" id="cTabs">${tabs.map((t) => `<button data-t="${t}">${t[0].toUpperCase() + t.slice(1)} <i>${t === "all" ? list.length : list.filter((c) => c.status === t).length}</i></button>`).join("")}</div>
    <div class="c-list" id="cList"></div>`;
  $$("#cTabs button").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.t; render(); }));
  render();
}

function campaignCard(c) {
  const k = c.kpis;
  const pct = k.creators ? Math.round((k.committed / k.creators) * 100) : 0;
  const spendPct = c.budget ? Math.min(100, Math.round((k.committed_spend / c.budget) * 100)) : 0;
  return `<a class="c-card glass" href="#/campaigns/${c.id}">
    <div class="c-top"><span class="pill ${c.status}">${STATUS_PILL[c.status]}</span><span class="muted">${fmtDate(c.created_at)}</span></div>
    <h3>${esc(c.name)}</h3>
    <p class="muted">${esc([c.brand, c.product].filter(Boolean).join(" · ")) || "&nbsp;"}</p>
    <div class="c-nums">
      <div><b>${k.committed}/${k.creators}</b><span>confirmed</span></div>
      <div><b>${k.live}</b><span>live posts</span></div>
      <div><b>${fmtN(k.views)}</b><span>views</span></div>
      <div><b>${k.actual_cpv != null ? "₹" + k.actual_cpv.toFixed(2) : "—"}</b><span>₹ / view</span></div>
    </div>
    <div class="meter"><i style="width:${pct}%"></i></div>
    <div class="c-foot"><span>${fmtINR(k.committed_spend)} of ${fmtINR(c.budget)} committed</span><span>${spendPct}%</span></div>
  </a>`;
}

/* ============================================================== studio */
const PRESETS = [
  { icon: "🍪", title: "Healthy snack launch", sub: "Mumbai & Pune · ₹5L · engagement",
    brief: { brand: "NutriCrunch", product: "Millet snack bars", niches: ["Food", "Fitness & Health"], keywords: "healthy eating, baking, nutrition, home cooking",
      cities: ["Mumbai", "Pune"], regions: [], age_bands: ["18-24", "25-34"], languages: ["Hindi", "Marathi", "English", "Hinglish"], gender: "any",
      platforms: [], deliverable: "reel", objective: "engagement", budget: 500000, count: 12, min_er: 0, exclude_brands: "Crunchwala" } },
  { icon: "💄", title: "Festive beauty drop", sub: "South India · ₹8L · awareness",
    brief: { brand: "Kolam Cosmetics", product: "Festive lip kit", niches: ["Beauty", "Fashion"], keywords: "makeup, skincare, ethnic wear, bridal",
      cities: [], regions: ["South"], age_bands: ["18-24", "25-34"], languages: ["Tamil", "Telugu", "Kannada", "Malayalam", "English"], gender: "any",
      platforms: [], deliverable: "reel", objective: "awareness", budget: 800000, count: 15, min_er: 0, exclude_brands: "Blush Bazaar" } },
  { icon: "📱", title: "Budget phone launch", sub: "Pan-India · ₹20L · awareness",
    brief: { brand: "Zing Mobile", product: "Z5 — ₹14,999", niches: ["Tech", "Gaming"], keywords: "phones, gadgets, mobile gaming, bgmi",
      cities: [], regions: [], age_bands: ["18-24", "25-34"], languages: [], gender: "any",
      platforms: [], deliverable: "reel", objective: "awareness", budget: 2000000, count: 10, min_er: 0, exclude_brands: "PixelPhone" } },
  { icon: "📈", title: "Investing app sign-ups", sub: "Metros · ₹6L · conversions",
    brief: { brand: "PaisaGrow", product: "SIP app", niches: ["Finance & Business", "Education"], keywords: "investing, personal finance, startups",
      cities: ["Mumbai", "Bengaluru", "Delhi", "Hyderabad"], regions: [], age_bands: ["25-34", "35-44"], languages: ["Hindi", "English", "Hinglish"], gender: "any",
      platforms: [], deliverable: "reel", objective: "conversions", budget: 600000, count: 10, min_er: 1, exclude_brands: "PaisaWise, StackSIP" } },
];
const BLANK_BRIEF = { brand: "", product: "", niches: [], keywords: "", cities: [], regions: [], age_bands: [], languages: [], gender: "any",
  platforms: [], deliverable: "reel", objective: "awareness", budget: 500000, count: 10, min_er: 0, exclude_brands: "" };
const Studio = { brief: null, options: null, result: null };
const BUDGET_MIN = Math.log(25000), BUDGET_MAX = Math.log(1e7);
const toSlider = (v) => Math.round(((Math.log(v) - BUDGET_MIN) / (BUDGET_MAX - BUDGET_MIN)) * 1000);
const fromSlider = (s) => { const v = Math.exp(BUDGET_MIN + (s / 1000) * (BUDGET_MAX - BUDGET_MIN)); const step = v < 2e5 ? 5000 : v < 2e6 ? 25000 : 100000; return Math.round(v / step) * step; };

async function mountStudio(view) {
  Studio.options = await api("/api/options");
  if (Studio.options.empty) {
    view.innerHTML = `<header class="page-head"><div><p class="eyebrow">New campaign</p><h1>Campaign studio</h1></div></header>
      <div class="empty glass"><div class="empty-art">✦</div><h3>Upload creators first</h3>
      <p class="muted">The studio matches your brief against your creator library.</p><a class="btn" href="#/creators">Go to creators →</a></div>`;
    return;
  }
  view.appendChild($("#tpl-new-campaign").content.cloneNode(true));
  $("#presets").innerHTML = PRESETS.map((p, i) => `<button class="preset" data-i="${i}">${p.icon} ${esc(p.title)}<small>${esc(p.sub)}</small></button>`).join("");
  $$("#presets .preset").forEach((el) => el.addEventListener("click", () => { buildBrief(PRESETS[+el.dataset.i].brief); runMatch(); }));
  $("#brief").addEventListener("submit", (e) => { e.preventDefault(); runMatch(); });
  Studio.result = null;
  buildBrief(BLANK_BRIEF);
}

function buildBrief(preset) {
  Studio.brief = structuredClone(preset);
  const o = Studio.options || {};
  const b = Studio.brief;
  const chipset = (key, values, labelFn = (x) => x) => `<div class="chips">${(values || []).map((v) =>
    `<button type="button" class="chip ${b[key].includes(v) ? "on" : ""}" data-k="${key}" data-v="${esc(v)}">${esc(labelFn(v))}</button>`).join("")}</div>`;
  const seg = (key, opts) => `<div class="seg-ctl">${opts.map(([v, l]) => `<button type="button" class="${b[key] === v ? "on" : ""}" data-seg="${key}" data-v="${v}">${l}</button>`).join("")}</div>`;
  const niches = [...new Set([...(o.niches || []), ...b.niches])].filter((n) => n !== "Uncategorised");
  const cities = [...new Set([...b.cities, ...(o.cities || []).slice(0, 16)])];
  $("#brief").innerHTML = `
    <div class="row2">
      <div class="field"><label>Brand</label><input type="text" data-in="brand" value="${esc(b.brand)}" placeholder="e.g. NutriCrunch"></div>
      <div class="field"><label>Product</label><input type="text" data-in="product" value="${esc(b.product)}" placeholder="e.g. Millet bars"></div>
    </div>
    <div class="field"><span class="lbl">Niches</span>${chipset("niches", niches, (n) => `${ne(n)} ${n}`)}</div>
    <div class="field"><label>Keywords / sub-niches</label><input type="text" data-in="keywords" value="${esc(b.keywords)}" placeholder="healthy eating, baking…"></div>
    <div class="field"><span class="lbl">Target cities</span>${chipset("cities", cities)}</div>
    <div class="field"><span class="lbl">…or regions</span>${chipset("regions", o.regions || [])}</div>
    <div class="field"><span class="lbl">Creator age (proxy for audience)</span>${chipset("age_bands", o.age_bands || [])}</div>
    <div class="field"><span class="lbl">Languages</span>${chipset("languages", o.languages || [])}</div>
    <div class="row2">
      <div class="field"><span class="lbl">Deliverable</span>${seg("deliverable", [["reel", "Reel"], ["story", "Story"], ["video", "YT video"]])}</div>
      <div class="field"><span class="lbl">Creator gender</span>${seg("gender", [["any", "Any"], ["Female", "F"], ["Male", "M"]])}</div>
    </div>
    <div class="field"><span class="lbl">Objective</span>${seg("objective", [["awareness", "Awareness"], ["engagement", "Engagement"], ["conversions", "Conversions"]])}</div>
    <div class="field"><span class="lbl">Total creator budget</span><div class="range-val" id="budgetVal">${fmtINR(b.budget)}</div>
      <input type="range" min="0" max="1000" value="${toSlider(b.budget)}" id="budget"></div>
    <div class="row2">
      <div class="field"><span class="lbl">Creators wanted</span><div class="range-val" id="countVal">${b.count}</div><input type="range" min="2" max="40" value="${b.count}" id="count"></div>
      <div class="field"><span class="lbl">Min engagement</span><div class="range-val" id="erVal">${b.min_er}%</div><input type="range" min="0" max="10" step="0.5" value="${b.min_er}" id="minEr"></div>
    </div>
    <div class="field"><label>Exclude creators who worked with</label><input type="text" data-in="exclude_brands" list="brandList" value="${esc(b.exclude_brands)}" placeholder="competitor brands, comma separated">
      <datalist id="brandList">${(o.brands || []).map((x) => `<option value="${esc(x)}">`).join("")}</datalist></div>
    <button class="btn wide" type="submit" id="matchBtn">Find my creator pool ✨</button>`;
  $$("#brief .chip").forEach((c) => c.addEventListener("click", () => {
    const arr = b[c.dataset.k];
    const i = arr.indexOf(c.dataset.v);
    i >= 0 ? arr.splice(i, 1) : arr.push(c.dataset.v);
    c.classList.toggle("on");
  }));
  $$("#brief [data-seg]").forEach((btn) => btn.addEventListener("click", () => {
    b[btn.dataset.seg] = btn.dataset.v;
    $$(`#brief [data-seg="${btn.dataset.seg}"]`).forEach((x) => x.classList.toggle("on", x === btn));
  }));
  $$("#brief [data-in]").forEach((inp) => inp.addEventListener("input", () => (b[inp.dataset.in] = inp.value)));
  $("#budget").addEventListener("input", (e) => { b.budget = fromSlider(+e.target.value); $("#budgetVal").textContent = fmtINR(b.budget); });
  $("#count").addEventListener("input", (e) => { b.count = +e.target.value; $("#countVal").textContent = b.count; });
  $("#minEr").addEventListener("input", (e) => { b.min_er = +e.target.value; $("#erVal").textContent = b.min_er + "%"; });
}

async function runMatch() {
  const btn = $("#matchBtn");
  btn.disabled = true;
  btn.textContent = "Scoring every creator…";
  try {
    Studio.result = await api("/api/match", { brief: Studio.brief });
    renderResults(Studio.result);
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast("Matching failed: " + e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = "Find my creator pool ✨";
  }
}

const SCORE_BARS = [["s_relevance", "fit"], ["s_location", "place"], ["s_audience", "age"], ["s_language", "lang"], ["s_performance", "perf."], ["s_value", "value"]];

function pickHTML(c, i) {
  return `<article class="pick reveal" style="animation-delay:${i * 40}ms">
    <div class="fit" style="--p:${c.fit};--c:${nc(c.niche)}">${Math.round(c.fit)}<small>fit</small></div>
    <div>
      <div class="nm">${esc(c.name)} <span class="hd">${c.handle ? "@" + esc(c.handle) : ""} · ${PLAT[c.primary_platform] || ""}</span></div>
      <div class="hd">${[c.city, c.age ? c.age + " yrs" : null, fmtN(c.followers) + " followers", c.segment_name].filter(Boolean).map(esc).join(" · ")}</div>
      <ul>${(c.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      <div class="bars">${SCORE_BARS.map(([k, l]) => `<div>${l}<i style="--v:${(c[k] ?? 0).toFixed(2)}"></i></div>`).join("")}</div>
    </div>
    <div class="cost"><b>${fmtINR(c.cost)}</b><span>~${fmtN(c.est_views)} views</span></div>
  </article>`;
}

function renderResults(res) {
  const s = res.summary;
  const b = Studio.brief;
  const used = s.budget ? Math.round((s.spent / s.budget) * 100) : 0;
  const alt = (c) => `<div class="alt"><span><b>${esc(c.name)}</b> · ${esc(c.city || "")} · fit ${Math.round(c.fit)}</span><span class="muted">${fmtINR(c.cost)} — ${esc(c.why_not || "")}</span></div>`;
  const defName = [b.brand, b.product].filter(Boolean).join(" — ") || "New campaign";
  $("#results").innerHTML = `
    <div class="pool-head glass reveal">
      <div><p class="eyebrow" style="margin:0 0 4px">Your pool${b.brand ? " for " + esc(b.brand) : ""}</p>
        <h3>${s.creators} creators · ${fmtN(s.est_views)} estimated views</h3></div>
      <div class="kpis">
        <div class="kpi gauge"><div class="ring" style="--p:${used}"></div><div><b>${fmtINR(s.spent)}</b><span>of ${fmtINR(s.budget)} (${used}%)</span></div></div>
        <div class="kpi"><b>${s.blended_cpv != null ? "₹" + s.blended_cpv.toFixed(2) : "—"}</b><span>blended ₹ per view</span></div>
        <div class="kpi"><b>${s.avg_er != null ? s.avg_er.toFixed(1) + "%" : "—"}</b><span>average engagement</span></div>
        <div class="kpi"><b>${s.avg_fit ?? "—"}</b><span>average fit score</span></div>
      </div>
      <div class="pills">${Object.entries(s.cities).map(([c, n]) => `<span>${esc(c)} · ${n}</span>`).join("")}</div>
      <div class="save-row">
        <input type="text" id="cName" value="${esc(defName)}" aria-label="Campaign name" />
        <button class="btn" id="saveCampaign" ${res.pool.length ? "" : "disabled"}>Save as campaign →</button>
      </div>
      <p class="muted small">Creators are saved as <b>shortlisted</b>. You're billed only for creators who confirm.</p>
    </div>
    ${res.pool.map(pickHTML).join("") || '<div class="glass" style="padding:20px">No creators fit this brief — loosen the filters or raise the budget.</div>'}
    ${res.alternates.length ? `<details class="more"><summary>Next best (${res.alternates.length}) — and why they weren't picked</summary>${res.alternates.map(alt).join("")}</details>` : ""}
    ${res.conflicts.length ? `<details class="more"><summary>Excluded for competitor conflicts (${res.conflicts.length})</summary>${res.conflicts.map((c) => `<div class="alt"><span><b>${esc(c.name)}</b></span><span class="muted">${esc(c.excluded)}</span></div>`).join("")}</details>` : ""}`;
  $("#saveCampaign").addEventListener("click", saveCampaign);
}

async function saveCampaign() {
  const name = $("#cName").value.trim();
  if (name.length < 2) return toast("Give the campaign a name", "bad");
  const btn = $("#saveCampaign");
  btn.disabled = true;
  try {
    const { id } = await api("/api/campaigns", { name, brief: Studio.brief, creators: Studio.result.pool });
    toast("Campaign saved");
    location.hash = `#/campaigns/${id}`;
  } catch (e) {
    toast(e.message, "bad");
    btn.disabled = false;
  }
}

/* ============================================================== detail */
const Cd = { id: null, data: null, tab: "pipeline", chart: null };

async function mountCampaign(view, id) {
  Cd.id = id;
  Cd.tab = Cd.tab || "pipeline";
  view.innerHTML = '<div class="loading">Loading…</div>';
  await reloadCampaign();
}

async function reloadCampaign() {
  Cd.data = await api(`/api/campaigns/${Cd.id}`);
  renderCampaign();
}

function renderCampaign() {
  const c = Cd.data, k = c.kpis;
  const editable = c.status === "draft" || c.status === "active";
  const actions = {
    draft: `<button class="btn sm" data-act="launch">🚀 Launch campaign</button><button class="btn ghost sm" data-act="cancel">Cancel</button>`,
    active: `${c.unbilled ? `<button class="btn ghost sm" data-act="bill">Bill ${c.unbilled} new confirmed</button>` : ""}<button class="btn sm" data-act="complete">✓ Mark completed</button><button class="btn ghost sm" data-act="cancel">Cancel</button>`,
  }[c.status] || "";
  const spendPct = c.budget ? Math.min(100, Math.round((k.committed_spend / c.budget) * 100)) : 0;
  $("#view").innerHTML = `
    <header class="page-head">
      <div><p class="eyebrow"><a class="linkish" href="#/campaigns">← Campaigns</a></p>
        <h1>${esc(c.name)} <span class="pill ${c.status}">${STATUS_PILL[c.status]}</span></h1>
        <p class="muted">${esc([c.brand, c.product].filter(Boolean).join(" · "))} · ${esc(c.objective || "")} · ${esc(c.deliverable || "")}
          ${c.launched_at ? " · launched " + fmtDate(c.launched_at) : ""}</p></div>
      <div class="head-actions">${editable ? `<button class="btn ghost sm" id="addMore">+ Add creators</button>` : ""}${actions}</div>
    </header>
    ${c.status === "draft" ? `<div class="notice glass">📝 <b>Draft.</b> Reach out to creators, move them along the board, then <b>Launch</b>. On launch you're invoiced
      ₹${c.fee_per_creator} + GST for each creator already <b>confirmed</b>; creators confirmed later are billed separately. Shortlisted-only creators are free.</div>` : ""}
    <div class="kpi-row">
      <div class="kpi glass"><b>${k.committed}<small>/${k.creators}</small></b><span>creators confirmed</span></div>
      <div class="kpi glass"><b>${fmtINR(k.committed_spend)}</b><span>committed of ${fmtINR(c.budget)} (${spendPct}%)</span><div class="meter"><i style="width:${spendPct}%"></i></div></div>
      <div class="kpi glass"><b>${k.live}</b><span>posts live</span></div>
      <div class="kpi glass"><b>${fmtN(k.views)}</b><span>views${k.est_views ? ` · plan ${fmtN(k.est_views)}` : ""}</span></div>
      <div class="kpi glass"><b>${k.er != null ? k.er.toFixed(1) + "%" : "—"}</b><span>engagement rate</span></div>
      <div class="kpi glass"><b>${k.actual_cpv != null ? "₹" + k.actual_cpv.toFixed(2) : "—"}</b><span>₹ / view${k.est_cpv != null ? ` · plan ₹${k.est_cpv.toFixed(2)}` : ""}</span></div>
    </div>
    <div class="seg-ctl tabs" id="cdTabs">
      ${[["pipeline", "Pipeline"], ["performance", "Performance"], ["billing", "Billing"], ["activity", "Activity"], ["brief", "Brief"]]
        .map(([t, l]) => `<button data-t="${t}" class="${Cd.tab === t ? "on" : ""}">${l}</button>`).join("")}
    </div>
    <section id="cdBody"></section>`;
  $$("#cdTabs button").forEach((b) => b.addEventListener("click", () => { Cd.tab = b.dataset.t; renderCampaign(); }));
  $$("[data-act]").forEach((b) => b.addEventListener("click", () => campaignAct(b.dataset.act)));
  const add = $("#addMore");
  if (add) add.addEventListener("click", openSuggestions);
  ({ pipeline: renderBoard, performance: renderPerformance, billing: renderCampaignBilling, activity: renderActivity, brief: renderBrief })[Cd.tab]();
}

async function campaignAct(act) {
  const c = Cd.data;
  const confirmText = {
    launch: `Launch “${c.name}”?\n\n${c.kpis.committed} confirmed creator(s) will be invoiced at ₹${c.fee_per_creator} + GST each.`,
    complete: "Mark this campaign completed? Any confirmed creators not yet billed will be invoiced.",
    cancel: "Cancel this campaign? Creators already billed are not refunded automatically.",
    bill: `Invoice ${c.unbilled} newly confirmed creator(s) at ₹${c.fee_per_creator} + GST each?`,
  }[act];
  if (!confirm(confirmText)) return;
  try {
    const res = await api(`/api/campaigns/${c.id}/${act}`, {});
    if (res.invoice) toast(`Invoice ${res.invoice.number} issued — ${fmtMoney(res.invoice.total)}`);
    else toast(act === "bill" ? "Nothing new to bill" : "Done");
    await reloadCampaign();
  } catch (e) {
    toast(e.message, "bad");
  }
}

/* ---------------- pipeline board (drag & drop) */
function renderBoard() {
  const c = Cd.data;
  const editable = c.status === "draft" || c.status === "active";
  const cols = CC_STATUS.map(([key, label]) => {
    const items = c.creators.filter((x) => x.status === key);
    return `<div class="col" data-status="${key}"><h5>${label} <i>${items.length}</i></h5>
      <div class="col-body">${items.map(ccCard).join("") || '<div class="col-empty">Drop here</div>'}</div></div>`;
  }).join("");
  const dropped = c.creators.filter((x) => x.status === "dropped");
  $("#cdBody").innerHTML = `<div class="board ${editable ? "" : "readonly"}">${cols}</div>
    ${dropped.length ? `<details class="more"><summary>Dropped (${dropped.length})</summary>${dropped.map((x) => `<div class="alt"><span><b>${esc(x.name)}</b> · ${esc(x.city || "")}</span><button class="linkish" data-open="${x.id}">Open</button></div>`).join("")}</details>` : ""}
    <p class="muted small">${editable ? "Drag cards between columns, or click a card to set the fee, due date, post link and stats." : "This campaign is closed — the board is read-only."}</p>`;
  $$("#cdBody [data-open]").forEach((el) => el.addEventListener("click", () => openDrawer(+el.dataset.open)));
  if (!editable) return;
  $$(".cc-card").forEach((card) => {
    card.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", card.dataset.id); card.classList.add("dragging"); });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
  });
  $$(".col").forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("over"); });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("over");
      const id = +e.dataTransfer.getData("text/plain");
      const cc = Cd.data.creators.find((x) => x.id === id);
      if (!cc || cc.status === col.dataset.status) return;
      await setStatus(cc, col.dataset.status);
    });
  });
}

function ccCard(x) {
  const m = x.metrics || {};
  return `<div class="cc-card" draggable="true" data-id="${x.id}" data-open="${x.id}" style="--c:${nc(x.niche)}">
    <div class="cc-top"><div class="avatar xs">${esc(initials(x.name))}</div><div><b>${esc(x.name)}</b><span>${x.handle ? "@" + esc(x.handle) : ""}</span></div></div>
    <div class="cc-meta"><span>${fmtINR(fee(x))}${x.agreed_fee != null ? "" : " quoted"}</span>
      ${m.views != null ? `<span>👁 ${fmtN(m.views)}</span>` : x.due_date ? `<span>due ${fmtDate(x.due_date)}</span>` : `<span>${esc(x.city || "")}</span>`}</div>
    ${x.billed ? '<div class="billed" title="Platform fee invoiced for this creator">✓ fee billed</div>' : ""}
  </div>`;
}

async function setStatus(cc, status) {
  try {
    await apiPatch(`/api/campaign-creators/${cc.id}`, { status });
    toast(`${cc.name} → ${CC_LABEL[status]}`);
    await reloadCampaign();
  } catch (e) {
    toast(e.message, "bad");
  }
}

/* ---------------- drawer: one creator in the campaign */
async function openDrawer(ccId) {
  const x = Cd.data.creators.find((c) => c.id === ccId);
  if (!x) return;
  const editable = Cd.data.status === "draft" || Cd.data.status === "active";
  const history = await api(`/api/campaign-creators/${ccId}/metrics`);
  const m = x.metrics || {};
  const isYT = /youtu\.?be/.test(x.post_url || "");
  const dis = editable ? "" : "disabled";
  $("#drawer").innerHTML = `
    <button class="close linkish" id="dClose">✕</button>
    <div class="card-top"><div class="avatar" style="--c:${nc(x.niche)}">${esc(initials(x.name))}</div>
      <div><div class="nm">${esc(x.name)}</div><div class="hd">${x.handle ? "@" + esc(x.handle) : ""} · ${PLAT[x.platform] || ""}
      ${x.profile_url ? ` · <a class="link" href="${esc(x.profile_url)}" target="_blank" rel="noopener">profile ↗</a>` : ""}</div></div></div>
    <p class="muted">${[x.city, x.niche, fmtN(x.followers) + " followers", x.er != null ? x.er.toFixed(1) + "% ER" : null, x.fit != null ? "fit " + Math.round(x.fit) : null].filter(Boolean).map(esc).join(" · ")}</p>
    ${(x.reasons || []).length ? `<ul class="reasons">${x.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    <form id="ccForm" class="d-form">
      <div class="field"><span class="lbl">Status</span><select name="status" ${dis}>${[...CC_STATUS, ["dropped", "Dropped"]].map(([k, l]) => `<option value="${k}" ${k === x.status ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="row2">
        <div class="field"><label>Agreed fee (₹)</label><input type="number" min="0" step="500" name="agreed_fee" value="${x.agreed_fee ?? ""}" placeholder="quoted ${x.quoted_fee ?? "—"}" ${dis}></div>
        <div class="field"><label>Content due</label><input type="date" name="due_date" value="${esc(x.due_date || "")}" ${dis}></div>
      </div>
      <div class="field"><label>Post link</label><input type="text" name="post_url" value="${esc(x.post_url || "")}" placeholder="https://www.instagram.com/reel/… or YouTube link" ${dis}></div>
      <div class="field"><label>Notes (internal)</label><textarea name="notes" rows="3" ${dis}>${esc(x.notes || "")}</textarea></div>
      ${editable ? '<button class="btn sm" type="submit">Save</button>' : ""}
    </form>
    <h4 class="d-h">Post performance</h4>
    <div class="kpis">
      <div class="kpi"><b>${fmtN(m.views)}</b><span>views</span></div>
      <div class="kpi"><b>${fmtN((m.likes || 0) + (m.comments || 0) + (m.shares || 0) + (m.saves || 0))}</b><span>engagements</span></div>
      <div class="kpi"><b>${m.views && fee(x) ? "₹" + (fee(x) / m.views).toFixed(2) : "—"}</b><span>₹ / view</span></div>
    </div>
    ${editable ? `<form id="mForm" class="d-form metrics">
      <div class="row5">${["views", "likes", "comments", "shares", "saves"].map((f) => `<div class="field"><label>${f}</label><input type="number" min="0" name="${f}"></div>`).join("")}</div>
      <div class="row-actions"><button class="btn ghost sm" type="submit">Record stats</button>
      ${isYT ? '<button class="btn ghost sm" type="button" id="ytFetch">Fetch from YouTube</button>' : '<span class="muted small">YouTube links can be fetched automatically.</span>'}</div>
    </form>` : ""}
    ${history.length ? `<table class="tbl"><tr><th>When</th><th>Views</th><th>Likes</th><th>Comments</th><th>Source</th></tr>
      ${history.slice().reverse().map((h) => `<tr><td>${fmtDate(h.recorded_at)}</td><td>${fmtN(h.views)}</td><td>${fmtN(h.likes)}</td><td>${fmtN(h.comments)}</td><td>${h.source === "youtube_api" ? "YouTube API" : "manual"}</td></tr>`).join("")}</table>` : ""}`;
  $("#drawer").hidden = false;
  $("#scrim").hidden = false;
  $("#dClose").addEventListener("click", closeDrawer);
  if (!editable) return;
  $("#ccForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target).entries());
    const body = { status: f.status, due_date: f.due_date || null, post_url: f.post_url || null, notes: f.notes || null };
    if (f.agreed_fee !== "") body.agreed_fee = +f.agreed_fee;
    try { await apiPatch(`/api/campaign-creators/${ccId}`, body); toast("Saved"); await reloadCampaign(); openDrawer(ccId); } catch (err) { toast(err.message, "bad"); }
  });
  $("#mForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries([...new FormData(e.target).entries()].filter(([, v]) => v !== "").map(([k, v]) => [k, +v]));
    if (!Object.keys(f).length) return toast("Enter at least one number", "bad");
    try { await api(`/api/campaign-creators/${ccId}/metrics`, f); toast("Stats recorded"); await reloadCampaign(); openDrawer(ccId); } catch (err) { toast(err.message, "bad"); }
  });
  const yt = $("#ytFetch");
  if (yt) yt.addEventListener("click", async () => {
    try { const r = await api(`/api/campaign-creators/${ccId}/fetch`, {}); toast(`Fetched ${fmtN(r.views)} views`); await reloadCampaign(); openDrawer(ccId); } catch (err) { toast(err.message, "bad"); }
  });
}

function closeDrawer() {
  $("#drawer").hidden = true;
  $("#scrim").hidden = true;
}

/* ---------------- add creators modal */
async function openSuggestions() {
  $("#modalBody").innerHTML = '<div class="loading">Finding more creators for this brief…</div>';
  $("#modal").hidden = false;
  $("#scrim").hidden = false;
  try {
    const { suggestions } = await api(`/api/campaigns/${Cd.id}/suggestions`);
    const chosen = new Set();
    $("#modalBody").innerHTML = `<button class="close linkish" id="mClose">✕</button>
      <h3>Add creators</h3><p class="muted">Next-best matches for this campaign's brief (not already in the campaign).</p>
      <div class="sugg">${suggestions.map((s, i) => `<label class="sugg-row"><input type="checkbox" data-i="${i}">
        <div class="fit sm" style="--p:${s.fit};--c:${nc(s.niche)}">${Math.round(s.fit)}</div>
        <div><b>${esc(s.name)}</b> <span class="muted">${s.handle ? "@" + esc(s.handle) : ""} · ${esc(s.city || "")} · ${esc(s.niche)}</span>
        <div class="muted small">${esc((s.reasons || []).slice(0, 3).join(" · "))}</div></div><b>${fmtINR(s.cost)}</b></label>`).join("") || '<p class="muted">No more matches.</p>'}</div>
      <div class="row-actions"><button class="btn" id="addChosen" disabled>Add selected</button></div>`;
    $("#mClose").addEventListener("click", closeModal);
    $$(".sugg input").forEach((cb) => cb.addEventListener("change", () => {
      cb.checked ? chosen.add(+cb.dataset.i) : chosen.delete(+cb.dataset.i);
      $("#addChosen").disabled = !chosen.size;
      $("#addChosen").textContent = chosen.size ? `Add ${chosen.size} creator${chosen.size > 1 ? "s" : ""}` : "Add selected";
    }));
    $("#addChosen").addEventListener("click", async () => {
      const r = await api(`/api/campaigns/${Cd.id}/creators`, { creators: [...chosen].map((i) => suggestions[i]) });
      toast(`Added ${r.added} creator(s) as shortlisted`);
      closeModal();
      await reloadCampaign();
    });
  } catch (e) {
    $("#modalBody").innerHTML = `<p>${esc(e.message)}</p>`;
  }
}

function closeModal() {
  $("#modal").hidden = true;
  $("#scrim").hidden = true;
}

/* ---------------- performance / billing / activity / brief tabs */
function renderPerformance() {
  const c = Cd.data;
  const live = c.creators.filter((x) => x.metrics && x.metrics.views != null).sort((a, b) => b.metrics.views - a.metrics.views);
  $("#cdBody").innerHTML = `
    <div class="chart-card glass"><div class="chart-title">Cumulative views</div><div class="chart" id="perfChart" style="height:280px"></div></div>
    <div class="glass tbl-wrap"><table class="tbl">
      <tr><th>Creator</th><th>Status</th><th>Fee</th><th>Views</th><th>Plan</th><th>Engagements</th><th>ER</th><th>₹ / view</th><th>Post</th></tr>
      ${c.creators.filter((x) => COMMITTED.has(x.status)).map((x) => {
        const m = x.metrics || {};
        const eng = (m.likes || 0) + (m.comments || 0) + (m.shares || 0) + (m.saves || 0);
        return `<tr><td><b>${esc(x.name)}</b></td><td>${CC_LABEL[x.status]}</td><td>${fmtINR(fee(x))}</td><td>${fmtN(m.views)}</td>
          <td class="muted">${fmtN(x.est_views)}</td><td>${m.views != null ? fmtN(eng) : "—"}</td><td>${m.views ? (100 * eng / m.views).toFixed(1) + "%" : "—"}</td>
          <td>${m.views && fee(x) ? "₹" + (fee(x) / m.views).toFixed(2) : "—"}</td>
          <td>${x.post_url ? `<a class="link" href="${esc(x.post_url)}" target="_blank" rel="noopener">open ↗</a>` : "—"}</td></tr>`;
      }).join("") || '<tr><td colspan="9" class="muted">No confirmed creators yet.</td></tr>'}
    </table></div>`;
  if (!window.echarts) return;
  const ch = echarts.init($("#perfChart"));
  const txt = "#b3a9cf";
  ch.setOption({
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    tooltip: { trigger: "axis", valueFormatter: (v) => fmtN(v) },
    xAxis: { type: "category", data: c.timeline.map((t) => t.day), axisLabel: { color: txt } },
    yAxis: { type: "value", axisLabel: { color: txt, formatter: (v) => fmtN(v) }, splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } } },
    series: [{ type: "line", smooth: true, data: c.timeline.map((t) => t.views), symbolSize: 8,
      lineStyle: { width: 3, color: "#ff3d8b" }, itemStyle: { color: "#ffb020" },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(255,61,139,.35)" }, { offset: 1, color: "rgba(255,61,139,0)" }]) } }],
    graphic: c.timeline.length ? [] : [{ type: "text", left: "center", top: "middle", style: { text: "Record post stats to see the curve", fill: txt, fontSize: 14 } }],
  });
}

function renderCampaignBilling() {
  const c = Cd.data;
  $("#cdBody").innerHTML = `
    <div class="notice glass">Service fee: <b>${fmtMoney(c.fee_per_creator)}</b> per confirmed creator + GST.
      ${c.unbilled ? `<b>${c.unbilled}</b> confirmed creator(s) not yet billed.` : "All confirmed creators are billed."}</div>
    <div class="glass tbl-wrap"><table class="tbl"><tr><th>Invoice</th><th>Issued</th><th>Total</th><th>Status</th><th></th></tr>
      ${c.invoices.map((i) => `<tr><td><b>${esc(i.number)}</b></td><td>${fmtDate(i.issued_at)}</td><td>${fmtMoney(i.total)}</td>
        <td><span class="pill ${i.status}">${i.status}</span></td><td><a class="link" href="/invoice/${i.id}" target="_blank">View ↗</a></td></tr>`).join("")
        || '<tr><td colspan="5" class="muted">No invoices yet — they are issued when the campaign launches.</td></tr>'}
    </table></div>`;
}

function renderActivity() {
  $("#cdBody").innerHTML = `<ul class="feed glass">${Cd.data.activity.map((a) => `<li><span class="muted">${ago(a.at)}</span>${esc(a.text)}</li>`).join("") || "<li>No activity yet.</li>"}</ul>`;
}

function renderBrief() {
  const b = Cd.data.brief || {};
  const row = (k, v) => (v && (!Array.isArray(v) || v.length) ? `<div class="b-row"><span>${k}</span><b>${esc(Array.isArray(v) ? v.join(", ") : v)}</b></div>` : "");
  $("#cdBody").innerHTML = `<div class="glass brief-view">
    ${row("Brand", b.brand)}${row("Product", b.product)}${row("Niches", b.niches)}${row("Keywords", b.keywords)}
    ${row("Cities", b.cities)}${row("Regions", b.regions)}${row("Creator age", b.age_bands)}${row("Languages", b.languages)}
    ${row("Deliverable", b.deliverable)}${row("Objective", b.objective)}${row("Budget", b.budget ? fmtINR(b.budget) : "")}
    ${row("Creators wanted", b.count ? String(b.count) : "")}${row("Excluded brands", b.exclude_brands)}</div>`;
}
