// No build step on purpose: this is a plain static site. The API base URL is read from a <meta> tag so it's a one-line edit
// per page after you know your Render API URL (see ../SETUP.md) - no bundler, no secrets, nothing to compile.
const API_BASE = (document.querySelector('meta[name="meso-api-base"]') || {}).content || "";

// ------------------------------------------------------------------------------------------------- plan switch
const PLAN_LABELS = { monthly: "$1.99/mo", "6mo": "$8/6mo", yearly: "$10/yr" };

function selectedPlan() {
  const checked = document.querySelector('input[name="plan"]:checked');
  return checked ? checked.value : "monthly";
}

function syncPlanUI() {
  document.querySelectorAll(".plan-opt").forEach((el) => {
    el.classList.toggle("is-selected", el.querySelector("input").checked);
  });
  const btn = document.getElementById("buy-btn");
  if (btn && !btn.disabled) btn.textContent = `Subscribe for ${PLAN_LABELS[selectedPlan()]}`;
}

document.querySelectorAll('input[name="plan"]').forEach((el) => el.addEventListener("change", syncPlanUI));
syncPlanUI();

async function startCheckout(ev) {
  ev.preventDefault();
  const btn = document.getElementById("buy-btn");
  const err = document.getElementById("checkout-error");
  const email = (document.getElementById("email") || {}).value || undefined;
  const plan = selectedPlan();
  err.style.display = "none";
  btn.disabled = true;
  btn.textContent = "Opening secure checkout...";
  try {
    const res = await fetch(`${API_BASE}/v1/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...(email ? { email } : {}), plan }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // data.detail (e.g. "That plan isn't available yet...") is written by the server for a reason - show it
      // verbatim. Anything else failing here (offline, CORS, a non-JSON response) has no such message and falls
      // through to the generic text below instead - a raw "Failed to fetch" is not a reason a buyer can act on.
      const reason = new Error(data.detail || "checkout_failed");
      reason.isServerMessage = !!data.detail;
      throw reason;
    }
    window.location.href = data.url;
  } catch (e) {
    err.textContent = (e && e.isServerMessage) ? e.message : "Couldn't start checkout. Please try again in a moment.";
    err.style.display = "block";
    btn.disabled = false;
    btn.textContent = `Subscribe for ${PLAN_LABELS[plan]}`;
  }
}

const form = document.getElementById("buy-form");
if (form) form.addEventListener("submit", startCheckout);

// ---------------------------------------------------------------------------------------------------- nav shrink
const navEl = document.querySelector("nav");
if (navEl) {
  const onScroll = () => navEl.classList.toggle("scrolled", window.scrollY > 10);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

// ------------------------------------------------------------------------------------------------ hero demo
// The hero shows a working copy of the overlay running a made-up session (the caption says so). It is a toy model
// with invented kill, meso and potion rates; only the drop table mirrors the real screenshot. Nothing here talks to
// the API. With reduced motion on it stays still until the visitor presses Resume.
(function heroDemo() {
  const root = document.getElementById("demo");
  if (!root) return;
  const el = (k) => root.querySelector(`[data-demo="${k}"]`);
  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  const MOBS = [
    { exp: 38, drops: [["Jr. Necki Skin", 0.4, 21], ["Orange Potion", 0.01, 15], ["Orange", 0.008, 5], ["Mithril Ore", 0.003, 40], ["Topaz Ore", 0.002, 80]] },
    { exp: 55, drops: [["Ligator Skin", 0.5, 31], ["Blue Potion", 0.01, 22], ["White Potion", 0.01, 35], ["Mithril Ore", 0.003, 40], ["Aquamarine Ore", 0.002, 40]] },
  ];
  const POTION_COST = 200;
  let s, timer = null, fresh = null;

  function start() {
    s = { t: 0, exp: 0, kills: 0, mesos: 0, pots: 0, loot: new Map() }; // loot: name -> { n, value }, newest last
    fresh = null;
  }
  function step() {
    s.t += 1;
    if (Math.random() < 0.68) {
      const mob = MOBS[Math.random() < 0.5 ? 0 : 1];
      s.kills += 1; s.exp += mob.exp;
      if (Math.random() < 0.6) s.mesos += 24 + Math.floor(Math.random() * 24);
      for (const [name, chance, value] of mob.drops) {
        if (Math.random() < chance) {
          const row = s.loot.get(name) || { n: 0, value: 0 };
          row.n += 1; row.value += value;
          s.loot.delete(name); s.loot.set(name, row);
          fresh = name;
        }
      }
    }
    if (Math.random() < 0.023) s.pots += 1;
  }
  function render() {
    const perHr = (n) => (s.t ? (n / s.t) * 3600 : 0);
    const items = [...s.loot.values()];
    const count = items.reduce((a, r) => a + r.n, 0), value = items.reduce((a, r) => a + r.value, 0);
    const hh = String(Math.floor(s.t / 3600)).padStart(2, "0"), mm = String(Math.floor(s.t / 60) % 60).padStart(2, "0"), ss = String(s.t % 60).padStart(2, "0");
    el("clock").textContent = `${hh}:${mm}:${ss}`;
    el("exp").textContent = fmt(s.exp); el("kills").textContent = fmt(s.kills); el("expHr").textContent = fmt(perHr(s.exp));
    el("mesos").textContent = fmt(s.mesos); el("mesosHr").textContent = fmt(perHr(s.mesos));
    el("items").textContent = fmt(count); el("itemsHr").textContent = fmt(perHr(count));
    el("value").textContent = fmt(value); el("valueHr").textContent = fmt(perHr(value));
    el("pots").textContent = fmt(s.pots); el("potCost").textContent = fmt(s.pots * POTION_COST); el("potHr").textContent = fmt(perHr(s.pots * POTION_COST));
    const gross = perHr(s.mesos + value);
    el("gross").textContent = fmt(gross); el("net").textContent = fmt(gross - perHr(s.pots * POTION_COST));

    const list = el("loot");
    list.textContent = "";
    [...s.loot.entries()].reverse().slice(0, 4).forEach(([name, row]) => {
      const li = document.createElement("li");
      [name, `×${row.n}`, fmt(row.value)].forEach((text) => { const sp = document.createElement("span"); sp.textContent = text; li.appendChild(sp); });
      if (name === fresh) li.className = "is-new";
      list.appendChild(li);
    });
    root.querySelectorAll("[data-drop]").forEach((tr) => {
      const got = s.loot.has(tr.dataset.drop);
      tr.classList.toggle("got", got);
      tr.classList.toggle("is-new", got && tr.dataset.drop === fresh);
    });
    fresh = null;
  }
  function setRunning(on) {
    clearInterval(timer); timer = null;
    if (on) timer = setInterval(() => { step(); render(); }, 1000);
    el("pause").textContent = on ? "Pause" : "Resume";
    el("rec").textContent = on ? "Rec" : "Paused";
    el("rec").classList.toggle("is-paused", !on);
  }

  // Open a few minutes into a session so the numbers are already meaningful but rare drops are still to come.
  start();
  for (let i = 0; i < 185; i++) step();
  fresh = null;
  render();
  setRunning(!window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  el("pause").addEventListener("click", () => setRunning(!timer));
  el("reset").addEventListener("click", () => { start(); render(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden && timer) setRunning(false); });
})();
