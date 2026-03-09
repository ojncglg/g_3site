"""
G3 Industries public website backend.

This module handles:
1) Page rendering routes.
2) Public demo-form intake and anti-abuse controls.
3) Email delivery through Resend or SMTP.
4) Baseline security headers and HTTPS redirect behavior.

The goal is to keep this file readable for non-specialists who need to
understand operational behavior quickly.
"""

# Standard library imports used for persistence, validation, and delivery.
import hashlib
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List
from urllib import error as urllib_error
from urllib import request as urllib_request

# Flask objects used by routes/middleware.
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

# Create the Flask application instance.
app = Flask(__name__)

# Secret key powers session signing and flash-message integrity.
# In production this must be injected via env var.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")

# Reject unexpectedly large requests early (default 64 KB).
# This prevents oversized payload abuse against public form endpoints.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_FORM_CONTENT_BYTES", "65536"))

# Decide whether service is running as a production deployment.
RUNNING_PRODUCTION = os.environ.get("RENDER", "").lower() == "true" or os.environ.get(
    "FLASK_ENV", ""
).lower() == "production"
# Hard-fail startup in production if default key is still present.
if RUNNING_PRODUCTION and app.config["SECRET_KEY"] == "dev-change-me":
    raise RuntimeError("SECRET_KEY must be set in production.")

# Shared contact addresses consumed by templates and email handlers.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "grigori.lopezgarcia@g3industries.io")
DEMO_TO_EMAIL = os.environ.get("DEMO_TO_EMAIL", CONTACT_EMAIL)
DEMO_FROM_EMAIL = os.environ.get("DEMO_FROM_EMAIL", DEMO_TO_EMAIL)

# SMTP settings used when provider is "smtp" or when "auto" falls back to SMTP.
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
# Outbound provider selection:
# - "auto": prefer Resend when configured; otherwise use SMTP.
# - "resend": only use Resend API.
# - "smtp": only use SMTP.
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "auto").strip().lower()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", DEMO_FROM_EMAIL).strip()
RESEND_API_URL = os.environ.get("RESEND_API_URL", "https://api.resend.com/emails").strip()

# Field-length controls used during form validation.
FIELD_MAX_LENGTHS = {
    "name": 120,
    "agency": 160,
    "role": 120,
    "email": 254,
    "phone": 40,
    "notes": 2000,
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+().\-\s]{7,40}$")

# Salt used to hash identity keys inside the local rate-limit store.
RATE_LIMIT_SALT = os.environ.get("RATE_LIMIT_SALT", app.config["SECRET_KEY"])

# Per-network throttling controls.
DEMO_IP_LIMIT_WINDOW_SECONDS = int(os.environ.get("DEMO_IP_LIMIT_WINDOW_SECONDS", "300"))
DEMO_IP_LIMIT_COUNT = int(os.environ.get("DEMO_IP_LIMIT_COUNT", "5"))

# Per-email throttling controls.
DEMO_EMAIL_LIMIT_WINDOW_SECONDS = int(os.environ.get("DEMO_EMAIL_LIMIT_WINDOW_SECONDS", "1800"))
DEMO_EMAIL_LIMIT_COUNT = int(os.environ.get("DEMO_EMAIL_LIMIT_COUNT", "3"))

# Global endpoint burst controls.
DEMO_GLOBAL_LIMIT_WINDOW_SECONDS = int(os.environ.get("DEMO_GLOBAL_LIMIT_WINDOW_SECONDS", "60"))
DEMO_GLOBAL_LIMIT_COUNT = int(os.environ.get("DEMO_GLOBAL_LIMIT_COUNT", "25"))

# Minimum seconds between two requests from same IP.
DEMO_IP_MIN_INTERVAL_SECONDS = int(os.environ.get("DEMO_IP_MIN_INTERVAL_SECONDS", "10"))

# Filesystem paths used by simple on-disk storage.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LEADS_FILE = os.path.join(DATA_DIR, "leads.json")
RATE_LIMIT_FILE = os.path.join(DATA_DIR, "rate_limits.json")

# Centralized CSP applied to responses unless explicitly overridden.
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

# Trust one proxy hop so Flask receives real client protocol/IP data.
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
    if not os.path.exists(RATE_LIMIT_FILE):
        with open(RATE_LIMIT_FILE, "w", encoding="utf-8") as file:
            json.dump({"global": [], "ip": {}, "email": {}}, file)


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


def normalize_text(value: str, *, allow_newlines: bool = False) -> str:
    """Trim and normalize user-provided text for consistent validation."""
    value = (value or "").replace("\x00", "").strip()
    if allow_newlines:
        return value.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(value.split())


