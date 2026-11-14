"""Transactional email via Resend's HTTP API (https://resend.com) - plain requests call, no SDK needed for something this small."""
import requests

RESEND_URL = "https://api.resend.com/emails"


def send(settings, to, subject, html):
    r = requests.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"},
        json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def send_welcome(settings, to, license_key, download_url):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#7a3b0c">Welcome to Meso Tracker</h2>
      <p>Thanks for subscribing. Here's everything you need:</p>
      <p style="font-size:13px;color:#555">Your licence key (you'll enter this once, the first time you open the app):</p>
      <p style="font-size:20px;font-weight:bold;letter-spacing:1px;background:#fff4dc;border:1px solid #e3b46a;
                 border-radius:8px;padding:12px;text-align:center">{license_key}</p>
      <p><a href="{download_url}" style="display:inline-block;background:#e8801c;color:#fff;text-decoration:none;
                 padding:10px 18px;border-radius:8px;font-weight:bold">Download Meso Tracker</a></p>
      <p style="font-size:13px;color:#555">The first time you open it, it'll ask for your email and this key, and remember your
      PC. One licence runs on one PC at a time - to move it to a new PC, use "Deactivate this device" in the app's Settings first.</p>
      <p style="font-size:13px;color:#555">Manage or cancel your subscription any time: {settings.site_url}/billing?email={to}</p>
      <p style="font-size:12px;color:#999">Not affiliated with Nexon or MapleStory. Reads your screen only; never touches game
      files or memory, and never sends input.</p>
    </div>"""
    return send(settings, to, "Your Meso Tracker licence key", html)


def send_payment_failed(settings, to):
    html = """
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#c23a2a">We couldn't renew your Meso Tracker subscription</h2>
      <p>Your card was declined. Please update your payment method to keep using the app without interruption.</p>
    </div>"""
    return send(settings, to, "Action needed: Meso Tracker payment failed", html)


def send_update_announcement(settings, to, download_url):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#7a3b0c">Meso Tracker 1.2.0 is out</h2>
      <p>Three changes in this release:</p>
      <ul style="font-size:14px;color:#333;padding-left:18px">
        <li>Potion/food tracking covers all 8 hotbar slots now, not just Q and E.</li>
        <li>Lowering the overlay's opacity only fades the background - the text stays readable.</li>
        <li>A real installer: Start Menu and desktop shortcuts, a proper uninstaller, and automatic updates in place from here on.</li>
      </ul>
      <p style="font-size:13px;color:#555">You're running a version that came as a zip you extracted yourself, so this is the one
      update you'll have to grab by hand. Run the installer below once - it finds your existing licence automatically, nothing
      to re-enter - and every update after this happens inside the app on its own.</p>
      <p><a href="{download_url}" style="display:inline-block;background:#e8801c;color:#fff;text-decoration:none;
                 padding:10px 18px;border-radius:8px;font-weight:bold">Download Meso Tracker 1.2.0</a></p>
      <p style="font-size:13px;color:#555">Once it's running, you can delete your old Meso Tracker folder - the installer put a
      fresh copy in its own location and your login already carried over.</p>
      <p style="font-size:12px;color:#999">Not affiliated with Nexon or MapleStory. Reads your screen only; never touches game
      files or memory, and never sends input.</p>
    </div>"""
    return send(settings, to, "Meso Tracker 1.2.0 - the last manual update you'll need to do", html)
