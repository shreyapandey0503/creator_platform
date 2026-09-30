/* Creator Atlas — shared helpers: DOM, API, formatting, niche palette, the live reel wallpaper. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const NICHE = {
  "Food": ["#FF8A3D", "🍛"], "Fashion": ["#FF3D8B", "👗"], "Beauty": ["#F472B6", "💄"], "Travel": ["#16C6B7", "🧳"],
  "Fitness & Health": ["#9BD14B", "🧘"], "Tech": ["#7C5CFF", "📱"], "Finance & Business": ["#FFB020", "📈"],
  "Comedy": ["#FFD23F", "😂"], "Education": ["#4FC3F7", "📚"], "Family & Parenting": ["#F9A8D4", "🧸"],
  "Gaming": ["#A78BFA", "🎮"], "Lifestyle": ["#FDBA74", "☕"], "Music": ["#60A5FA", "🎤"], "Dance": ["#E879F9", "💃"],
  "Auto": ["#94A3B8", "🏍️"], "Home & Garden": ["#86EFAC", "🪴"], "Entertainment": ["#FB7185", "🎬"],
  "Film & TV": ["#F87171", "🎬"], "Sports": ["#34D399", "🏏"], "Celebrity": ["#FDE047", "⭐"],
  "News & Politics": ["#CBD5E1", "📰"], "Uncategorised": ["#8B84A8", "❔"],
};
const nc = (n) => (NICHE[n] || ["#C4B5FD", "✦"])[0];
const ne = (n) => (NICHE[n] || ["#C4B5FD", "✦"])[1];
const PLAT = { instagram: "📸 Instagram", youtube: "▶ YouTube", threads: "🧵 Threads", tiktok: "🎵 TikTok" };

const fmtN = (x) => {
  if (x == null || isNaN(x)) return "—";
  x = +x;
  if (x >= 1e7) return (x / 1e6).toFixed(0) + "M";
  if (x >= 1e6) return (x / 1e6).toFixed(1) + "M";
  if (x >= 1e3) return (x / 1e3).toFixed(x >= 1e5 ? 0 : 1) + "K";
  return Math.round(x).toString();
};
const fmtINR = (x) => {
  if (x == null || isNaN(x)) return "—";
  x = +x;
  if (x >= 1e7) return "₹" + (x / 1e7).toFixed(1) + "Cr";
  if (x >= 1e5) return "₹" + (x / 1e5).toFixed(x >= 1e6 ? 0 : 1) + "L";
  if (x >= 1e3) return "₹" + (x / 1e3).toFixed(x >= 1e4 ? 0 : 1) + "K";
  return "₹" + Math.round(x);
};
const fmtMoney = (x) => (x == null ? "—" : "₹" + (+x).toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 0 }));
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—");
const ago = (iso) => {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  for (const [u, n] of [["d", 86400], ["h", 3600], ["m", 60]]) if (s >= n) return Math.floor(s / n) + u + " ago";
  return "";
};
const initials = (n) => (n || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

async function api(path, body, method) {
  const opt = { method: method || (body !== undefined ? "POST" : "GET"), headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  if (r.status === 401 && !path.startsWith("/api/auth/")) { location.href = "/login"; throw new Error("Please log in"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : (data.detail?.[0]?.msg || r.statusText));
  return data;
}
const apiPatch = (path, body) => api(path, body, "PATCH");

function toast(msg, kind = "") {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg;
  t.className = "toast " + kind;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 4500);
}

/* ================================================================ live reel wallpaper */
const SCENES = [
  { bg: "linear-gradient(160deg,#ff9a3d,#c2185b)", main: "🍛", sides: ["🌶️", "🧅", "✨"], steam: 1, h: "masala.meera", cap: "Mumbai ka best vada pav? 🔥 #streetfood", likes: 48200 },
  { bg: "linear-gradient(160deg,#8d5524,#2b1a10)", main: "☕", sides: ["🍪", "🌧️", "💛"], steam: 1, h: "chai.and.chats", cap: "Cutting chai, 6am, Pune rains ☔", likes: 12900, paid: "BrewBerry" },
  { bg: "linear-gradient(160deg,#4facfe,#1e3c72)", main: "🏔️", sides: ["🏍️", "☁️", "🧭"], h: "wander.arjun", cap: "Spiti in 4 days — full route 🗺️", likes: 91300 },
  { bg: "linear-gradient(160deg,#f7971e,#ffd200)", main: "🏖️", sides: ["🌴", "🥥", "😎"], h: "goa.off.season", cap: "Goa off-season guide (save this!)", likes: 33100, paid: "StayNest" },
  { bg: "linear-gradient(160deg,#ff5f9e,#7b1fa2)", main: "💄", sides: ["✨", "🪔", "💅"], h: "glam.by.kavya", cap: "5-min Diwali glam ✨ #festive", likes: 76400, paid: "Haldi Lab" },
  { bg: "linear-gradient(160deg,#ff3d8b,#ffb020)", main: "🥻", sides: ["🌸", "👜", "✨"], h: "saree.stories", cap: "1 saree, 3 ways to drape it 🌸", likes: 58800 },
  { bg: "linear-gradient(160deg,#56ab2f,#0f3d2e)", main: "🧘", sides: ["🌿", "🌅", "🕉️"], h: "yoga.rishikesh", cap: "Morning flow by the Ganga 🌅", likes: 22700 },
  { bg: "linear-gradient(160deg,#7c5cff,#1a1045)", main: "📱", sides: ["⚡", "📸", "🔋"], h: "techwithtanvi", cap: "Is this ₹15K phone worth it?", likes: 41800, paid: "PixelPhone" },
  { bg: "linear-gradient(160deg,#11998e,#0b3d3a)", main: "📈", sides: ["💰", "🪙", "📊"], h: "paisa.simplified", cap: "SIP vs FD — explained in 60s", likes: 29400, paid: "PaisaWise" },
  { bg: "linear-gradient(160deg,#fbd72b,#f9484a)", main: "😂", sides: ["👩‍👦", "📦", "💸"], h: "ghar.ke.skits", cap: "When mummy sees the delivery bill 😭", likes: 184000 },
  { bg: "linear-gradient(160deg,#e040fb,#311b92)", main: "💃", sides: ["🥁", "🪩", "✨"], h: "garba.nights", cap: "Garba practice day 3 🥁", likes: 67300 },
  { bg: "linear-gradient(160deg,#43cea2,#185a9d)", main: "🏏", sides: ["🏟️", "🔥", "🧢"], h: "gully.cricket.club", cap: "Gully cricket rules, explained 🏏", likes: 102000 },
  { bg: "linear-gradient(160deg,#f6d365,#fda085)", main: "🧁", sides: ["🍫", "🥄", "✨"], h: "bake.with.isha", cap: "Eggless brownie, no oven needed", likes: 38900, paid: "Kesar Kitchen Co" },
  { bg: "linear-gradient(160deg,#654ea3,#0f0c29)", main: "🎮", sides: ["🎧", "🔥", "🏆"], h: "clutch.king", cap: "1v4 clutch… watch till end 🔥", likes: 88100, paid: "Voltbuds" },
  { bg: "linear-gradient(160deg,#fbc2eb,#a18cd1)", main: "🧸", sides: ["🍱", "🎒", "🌈"], h: "tiffin.tales.mom", cap: "5 tiffin ideas kids actually eat", likes: 27600 },
  { bg: "linear-gradient(160deg,#ff512f,#dd2476)", main: "🥘", sides: ["🍋", "🌶️", "🔥"], steam: 1, h: "dilli.food.walk", cap: "Chandni Chowk in ₹500 🤯", likes: 142000, paid: "SnackRiot" },
];