def get_client_ip() -> str:
    """
    Resolve the best-available client IP.
    ProxyFix already handles trusted proxy headers, but Cloudflare and some edges
    still provide explicit headers we can prefer.
    """
    cloudflare_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cloudflare_ip:
        return cloudflare_ip
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.remote_addr or "unknown"


def stable_rate_key(value: str) -> str:
    """Hash identifiers before storing in rate-limit state."""
    digest = hashlib.sha256(f"{RATE_LIMIT_SALT}|{value}".encode("utf-8")).hexdigest()
    return digest[:32]


def load_rate_store() -> Dict[str, Any]:
    """Load rate-limit state from disk with a safe fallback."""
    ensure_data_store()
    try:
        with open(RATE_LIMIT_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        data = {}

    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("global"), list):
        data["global"] = []
    if not isinstance(data.get("ip"), dict):
        data["ip"] = {}
    if not isinstance(data.get("email"), dict):
        data["email"] = {}
    return data


def save_rate_store(data: Dict[str, Any]) -> None:
    """Persist rate-limit state atomically."""
    ensure_data_store()
    temp_file = RATE_LIMIT_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)
    os.replace(temp_file, RATE_LIMIT_FILE)


def prune_recent(events: List[int], now_s: int, window_s: int) -> List[int]:
    """Keep only event timestamps inside the configured time window."""
    cutoff = now_s - window_s
    return [timestamp for timestamp in events if timestamp >= cutoff]


def check_and_record_rate_limit(client_ip: str, email: str) -> tuple[bool, str]:
    """
    Enforce burst and windowed limits to prevent form abuse.
    Limits:
    - global requests per minute
    - per-IP requests per 5 minutes + minimum interval between requests
    - per-email requests per 30 minutes
    """
    now_s = int(utc_now().timestamp())
    state = load_rate_store()

    global_events = prune_recent(
        [int(value) for value in state["global"] if isinstance(value, int)],
        now_s,
        DEMO_GLOBAL_LIMIT_WINDOW_SECONDS,
    )
    if len(global_events) >= DEMO_GLOBAL_LIMIT_COUNT:
        return False, "Too many requests right now. Please wait a minute and try again."

    ip_key = stable_rate_key(client_ip)
    ip_events = prune_recent(
        [int(value) for value in state["ip"].get(ip_key, []) if isinstance(value, int)],
        now_s,
        DEMO_IP_LIMIT_WINDOW_SECONDS,
    )
    if ip_events and (now_s - ip_events[-1]) < DEMO_IP_MIN_INTERVAL_SECONDS:
        return False, "Please wait a few seconds before submitting again."
    if len(ip_events) >= DEMO_IP_LIMIT_COUNT:
        return False, "Too many requests from this network. Please try again later."

    email_key = stable_rate_key(email.lower())
    email_events = prune_recent(
        [int(value) for value in state["email"].get(email_key, []) if isinstance(value, int)],
        now_s,
        DEMO_EMAIL_LIMIT_WINDOW_SECONDS,
    )
    if len(email_events) >= DEMO_EMAIL_LIMIT_COUNT:
        return False, "Too many demo requests for this email. Please try again later."

    global_events.append(now_s)
    ip_events.append(now_s)
    email_events.append(now_s)

    state["global"] = global_events
    state["ip"][ip_key] = ip_events
    state["email"][email_key] = email_events
    save_rate_store(state)
    return True, ""


def send_demo_email(lead: Dict[str, Any]) -> tuple[bool, str]:
    """
    Send a demo request email through the configured provider.
    Returns (ok, error_message).
    """
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
    body_text = "\n".join(body_lines)

    # Provider routing:
    # 1) Use Resend first when allowed and configured.
    # 2) If provider is strictly "resend", return Resend error directly.
    # 3) Otherwise fall back to SMTP.
    if EMAIL_PROVIDER in ("auto", "resend") and RESEND_API_KEY:
        ok, message = send_demo_email_resend(subject, body_text, lead)
        if ok:
            return True, ""
        if EMAIL_PROVIDER == "resend":
            return False, message

    if EMAIL_PROVIDER == "resend" and not RESEND_API_KEY:
        return False, "RESEND_API_KEY is missing while EMAIL_PROVIDER=resend."

    # Fallback path for smtp/auto mode.
    return send_demo_email_smtp(subject, body_text, lead)


