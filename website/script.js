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

// ------------------------------------------------------------------------------------------------- free trial
// POST /v1/trial {email}: the server emails the licence key (no card). The 5 days start when the app is first opened with it.
async function startTrial(ev) {
  ev.preventDefault();
  const btn = document.getElementById("trial-btn");
  const msg = document.getElementById("trial-msg");
  const email = ((document.getElementById("trial-email") || {}).value || "").trim();
  const show = (text, ok) => { msg.textContent = text; msg.className = ok ? "is-ok" : "is-error"; };
  msg.className = "";
  btn.disabled = true;
  btn.textContent = "Sending your key...";
  try {
    const res = await fetch(`${API_BASE}/v1/trial`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : (res.status === 422 ? "Please enter a valid email address." : "");
      throw new Error(detail || "trial_failed");
    }
    show(`Check your inbox: we sent your licence key to ${email}. Install the app, log in with that email and key, and your ${data.days || 5} free days begin. (Not there? Look in spam.)`, true);
    btn.textContent = "Key sent";
  } catch (e) {
    show(e && e.message && e.message !== "trial_failed" && !/fetch|network/i.test(e.message) ? e.message : "Couldn't start your trial. Please try again in a moment.", false);
    btn.disabled = false;
    btn.textContent = "Start my free trial";
  }
}

const trialForm = document.getElementById("trial-form");
if (trialForm) trialForm.addEventListener("submit", startTrial);

// ---------------------------------------------------------------------------------------------- real-session tour
// Two real screenshots behind tabs; the numbered markers and the legend only show on wide screens (CSS). Hovering a frame or its legend entry spotlights that part and dims the rest.
document.querySelectorAll("[data-tour]").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("[data-tour]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
    document.querySelectorAll("[data-tour-panel]").forEach((p) => {
      const on = p.dataset.tourPanel === tab.dataset.tour;
      p.hidden = !on;
      p.classList.toggle("is-on", on);
    });
  });
});
const spot = (frame, n, on) => {
  frame.classList.toggle("has-focus", on);
  frame.querySelectorAll(".box").forEach((b) => b.classList.toggle("is-hot", on && b === n));
};
document.querySelectorAll(".shot-frame").forEach((frame) => {
  frame.querySelectorAll(".box").forEach((b) => {
    b.addEventListener("mouseenter", () => spot(frame, b, true));
    b.addEventListener("mouseleave", () => spot(frame, b, false));
  });
});
document.querySelectorAll(".tour-legend li").forEach((li) => {
  const target = () => {
    const panel = document.querySelector("[data-tour-panel]:not([hidden])");
    return panel && { frame: panel.querySelector(".shot-frame"), box: panel.querySelector('.box[data-n="' + li.dataset.n + '"]') };
  };
  li.addEventListener("mouseenter", () => { const t = target(); if (t && t.box) spot(t.frame, t.box, true); });
  li.addEventListener("mouseleave", () => { const t = target(); if (t && t.box) spot(t.frame, t.box, false); });
});

// ---------------------------------------------------------------------------------------------------- nav shrink
const navEl = document.querySelector("nav");
if (navEl) {
  const onScroll = () => navEl.classList.toggle("scrolled", window.scrollY > 10);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

// ------------------------------------------------------------------------------------------------- parallax
// Scroll position is handed to CSS as custom properties; styles.css turns them into per-layer offsets (clouds and
// far hills in the hero, the specks in the pricing band). Skipped entirely when reduced motion is on.
(function parallax() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const hero = document.querySelector(".hero"), band = document.querySelector(".band");
  const hills = hero && hero.querySelector(".hills");
  if (!hero && !band) return;
  let queued = false;
  const update = () => {
    queued = false;
    if (hero) hero.style.setProperty("--sy", Math.min(window.scrollY, hero.offsetHeight).toFixed(1));
    if (hills) {
      const vh = window.innerHeight, past = vh * 0.4 - hills.getBoundingClientRect().top; // 0 when the hills sit 60% up
      hero.style.setProperty("--hy", Math.max(-vh * 0.6, Math.min(vh * 0.6, past)).toFixed(1));
    }
    if (band) {
      const r = band.getBoundingClientRect();
      if (r.bottom > 0 && r.top < window.innerHeight) band.style.setProperty("--by", (-r.top).toFixed(1));
    }
  };
  window.addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(update); } }, { passive: true });
  update();
})();

