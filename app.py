import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# Secret key used by Flask sessions and flash messages.
# In production, this should always come from an environment variable.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")

# Fail fast if production boots without a real session secret.
RUNNING_PRODUCTION = os.environ.get("RENDER", "").lower() == "true" or os.environ.get(
    "FLASK_ENV", ""
).lower() == "production"
if RUNNING_PRODUCTION and app.config["SECRET_KEY"] == "dev-change-me":
    raise RuntimeError("SECRET_KEY must be set in production.")

# Shared support/contact email exposed to templates via context_processor.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "grigori.lopezgarcia@g3industries.io")
DEMO_TO_EMAIL = os.environ.get("DEMO_TO_EMAIL", CONTACT_EMAIL)
DEMO_FROM_EMAIL = os.environ.get("DEMO_FROM_EMAIL", DEMO_TO_EMAIL)

# SMTP settings used to deliver demo requests via email.
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get(
    "SMTP_USERNAME",
    os.environ.get("SMTP_USER", CONTACT_EMAIL),
).strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", ""))
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip() in ("1", "true", "True")
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "0").strip() in ("1", "true", "True")
SMTP_TIMEOUT_SECONDS = float(os.environ.get("SMTP_TIMEOUT_SECONDS", "10"))
# In production this should stay enabled; set to 0 temporarily if you're testing locally.
REQUIRE_EMAIL_DELIVERY = os.environ.get("REQUIRE_EMAIL_DELIVERY", "1").strip() in (
    "1",
    "true",
    "True",
)

# Build absolute paths once so file access is predictable from any working dir.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LEADS_FILE = os.path.join(DATA_DIR, "leads.json")

# Central CSP string reused for each response unless a route sets its own CSP.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://www.googletagmanager.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: https://www.google-analytics.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self' https://www.google-analytics.com https://www.googletagmanager.com; "
    "base-uri 'self'; "
    "form-action 'self' mailto:; "
    "frame-ancestors 'none'"
)

# Trust one layer of proxy headers (Render/ingress), so request.is_secure is accurate.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def utc_now_ms() -> int:
    """Return current UTC time in milliseconds for anti-spam timing checks."""
    return int(utc_now().timestamp() * 1000)


def wants_json_response() -> bool:
    """Detect whether caller expects JSON (AJAX/fetch/API style requests)."""
    accept = request.headers.get("Accept", "")
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept
    )


def redirect_to_demo_anchor():
    """Send browser users back to the home page demo section."""
    return redirect(url_for("home", _anchor="demo"))


