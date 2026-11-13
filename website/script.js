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
  if (btn && !btn.disabled) btn.textContent = `Subscribe - ${PLAN_LABELS[selectedPlan()]}`;
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
  btn.textContent = "Redirecting to secure checkout...";
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
    btn.textContent = `Subscribe - ${PLAN_LABELS[plan]}`;
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
