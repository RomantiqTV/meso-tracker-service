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
