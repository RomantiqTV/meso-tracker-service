// No build step on purpose: this is a plain static site. The API base URL is read from a <meta> tag so it's a one-line edit
// per page after you know your Render API URL (see ../SETUP.md) - no bundler, no secrets, nothing to compile.
const API_BASE = (document.querySelector('meta[name="meso-api-base"]') || {}).content || "";

async function startCheckout(ev) {
  ev.preventDefault();
  const btn = document.getElementById("buy-btn");
  const err = document.getElementById("checkout-error");
  const email = (document.getElementById("email") || {}).value || undefined;
  err.style.display = "none";
  btn.disabled = true;
  btn.textContent = "Redirecting to secure checkout...";
  try {
    const res = await fetch(`${API_BASE}/v1/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(email ? { email } : {}),
    });
    if (!res.ok) throw new Error("checkout_failed");
    const data = await res.json();
    window.location.href = data.url;
  } catch (e) {
    err.textContent = "Couldn't start checkout. Please try again in a moment.";
    err.style.display = "block";
    btn.disabled = false;
    btn.textContent = "Subscribe - $1.99/mo";
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

// -------------------------------------------------------------------------------------------- scroll-in reveals
const revealEls = document.querySelectorAll(".reveal");
if (revealEls.length && "IntersectionObserver" in window) {
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          setTimeout(() => entry.target.classList.add("in"), i % 6 * 70);
          io.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
  );
  revealEls.forEach((el) => io.observe(el));
} else {
  revealEls.forEach((el) => el.classList.add("in"));
}

// ----------------------------------------------------------------------------------------- hero HUD demo counters
// Purely cosmetic: a fake-but-plausible EXP/mesos/item readout that counts up once the hero scrolls into view, so the
// hero visually demonstrates what the real overlay shows instead of only describing it in words.
const hud = {
  exp: document.getElementById("hud-exp"),
  mesos: document.getElementById("hud-mesos"),
  items: document.getElementById("hud-items"),
};
if (hud.exp && "IntersectionObserver" in window && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const targets = { exp: 184_320, mesos: 92_740, items: 17 };
  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  let started = false;
  const runCountUp = () => {
    if (started) return;
    started = true;
    const duration = 1800, start = performance.now();
    function frame(now) {
      const p = Math.min(1, (now - start) / duration);
      const ease = 1 - Math.pow(1 - p, 3);
      hud.exp.textContent = fmt(targets.exp * ease);
      hud.mesos.textContent = fmt(targets.mesos * ease);
      hud.items.textContent = String(Math.round(targets.items * ease));
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  };
  new IntersectionObserver(
    (entries) => { if (entries[0].isIntersecting) runCountUp(); },
    { threshold: 0.4 }
  ).observe(hud.exp.closest(".hud-demo"));
} else if (hud.exp) {
  hud.exp.textContent = "184,320"; hud.mesos.textContent = "92,740"; hud.items.textContent = "17";
}