function phoneHTML(s) {
  const side = (s.sides || []).map((e, i) => `<span class="deco s${i + 1}">${e}</span>`).join("");
  const steam = s.steam ? '<span class="steam"></span><span class="steam b"></span>' : "";
  const floaty = Math.random() < 0.5 ? '<span class="floaty">❤️</span><span class="floaty f2">❤️</span><span class="floaty f3">💖</span>' : "";
  return `<div class="phone" style="--bg:${s.bg}">
    <div class="scene"><span class="big">${s.main}</span>${side}${steam}</div>
    <div class="bar"><i style="--dur:${6 + Math.random() * 6}s;animation-delay:-${Math.random() * 6}s"></i></div>
    <div class="top">Reels</div>
    <div class="rail"><span class="heart"><b>♥</b><em>${fmtN(s.likes)}</em></span><span><b>💬</b>${fmtN(s.likes / 38)}</span><span><b>↗</b></span></div>
    ${floaty}
    <div class="cap"><div class="who"><i></i>@${s.h}</div>${s.cap}${s.paid ? `<br><span class="paid">Paid partnership · ${s.paid}</span>` : ""}</div>
  </div>`;
}

async function buildWall(el) {
  if (!el) return;
  const cols = Math.min(12, Math.ceil((window.innerWidth * 1.5) / 194));
  let html = "";
  for (let c = 0; c < cols; c++) {
    const picks = [];
    for (let i = 0; i < 5; i++) picks.push(SCENES[(c * 5 + i * 3 + c) % SCENES.length]);
    const inner = picks.map(phoneHTML).join("");
    html += `<div class="wall-col ${c % 2 ? "down" : ""}" style="animation-duration:${50 + (c % 4) * 12}s;margin-top:${(c % 3) * -60}px">${inner}${inner}</div>`;
  }
  el.innerHTML = html;
  setInterval(() => {
    const hearts = $$(".heart em", el);
    for (let i = 0; i < 8; i++) {
      const h = hearts[Math.floor(Math.random() * hearts.length)];
      if (!h) continue;
      const cur = h.textContent;
      const n = parseFloat(cur) * (cur.endsWith("K") ? 1e3 : cur.endsWith("M") ? 1e6 : 1);
      h.textContent = fmtN(n + 100 + Math.random() * 900);
    }
  }, 1400);
  try {  // optional licensed video loops in web/static/wallpapers/
    const { videos } = await api("/api/wallpapers");
    if (videos.length) {
      $$(".phone", el).forEach((p, i) => {
        if (i % 3 !== 0) return;
        const v = document.createElement("video");
        Object.assign(v, { src: videos[i % videos.length], muted: true, loop: true, autoplay: true, playsInline: true });
        p.querySelector(".scene").replaceWith(v);
      });
    }
  } catch { /* optional */ }
}
