/* Landing page: wallpaper, pricing calculator, scroll state. */
"use strict";

document.addEventListener("DOMContentLoaded", async () => {
  buildWall($("#wall"));
  let FEE = 499, GST = 0.18;
  const calc = () => {
    const n = +$("#calcRange").value;
    $("#calcN").textContent = n;
    $("#calcFee").textContent = fmtMoney(n * FEE);
    $("#calcTot").textContent = "= " + fmtMoney(Math.round(n * FEE * (1 + GST)));
  };
  $("#calcRange").addEventListener("input", calc);
  calc();
  try {
    const p = await api("/api/pricing");
    FEE = p.fee_per_creator; GST = p.gst_rate;
    $("#feeAmt").textContent = fmtMoney(FEE);
    calc();
  } catch { /* keep defaults */ }
  window.addEventListener("scroll", () => document.body.classList.toggle("scrolled", window.scrollY > window.innerHeight * 0.5), { passive: true });
});
