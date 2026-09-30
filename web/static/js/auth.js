/* Log in / sign up. */
"use strict";

function showTab(tab) {
  $$(".auth-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("#loginForm").hidden = tab !== "login";
  $("#signupForm").hidden = tab !== "signup";
  history.replaceState(null, "", "/" + tab);
  document.title = "Creator Atlas — " + (tab === "login" ? "Log in" : "Create account");
  $(tab === "login" ? "#le" : "#sn").focus();
}

async function submit(form, path) {
  const err = $(".form-err", form);
  const btn = $("button[type=submit]", form);
  err.hidden = true;
  btn.disabled = true;
  const body = Object.fromEntries(new FormData(form).entries());
  try {
    await api(path, body);
    location.href = "/app";
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  buildWall($("#wall"));
  $$(".auth-tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $$("[data-go]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); showTab(a.dataset.go); }));
  $("#loginForm").addEventListener("submit", (e) => { e.preventDefault(); submit(e.target, "/api/auth/login"); });
  $("#signupForm").addEventListener("submit", (e) => { e.preventDefault(); submit(e.target, "/api/auth/signup"); });
  const opts = await api("/api/auth/options");
  const fill = (sel, items, placeholder) => { $(sel).innerHTML = `<option value="">${placeholder}</option>` + items.map((x) => `<option>${esc(x)}</option>`).join(""); };
  fill("#sj", opts.job_titles, "Select…");
  fill("#si", opts.industries, "Select…");
  fill("#ss", opts.company_sizes, "Select…");
  showTab(location.pathname.includes("signup") ? "signup" : "login");
});
