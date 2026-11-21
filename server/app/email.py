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


_BTN = "display:inline-block;background:#e8801c;color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px;font-weight:bold"


def install_options_html(settings, download_url):
    """The "how to install" block of the welcome email. With a Store link configured (settings.store_url) there are two ways: the Microsoft Store (Windows 10 and 11)
    or the direct installer (Windows 10); without one, just the direct installer, as before."""
    store_url = getattr(settings, "store_url", "") or ""
    if not store_url:
        return f'<p><a href="{download_url}" style="{_BTN}">Download Meso Tracker</a></p>'
    return f"""
      <p style="font-size:14px;margin-bottom:6px"><strong>Two ways to install - pick one:</strong></p>
      <p style="margin:12px 0 2px"><strong>1. Microsoft Store</strong> <span style="font-size:13px;color:#555">(Windows 10 and 11)</span></p>
      <p style="margin:0 0 6px;font-size:13px;color:#555">Installs and keeps itself up to date through the Store. The easiest choice on Windows 11.</p>
      <p style="margin:6px 0 16px"><a href="{store_url}" style="{_BTN}">Get it from the Microsoft Store</a></p>
      <p style="margin:12px 0 2px"><strong>2. Direct installer</strong> <span style="font-size:13px;color:#555">(Windows 10)</span></p>
      <p style="margin:0 0 6px;font-size:13px;color:#555">A normal installer you download and run yourself.</p>
      <p style="margin:6px 0"><a href="{download_url}" style="{_BTN}">Download the installer</a></p>"""


def send_welcome(settings, to, license_key, download_url):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#7a3b0c">Welcome to Meso Tracker</h2>
      <p>Thanks for subscribing. Here's everything you need:</p>
      <p style="font-size:13px;color:#555">Your licence key (you'll enter this once, the first time you open the app):</p>
      <p style="font-size:20px;font-weight:bold;letter-spacing:1px;background:#fff4dc;border:1px solid #e3b46a;
                 border-radius:8px;padding:12px;text-align:center">{license_key}</p>
      {install_options_html(settings, download_url)}
      <p style="font-size:13px;color:#555">The first time you open it, it'll ask for your email and this key, and remember your
      PC. One licence runs on one PC at a time - to move it to a new PC, use "Deactivate this device" in the app's Settings first.</p>
      <p style="font-size:13px;color:#555">Manage or cancel your subscription any time: {settings.site_url}/billing?email={to}</p>
      <p style="font-size:12px;color:#999">Not affiliated with Nexon or MapleStory. Reads your screen only; never touches game
      files or memory, and never sends input.</p>
    </div>"""
    return send(settings, to, "Your Meso Tracker licence key", html)


def send_trial_welcome(settings, to, license_key, download_url, days):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#7a3b0c">Your {days}-day free trial of Meso Tracker</h2>
      <p>No card was taken and nothing will be charged. Here's everything you need:</p>
      <p style="font-size:13px;color:#555">Your licence key (you'll enter this once, the first time you open the app):</p>
      <p style="font-size:20px;font-weight:bold;letter-spacing:1px;background:#fff4dc;border:1px solid #e3b46a;
                 border-radius:8px;padding:12px;text-align:center">{license_key}</p>
      {install_options_html(settings, download_url)}
      <p style="font-size:13px;color:#555">Your {days} days start the first time you open the app and log in with this email and key, not today. The trial is one per person
      and one PC. When it ends the app stops until you subscribe; subscribing at {settings.site_url}/#pricing with this same email keeps this same key.</p>
      <p style="font-size:12px;color:#999">Not affiliated with Nexon or MapleStory. Reads your screen only; never touches game
      files or memory, and never sends input.</p>
    </div>"""
    return send(settings, to, f"Your Meso Tracker {days}-day free trial", html)


def send_trial_converted(settings, to):
    html = """
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#7a3b0c">Thanks for subscribing to Meso Tracker</h2>
      <p>Your subscription is active. <strong>Keep using the licence key from your free-trial email</strong> - it is the same key, nothing to re-enter, and the app picks up
      your subscription by itself the next time it checks in.</p>
      <p style="font-size:13px;color:#555">Manage or cancel any time from Settings &gt; Account &gt; Manage subscription in the app.</p>
    </div>"""
    return send(settings, to, "Your Meso Tracker subscription is active", html)


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
