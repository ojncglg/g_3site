from flask import Flask, render_template, request, jsonify
import os, json
from datetime import datetime
from typing import List, Dict, Any
app = Flask(__name__)

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


@app.route("/demo", methods=["POST"])
def demo():
    # Basic fields expected from the form
    name = request.form.get("name", "").strip()
    agency = request.form.get("agency", "").strip()
    role = request.form.get("role", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    notes = request.form.get("notes", "").strip()

    # Honeypot (hidden field). Bots will often fill this; humans won't.
    honeypot = request.form.get("website", "").strip()  # 'website' is a common honeypot name

    # If honeypot is filled, silently accept but do nothing.
    if honeypot:
        return jsonify({"ok": True, "message": "Thanks"}), 200

    # Minimal validation
    errors = []
    if not name:
        errors.append("name")
    if not agency:
        errors.append("agency")
    if not email:
        errors.append("email")

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

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
    }

    append_lead(lead)
    return jsonify({"ok": True, "message": "Lead received"}), 200

if __name__ == "__main__":
    app.run(debug=True)
