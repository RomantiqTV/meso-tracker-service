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