// ------------------------------------------------------------------------------------------------ hero demo
// The hero shows a working copy of the overlay and its metric bar running a made-up session (the caption says so).
// It is a toy model with invented kill, meso and potion figures; only the drop table mirrors the real
// screenshot. Nothing here talks to the API. With reduced motion on it stays still until the visitor presses Resume.
(function heroDemo() {
  const root = document.querySelector("[data-demo-root]");
  if (!root) return;
  const all = (k) => root.querySelectorAll(`[data-demo="${k}"]`);
  const set = (k, text) => all(k).forEach((n) => { n.textContent = text; });
  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  const MOBS = [
    { exp: 40, drops: [["Firewood", 0.4, 17], ["Blue Potion", 0.01, 22], ["Orange Potion", 0.01, 15], ["Sap of Ancient Tree", 0.005, 300], ["Iron Ore", 0.004, 20], ["Diamond Ore", 0.001, 240]] },
    { exp: 60, drops: [["Fire Boar's Tooth", 0.4, 32], ["Leather", 0.025, 10], ["Blue Potion", 0.01, 22], ["White Potion", 0.01, 35], ["Iron Ore", 0.003, 20], ["Garnet Ore", 0.002, 40], ["Diamond Ore", 0.001, 240]] },
  ];
  const POTION_COST = 160, LEVEL_EXP = 14000; // both invented for the demo
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
    set("clock", `${hh}:${mm}:${ss}`);
    set("exp", fmt(s.exp)); set("kills", fmt(s.kills)); set("expHr", fmt(perHr(s.exp)));
    set("mesos", fmt(s.mesos)); set("mesosHr", fmt(perHr(s.mesos)));
    set("items", fmt(count)); set("itemsHr", fmt(perHr(count)));
    set("value", fmt(value)); set("valueHr", fmt(perHr(value)));
    set("pots", fmt(s.pots)); set("potCost", fmt(s.pots * POTION_COST)); set("potHr", fmt(perHr(s.pots * POTION_COST)));
    const gross = perHr(s.mesos + value);
    set("gross", fmt(gross)); set("net", fmt(gross - perHr(s.pots * POTION_COST)));
    const left = LEVEL_EXP - (s.exp % LEVEL_EXP), expHr = perHr(s.exp);
    set("toLevel", expHr ? `${Math.max(1, Math.ceil((left / expHr) * 60))}m` : "-");

    const list = all("loot")[0];
    list.textContent = "";
    const rows = [...s.loot.entries()].reverse().slice(0, 4).map(([name, row]) => [name, `×${row.n}`, fmt(row.value), name === fresh]);
    if (!rows.length) rows.push(["nothing picked up yet", "", "", false]);
    rows.forEach(([name, n, v, isNew]) => {
      const li = document.createElement("li");
      [name, n, v].forEach((text) => { const sp = document.createElement("span"); sp.textContent = text; li.appendChild(sp); });
      if (isNew) li.className = "is-new";
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
    set("pause", on ? "Pause" : "Resume");
    set("rec", on ? "Tracking" : "Paused");
    set("state", on ? "" : "[Paused]");
    all("rec").forEach((n) => n.classList.toggle("is-paused", !on));
  }

  // Open a few minutes into a session so the numbers are already meaningful but rare drops are still to come.
  start();
  for (let i = 0; i < 185; i++) step();
  fresh = null;
  render();
  setRunning(!window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  all("pause").forEach((b) => b.addEventListener("click", () => setRunning(!timer)));
  all("reset").forEach((b) => b.addEventListener("click", () => { start(); render(); }));
  document.addEventListener("visibilitychange", () => { if (document.hidden && timer) setRunning(false); });
})();
