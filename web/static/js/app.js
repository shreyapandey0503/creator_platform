/* App shell: session, sidebar, hash router, dashboard, billing, settings. */
"use strict";

const App = { me: null };

const ROUTES = [
  [/^#\/dashboard$/, "dashboard", (v) => mountDashboard(v)],
  [/^#\/creators$/, "creators", (v) => mountCreators(v)],
  [/^#\/campaigns$/, "campaigns", (v) => mountCampaigns(v)],
  [/^#\/campaigns\/new$/, "campaigns", (v) => mountStudio(v)],
  [/^#\/campaigns\/(\d+)$/, "campaigns", (v, m) => mountCampaign(v, +m[1])],
  [/^#\/billing$/, "billing", (v) => mountBilling(v)],
  [/^#\/settings$/, "settings", (v) => mountSettings(v)],
];

async function route() {
  const hash = location.hash || "#/dashboard";
  const hit = ROUTES.map(([re, nav, fn]) => [hash.match(re), nav, fn]).find(([m]) => m);
  if (!hit) { location.hash = "#/dashboard"; return; }
  const [m, nav, fn] = hit;
  $$(".side-nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === nav));
  document.body.classList.remove("menu-open");
  closeDrawer();
  closeModal();
  const view = $("#view");
  view.innerHTML = "";
  view.scrollTop = 0;
  window.scrollTo(0, 0);
  try {
    await fn(view, m);
  } catch (e) {
    view.innerHTML = `<div class="empty glass"><p>Something went wrong: ${esc(e.message)}</p></div>`;
  }
}

/* ============================================================== dashboard */
function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

async function mountDashboard(view) {
  const d = await api("/api/dashboard");
  const first = d.user.name.split(" ")[0];
  const steps = [
    [d.library > 0, "Upload your creators", "#/creators", "Clean and cluster your creator sheet"],
    [d.campaigns.total > 0, "Create a campaign", "#/campaigns/new", "Match a brief to your library"],
    [d.campaigns.active + d.campaigns.completed > 0, "Launch it", d.recent[0] ? `#/campaigns/${d.recent[0].id}` : "#/campaigns", "Confirm creators and go live"],
    [d.live_posts > 0, "Track results", d.recent[0] ? `#/campaigns/${d.recent[0].id}` : "#/campaigns", "Add post links and stats"],
  ];
  const done = steps.filter((s) => s[0]).length;
  view.innerHTML = `
    <header class="page-head">
      <div><p class="eyebrow">${esc(d.user.org)}</p><h1>${greeting()}, ${esc(first)} <span class="hi">नमस्ते</span></h1></div>
      <div class="head-actions"><a class="btn ghost sm" href="#/creators">⇪ Upload creators</a><a class="btn sm" href="#/campaigns/new">+ New campaign</a></div>
    </header>
    ${done < steps.length ? `<section class="onboard glass">
      <div><h3>Get set up</h3><p class="muted">${done} of ${steps.length} done</p><div class="meter"><i style="width:${(done / steps.length) * 100}%"></i></div></div>
      <ol>${steps.map(([ok, t, href, sub], i) => `<li class="${ok ? "ok" : ""}"><a href="${href}"><b>${ok ? "✓" : i + 1}</b><span>${t}<small>${sub}</small></span></a></li>`).join("")}</ol>
    </section>` : ""}
    <div class="kpi-row">
      <a class="kpi glass" href="#/creators"><b>${d.library.toLocaleString()}</b><span>creators in your library</span></a>
      <a class="kpi glass" href="#/campaigns"><b>${d.campaigns.active}</b><span>active campaigns · ${d.campaigns.draft} draft</span></a>
      <div class="kpi glass"><b>${d.live_posts}</b><span>posts live</span></div>
      <div class="kpi glass"><b>${fmtN(d.views)}</b><span>views tracked</span></div>
      <div class="kpi glass"><b>${fmtINR(d.committed_spend)}</b><span>creator spend committed</span></div>
      <a class="kpi glass" href="#/billing"><b>${fmtMoney(d.outstanding)}</b><span>invoices outstanding</span></a>
    </div>
    <div class="dash-grid">
      <section><div class="grid-head"><h3 class="sub-h">Recent campaigns</h3><a class="link" href="#/campaigns">All campaigns →</a></div>
        <div class="c-list">${d.recent.map(campaignCard).join("") || `<div class="empty glass"><p>No campaigns yet.</p><a class="btn sm" href="#/campaigns/new">Create one</a></div>`}</div></section>
      <section><h3 class="sub-h">Activity</h3>
        <ul class="feed glass">${d.activity.map((a) => `<li><span class="muted">${ago(a.at)}</span>${a.campaign_id ? `<a href="#/campaigns/${a.campaign_id}">${esc(a.text)}</a>` : esc(a.text)}</li>`).join("") || "<li>No activity yet.</li>"}</ul></section>
    </div>`;
}

/* ============================================================== billing */
async function mountBilling(view) {
  const b = await api("/api/billing");
  view.innerHTML = `
    <header class="page-head"><div><p class="eyebrow">Billing</p><h1>Invoices &amp; fees</h1></div></header>
    <div class="fee-card glass">
      <div><span class="fee-amt">${fmtMoney(b.fee_per_creator)}</span><span class="muted"> per confirmed creator, per campaign · + ${Math.round(b.gst_rate * 100)}% GST</span></div>
      <p class="muted">You're invoiced when a campaign launches (for creators already confirmed) and again for creators confirmed later.
        Shortlisted-only creators are free. Creator fees are paid by you directly to creators.</p>
      ${b.test_mode ? '<span class="pill draft">Payments in test mode</span>' : ""}
    </div>
    <div class="kpi-row">
      <div class="kpi glass"><b>${fmtMoney(b.outstanding)}</b><span>outstanding${b.overdue ? ` · ${fmtMoney(b.overdue)} overdue` : ""}</span></div>
      <div class="kpi glass"><b>${fmtMoney(b.paid)}</b><span>paid to date</span></div>
      <div class="kpi glass"><b>${b.creators_billed}</b><span>creators billed</span></div>
      <div class="kpi glass"><b>${b.invoices.length}</b><span>invoices</span></div>
    </div>
    ${b.unbilled.length ? `<div class="notice glass"><b>Not yet billed:</b> ${b.unbilled.map((u) => `<a class="link" href="#/campaigns/${u.campaign_id}">${esc(u.campaign_name)}</a> (${u.creators} creator${u.creators > 1 ? "s" : ""})`).join(", ")} — they'll be invoiced when you click “Bill” on the campaign or complete it.</div>` : ""}
    <div class="glass tbl-wrap"><table class="tbl">
      <tr><th>Invoice</th><th>Campaign</th><th>Creators</th><th>Issued</th><th>Due</th><th>Total</th><th>Status</th><th></th></tr>
      ${b.invoices.map((i) => `<tr>
        <td><b>${esc(i.number)}</b></td><td>${i.campaign_id ? `<a class="link" href="#/campaigns/${i.campaign_id}">${esc(i.campaign_name)}</a>` : "—"}</td>
        <td>${i.creators ?? "—"}</td><td>${fmtDate(i.issued_at)}</td><td>${fmtDate(i.due_at)}</td><td><b>${fmtMoney(i.total)}</b></td>
        <td><span class="pill ${i.status}">${i.status === "issued" ? "due" : i.status}</span></td>
        <td class="row-actions"><a class="link" href="/invoice/${i.id}" target="_blank">View ↗</a>
          ${i.status === "issued" ? `<button class="btn sm" data-pay="${i.id}">Pay ${fmtMoney(i.total)}</button>` : ""}</td></tr>`).join("")
        || '<tr><td colspan="8" class="muted">No invoices yet. They appear when you launch a campaign with confirmed creators.</td></tr>'}
    </table></div>`;
  $$("[data-pay]").forEach((btn) => btn.addEventListener("click", async () => {
    if (!confirm("Pay this invoice?\n\nTEST MODE — no real money moves. A payment gateway (e.g. Razorpay) plugs in here.")) return;
    btn.disabled = true;
    try { const r = await api(`/api/invoices/${btn.dataset.pay}/pay`, {}); toast(`Paid · ref ${r.reference || ""}`); mountBilling(view); }
    catch (e) { toast(e.message, "bad"); btn.disabled = false; }
  }));
}

/* ============================================================== settings */
async function mountSettings(view) {
  const s = await api("/api/settings");
  const admin = ["owner", "admin"].includes(s.me.role);
  const opt = (items, sel) => `<option value="">—</option>` + items.map((x) => `<option ${x === sel ? "selected" : ""}>${esc(x)}</option>`).join("");
  const o = s.org;
  view.innerHTML = `
    <header class="page-head"><div><p class="eyebrow">Settings</p><h1>Workspace settings</h1></div></header>
    <div class="settings-grid">
      <form class="glass s-card" id="profileForm"><h3>Your profile</h3>
        <div class="field"><label>Full name</label><input type="text" name="name" value="${esc(s.me.name)}" required minlength="2"></div>
        <div class="field"><label>Role</label><select name="job_title" required>${opt(s.options.job_titles, s.me.job_title)}</select></div>
        <div class="field"><label>Email</label><input type="text" value="${esc(s.me.email)}" disabled></div>
        <button class="btn sm">Save profile</button></form>

      <form class="glass s-card" id="companyForm"><h3>Company &amp; billing details</h3>
        <div class="field"><label>Company name</label><input type="text" name="name" value="${esc(o.name)}" required minlength="2" ${admin ? "" : "disabled"}></div>
        <div class="row2"><div class="field"><label>Industry</label><select name="industry" ${admin ? "" : "disabled"}>${opt(s.options.industries, o.industry)}</select></div>
          <div class="field"><label>Company size</label><select name="size" ${admin ? "" : "disabled"}>${opt(s.options.company_sizes, o.size)}</select></div></div>
        <div class="row2"><div class="field"><label>GSTIN</label><input type="text" name="gstin" maxlength="15" value="${esc(o.gstin || "")}" placeholder="27ABCDE1234F1Z5" ${admin ? "" : "disabled"}></div>
          <div class="field"><label>Billing email</label><input type="text" name="billing_email" value="${esc(o.billing_email || "")}" ${admin ? "" : "disabled"}></div></div>
        <div class="field"><label>Billing address</label><input type="text" name="address" value="${esc(o.address || "")}" ${admin ? "" : "disabled"}></div>
        ${admin ? '<button class="btn sm">Save company</button>' : '<p class="muted small">Only admins can edit company details.</p>'}</form>

      <section class="glass s-card"><h3>Team</h3>
        <table class="tbl"><tr><th>Name</th><th>Role</th><th>Access</th><th>Last login</th></tr>
          ${s.members.map((m) => `<tr><td><b>${esc(m.name)}</b><div class="muted small">${esc(m.email)}</div></td><td>${esc(m.job_title || "")}</td><td>${esc(m.role)}</td><td>${m.last_login ? ago(m.last_login) : "never"}</td></tr>`).join("")}
        </table>
        ${admin ? `<form id="inviteForm" class="invite"><h4>Add a teammate</h4>
          <div class="row2"><div class="field"><label>Name</label><input type="text" name="name" required minlength="2"></div>
            <div class="field"><label>Email</label><input type="email" name="email" required></div></div>
          <div class="row2"><div class="field"><label>Role</label><select name="job_title" required>${opt(s.options.job_titles)}</select></div>
            <div class="field"><label>Access</label><select name="role"><option value="member">Member</option><option value="admin">Admin</option></select></div></div>
          <button class="btn ghost sm">Add teammate</button><p class="muted small" id="inviteOut"></p></form>` : ""}
      </section>

      <form class="glass s-card" id="pwForm"><h3>Password</h3>
        <div class="field"><label>Current password</label><input type="password" name="current" required autocomplete="current-password"></div>
        <div class="field"><label>New password (8+ characters)</label><input type="password" name="new" required minlength="8" autocomplete="new-password"></div>
        <button class="btn ghost sm">Change password</button></form>

      <section class="glass s-card"><h3>Plan</h3>
        <p><span class="fee-amt">${fmtMoney(s.fee_per_creator)}</span> per confirmed creator, per campaign + ${Math.round(s.gst_rate * 100)}% GST.</p>
        <p class="muted">Unlimited uploads, teammates and campaigns. <a class="link" href="#/billing">View invoices →</a></p></section>
    </div>`;
  const bind = (id, fn) => { const f = $(id); if (f) f.addEventListener("submit", async (e) => { e.preventDefault(); try { await fn(Object.fromEntries(new FormData(e.target).entries()), e.target); } catch (err) { toast(err.message, "bad"); } }); };
  bind("#profileForm", async (f) => { await apiPatch("/api/settings/profile", f); toast("Profile saved"); await loadMe(); });
  bind("#companyForm", async (f) => { await apiPatch("/api/settings/company", f); toast("Company saved"); await loadMe(); });
  bind("#pwForm", async (f, form) => { await api("/api/settings/password", f); form.reset(); toast("Password changed"); });
  bind("#inviteForm", async (f, form) => {
    const r = await api("/api/settings/members", f);
    form.reset();
    $("#inviteOut").innerHTML = `Added. Share this one-time password with them securely: <code>${esc(r.temporary_password)}</code> — they can change it in Settings.`;
    toast("Teammate added");
  });
}

/* ============================================================== boot */
async function loadMe() {
  App.me = await api("/api/auth/me");
  $("#meName").textContent = App.me.name;
  $("#meOrg").textContent = `${App.me.org_name}${App.me.job_title ? " · " + App.me.job_title : ""}`;
  $("#meAvatar").textContent = initials(App.me.name);
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadMe();
  $("#logout").addEventListener("click", async () => { await api("/api/auth/logout", {}); location.href = "/"; });
  $("#menuBtn").addEventListener("click", () => document.body.classList.toggle("menu-open"));
  $("#scrim").addEventListener("click", () => { closeDrawer(); closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); closeModal(); } });
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => $$(".chart").forEach((c) => window.echarts && echarts.getInstanceByDom(c)?.resize()));
  route();
});