def send_demo_email_resend(subject: str, body_text: str, lead: Dict[str, Any]) -> tuple[bool, str]:
    """Send demo request email through the Resend API."""
    # Build JSON payload expected by Resend.
    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [DEMO_TO_EMAIL],
        "subject": subject,
        "text": body_text,
        # Keep threaded replies pointed to the requestor.
        "reply_to": lead.get("email", DEMO_TO_EMAIL),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        RESEND_API_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            # Resend requires a User-Agent for direct HTTP requests.
            "User-Agent": "g3-industries-site/1.0",
            "Accept": "application/json",
        },
    )
    try:
        # Execute HTTPS request to Resend API.
        with urllib_request.urlopen(req, timeout=SMTP_TIMEOUT_SECONDS) as response:
            if 200 <= response.status < 300:
                return True, ""
            return False, f"Resend API returned status {response.status}."
    except urllib_error.HTTPError as exc:
        # Return server-provided response body for debugging.
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"Resend API HTTP {exc.code}: {body}"
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"Resend API error: {exc}"


def send_demo_email_smtp(subject: str, body_text: str, lead: Dict[str, Any]) -> tuple[bool, str]:
    """Send demo request email through SMTP."""
    if not SMTP_HOST:
        message = "SMTP is not configured (missing SMTP_HOST)."
        if app.debug and not REQUIRE_EMAIL_DELIVERY:
            # Allow local development without a configured mail server.
            app.logger.warning(message)
            return True, ""
        return False, message

    if not SMTP_PASSWORD:
        return False, "SMTP password is missing (set SMTP_PASSWORD)."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = DEMO_FROM_EMAIL
    message["To"] = DEMO_TO_EMAIL
    message["Reply-To"] = lead.get("email", DEMO_TO_EMAIL)
    message.set_content(body_text)

    try:
        # SSL mode uses implicit TLS on connect.
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
            # Plain socket mode can upgrade with STARTTLS.
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
    # Only redirect safe idempotent methods.
    if request.method not in ("GET", "HEAD"):
        return None
    if app.debug or request.is_secure:
        return None
    # Convert explicit http:// URLs to https://.
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


@app.errorhandler(413)
def request_too_large(_error):
    """Handle oversized form submissions without exposing internals."""
    if wants_json_response():
        return jsonify({"ok": False, "error": "Submission too large."}), 413
    flash("Submission too large. Please shorten your message and try again.", "error")
    return redirect_to_demo_anchor()


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
    # Read and normalize user input values.
    name = normalize_text(request.form.get("name", ""))
    agency = normalize_text(request.form.get("agency", ""))
    role = normalize_text(request.form.get("role", ""))
    email = normalize_text(request.form.get("email", "")).lower()
    phone = normalize_text(request.form.get("phone", ""))
    notes = normalize_text(request.form.get("notes", ""), allow_newlines=True)
    honeypot = normalize_text(request.form.get("website", ""))
    form_start = normalize_text(request.form.get("form_start", ""))

    # Time-based anti-spam check: require ~3 seconds before submit.
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
    # Collect invalid fields for length/format violations.
    invalid_fields = []
    if name and len(name) > FIELD_MAX_LENGTHS["name"]:
        invalid_fields.append("name")
    if agency and len(agency) > FIELD_MAX_LENGTHS["agency"]:
        invalid_fields.append("agency")
    if role and len(role) > FIELD_MAX_LENGTHS["role"]:
        invalid_fields.append("role")
    if email and (len(email) > FIELD_MAX_LENGTHS["email"] or not EMAIL_RE.fullmatch(email)):
        invalid_fields.append("email")
    if phone and (len(phone) > FIELD_MAX_LENGTHS["phone"] or not PHONE_RE.fullmatch(phone)):
        invalid_fields.append("phone")
    if notes and len(notes) > FIELD_MAX_LENGTHS["notes"]:
        invalid_fields.append("notes")

    validation_errors = sorted(set(missing_fields + invalid_fields))
    if validation_errors:
        if wants_json_response():
            return jsonify({"ok": False, "errors": validation_errors}), 400
        flash(
            "Please review the form fields: " + ", ".join(validation_errors),
            "error",
        )
        return redirect_to_demo_anchor()

    # Apply server-side rate limits before persisting or sending email.
    client_ip = get_client_ip()
    allowed, rate_message = check_and_record_rate_limit(client_ip, email)
    if not allowed:
        if wants_json_response():
            return jsonify({"ok": False, "error": rate_message}), 429
        flash(rate_message, "error")
        return redirect_to_demo_anchor()

    # Build and persist normalized lead record.
    submitted_at = utc_now()
    lead = {
        "timestamp": submitted_at.isoformat().replace("+00:00", "Z"),
        "name": name,
        "agency": agency,
        "role": role,
        "email": email,
        "phone": phone,
        "notes": notes,
        "source_ip": client_ip,
        "user_agent": request.headers.get("User-Agent", ""),
        "elapsed_ms": elapsed_ms,
        "suspicious_too_fast": not elapsed_ok,
    }
    append_lead(lead)

    # Attempt outbound email delivery via configured provider.
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