def ensure_data_store() -> None:
    """Create local lead storage if missing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "w", encoding="utf-8") as file:
            json.dump([], file)


def append_lead(lead: Dict[str, Any]) -> None:
    """Append one lead object to leads.json while tolerating a corrupt file."""
    ensure_data_store()
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as file:
            data: List[Dict[str, Any]] = json.load(file)
    except json.JSONDecodeError:
        data = []

    data.append(lead)
    with open(LEADS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def send_demo_email(lead: Dict[str, Any]) -> tuple[bool, str]:
    """
    Send a demo request email through SMTP.
    Returns (ok, error_message).
    """
    if not SMTP_HOST:
        message = "SMTP is not configured (missing SMTP_HOST)."
        if app.debug and not REQUIRE_EMAIL_DELIVERY:
            # Allow local development without a configured mail server.
            app.logger.warning(message)
            return True, ""
        return False, message

    if not SMTP_PASSWORD:
        return False, "SMTP password is missing (set SMTP_PASSWORD)."

    subject = f"New Demo Request — {lead.get('agency', 'Unknown Agency')}"
    body_lines = [
        "A new demo request was submitted on g3industries.io.",
        "",
        f"Name: {lead.get('name', '')}",
        f"Agency: {lead.get('agency', '')}",
        f"Role/Rank: {lead.get('role', '')}",
        f"Email: {lead.get('email', '')}",
        f"Phone: {lead.get('phone', '')}",
        "",
        "Notes:",
        lead.get("notes", "") or "(none)",
        "",
        "Metadata:",
        f"Submitted At (UTC): {lead.get('timestamp', '')}",
        f"Source IP: {lead.get('source_ip', '')}",
        f"User Agent: {lead.get('user_agent', '')}",
        f"Elapsed MS: {lead.get('elapsed_ms', '')}",
    ]

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = DEMO_FROM_EMAIL
    message["To"] = DEMO_TO_EMAIL
    message["Reply-To"] = lead.get("email", DEMO_TO_EMAIL)
    message.set_content("\n".join(body_lines))

    try:
        if SMTP_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                SMTP_HOST,
                SMTP_PORT,
                timeout=SMTP_TIMEOUT_SECONDS,
                context=context,
            ) as server:
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
                if SMTP_USE_TLS:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)

    return True, ""


@app.context_processor
def inject_contact_email():
    """Expose contact_email in every template render."""
    return {"contact_email": CONTACT_EMAIL}


@app.before_request
def enforce_https():
    """Redirect plaintext GET/HEAD requests to HTTPS in non-debug mode."""
    if request.method not in ("GET", "HEAD"):
        return None
    if app.debug or request.is_secure:
        return None
    if request.url.startswith("http://"):
        return redirect(request.url.replace("http://", "https://", 1), code=301)
    return None


@app.after_request
def set_security_headers(response):
    """Attach baseline security headers to every response."""
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), geolocation=(), microphone=()"
    )
    response.headers.setdefault("Content-Security-Policy", DEFAULT_CSP)
    return response


@app.route("/_health")
def health():
    """Lightweight health endpoint for deploy checks."""
    return "ok", 200


@app.route("/")
def home():
    """Marketing home page."""
    return render_template("index.html", title="G3 Industries")


@app.route("/products")
def products():
    """Products overview page."""
    return render_template("products.html", title="Products — G3 Industries")


@app.route("/about")
def about():
    """Company/about page."""
    return render_template("about.html", title="About — G3 Industries")


@app.route("/security")
def security():
    """Security posture page."""
    return render_template("security.html", title="Security — G3 Industries")


@app.route("/grants")
def grants():
    """Grant assistance page."""
    return render_template("grants.html", title="Grant Assistance — G3 Industries")


@app.route("/demo", methods=["POST"])
def demo():
    """
    Handle demo-request submissions:
    - normalize input
    - apply anti-spam checks
    - validate required fields
    - persist lead
    - return JSON for fetch clients or redirect+flash for browsers
    """
    # Normalize all input fields once to keep validation logic simple.
    name = request.form.get("name", "").strip()
    agency = request.form.get("agency", "").strip()
    role = request.form.get("role", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    notes = request.form.get("notes", "").strip()
    honeypot = request.form.get("website", "").strip()
    form_start = request.form.get("form_start", "").strip()

    # Time-based anti-spam check: require at least ~3 seconds before submit.
    min_delay_ms = 3000
    elapsed_ms = None
    elapsed_ok = True
    if form_start:
        try:
            elapsed_ms = max(0, utc_now_ms() - int(form_start))
            elapsed_ok = elapsed_ms >= min_delay_ms
        except ValueError:
            # Keep this permissive so malformed input does not block humans.
            elapsed_ok = True

    # Honeypot trips are treated as bot submissions and quietly ignored.
    if honeypot:
        if wants_json_response():
            return jsonify({"ok": True, "message": "Thanks"}), 200
        flash("Thanks — we’ll be in touch.", "success")
        return redirect_to_demo_anchor()

    # Required fields must be present for a valid demo request.
    required_values = {"name": name, "agency": agency, "email": email}
    missing_fields = [field for field, value in required_values.items() if not value]
    if missing_fields:
        if wants_json_response():
            return jsonify({"ok": False, "errors": missing_fields}), 400
        flash("Please fill the required fields: " + ", ".join(missing_fields), "error")
        return redirect_to_demo_anchor()

    # Persist the lead payload for follow-up and basic diagnostics.
    submitted_at = utc_now()
    lead = {
        "timestamp": submitted_at.isoformat().replace("+00:00", "Z"),
        "name": name,
        "agency": agency,
        "role": role,
        "email": email,
        "phone": phone,
        "notes": notes,
        "source_ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent", ""),
        "elapsed_ms": elapsed_ms,
        "suspicious_too_fast": not elapsed_ok,
    }
    append_lead(lead)

    # Try to deliver the lead via email.
    email_sent, delivery_error = send_demo_email(lead)
    if not email_sent:
        app.logger.error("Demo email delivery failed: %s", delivery_error)
        if REQUIRE_EMAIL_DELIVERY:
            if wants_json_response():
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "Request saved, but email delivery failed. Please try again or email us directly.",
                        }
                    ),
                    503,
                )
            flash(
                "We received your request, but email delivery failed. Please email us directly at "
                + CONTACT_EMAIL,
                "error",
            )
            return redirect_to_demo_anchor()

    if wants_json_response():
        return jsonify({"ok": True, "message": "Lead received"}), 200
    flash("Thanks — we received your request and will get back to you.", "success")
    return redirect_to_demo_anchor()


@app.errorhandler(404)
def page_not_found(_error):
    """Render branded 404 page."""
    return render_template("404.html", title="404 — Page not found"), 404


@app.errorhandler(500)
def internal_error(_error):
    """Render branded 500 page."""
    return render_template("500.html", title="500 — Internal server error"), 500


@app.route("/force500")
def force500():
    """Intentionally trigger HTTP 500 to test the error handler."""
    abort(500)


@app.route("/_preview/500")
def preview_500():
    """Preview the 500 template while debug mode is enabled."""
    return render_template("500.html", title="500 — Internal server error"), 500


@app.route("/robots.txt")
def robots_txt():
    """Serve robots.txt from project root."""
    return send_from_directory(BASE_DIR, "robots.txt", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    """Serve sitemap.xml from project root."""
    return send_from_directory(BASE_DIR, "sitemap.xml", mimetype="application/xml")


if __name__ == "__main__":
    app.run(debug=True)
