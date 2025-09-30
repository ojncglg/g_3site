from flask import Flask, render_template, request, jsonify, redirect, abort, send_from_directory, url_for, flash
from werkzeug.middleware.proxy_fix import ProxyFix
import os, json
from datetime import datetime
from typing import List, Dict, Any

app = Flask(__name__)

# Secret key for session/flash (override in Render env)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")

# Centralized contact email (override in Render env)
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "grigori.lopezgarcia@gmail.com")

# Make contact_email available in all templates
@app.context_processor
def inject_contact_email():
    return {"contact_email": CONTACT_EMAIL}

# Trust proxy headers (needed for HTTPS enforcement on Render)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

# Enforce HTTPS for all requests except in debug mode
@app.before_request
def enforce_https():
    xf_proto = request.headers.get("X-Forwarded-Proto", "")
    url = request.url
    if (request.method in ("GET", "HEAD")
        and not app.debug
        and xf_proto != "https"
        and url.startswith("http://")):
        secure_url = "https://" + url[len("http://"):]
        return redirect(secure_url, code=301)

# Set secure headers for all responses
@app.after_request
def set_security_headers(resp):
    resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self' mailto:; "
        "frame-ancestors 'none'"
    )
    if not resp.headers.get("Content-Security-Policy"):
        resp.headers["Content-Security-Policy"] = csp
    return resp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LEADS_FILE = os.path.join(DATA_DIR, "leads.json")

def ensure_data_store() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

def append_lead(lead: Dict[str, Any]) -> None:
    ensure_data_store()
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            data: List[Dict[str, Any]] = json.load(f)
    except json.JSONDecodeError:
        data = []
    data.append(lead)
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.route("/_health")
def health():
    return "ok", 200

@app.route("/")
def home():
    return render_template("index.html", title="G3 Industries")

@app.route("/products")
def products():
    return render_template("products.html", title="Products — G3 Industries")


@app.route("/about")
def about():
    return render_template("about.html", title="About — G3 Industries")


# New /security route
@app.route("/security")
def security():
    return render_template("security.html", title="Security — G3 Industries")


@app.route("/demo", methods=["POST"])
def demo():
    # Basic fields expected from the form
    name = request.form.get("name", "").strip()
    agency = request.form.get("agency", "").strip()
    role = request.form.get("role", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    notes = request.form.get("notes", "").strip()

    # Anti-spam: honeypot & time-to-submit
    honeypot = request.form.get("website", "").strip()  # hidden field; humans leave empty
    form_start = request.form.get("form_start", "").strip()  # epoch ms set by JS on load

    # Compute time-to-submit (ms)
    min_delay_ms = 3000  # require ~3s on page before submit
    elapsed_ok = True
    try:
        if form_start:
            started = int(form_start)
            now_ms = int(datetime.utcnow().timestamp() * 1000)
            elapsed_ok = (now_ms - started) >= min_delay_ms
    except ValueError:
        # If malformed, treat as suspicious but do not block legitimate users
        elapsed_ok = True

    # If honeypot filled or submitted too fast, pretend success (no side effects)
    is_bot = bool(honeypot) or not elapsed_ok
    if is_bot:
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")
        if wants_json:
            return jsonify({"ok": True, "message": "Thanks"}), 200
        flash("Thanks — we’ll be in touch.", "success")
        return redirect(url_for("home") + "#demo")

    # Minimal validation
    errors = []
    if not name:
        errors.append("name")
    if not agency:
        errors.append("agency")
    if not email:
        errors.append("email")

    if errors:
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")
        if wants_json:
            return jsonify({"ok": False, "errors": errors}), 400
        flash("Please fill the required fields: " + ", ".join(errors), "error")
        return redirect(url_for("home") + "#demo")

    lead = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "name": name,
        "agency": agency,
        "role": role,
        "email": email,
        "phone": phone,
        "notes": notes,
        "source_ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent", ""),
        "elapsed_ms": (int(datetime.utcnow().timestamp() * 1000) - int(form_start)) if form_start.isdigit() else None,
    }

    append_lead(lead)

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")
    if wants_json:
        return jsonify({"ok": True, "message": "Lead received"}), 200
    flash("Thanks — we received your request and will get back to you.", "success")
    return redirect(url_for("home") + "#demo")
@app.errorhandler(404)
def page_not_found(e):
        # Render a custom 404 page with Matrix effect
    return render_template("404.html", title="404 — Page not found"), 404

@app.errorhandler(500)
def internal_error(e):
        # Render a custom 500 page with Matrix effect
    return render_template("500.html", title="500 — Internal server error"), 500

# Testing error pages
@app.route("/force500")
def force500():
    # Force an Internal Server Error via HTTP abort so our errorhandler(500) runs
    abort(500)

# Directly preview the 500 page (useful when DEBUG is on)
@app.route("/_preview/500")
def preview_500():
    # Directly render the 500 template so you can preview it while DEBUG is on
    return render_template("500.html", title="500 — Internal server error"), 500


# Serve robots.txt and sitemap.xml from the project root
@app.route('/robots.txt')
def robots_txt():
    return send_from_directory(BASE_DIR, 'robots.txt', mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap_xml():
    return send_from_directory(BASE_DIR, 'sitemap.xml', mimetype='application/xml')

if __name__ == "__main__":
    app.run(debug=True)
