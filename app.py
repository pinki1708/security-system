import os
import json
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

# Config
EXTERNAL_LOOKUP_BASE = "https://super-duper-carnival.onrender.com/api/users/by-email"
ATTEMPT_THRESHOLD = int(os.getenv("ATTEMPT_THRESHOLD", "3"))  # change to 4 if you want
ATTEMPT_TRACKER_FILE = "attempts.json"   # demo-only; use DB/Redis in prod
MESSAGE_FILE = "messages.json"           # demo-only; use DB in prod

# ---------- JSON file helpers (demo) ----------
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

def norm_email(e: str) -> str:
    return (e or "").strip().lower()

# ---------- Attempts (demo) ----------
def increment_attempt(email):
    e = norm_email(email)
    data = load_json(ATTEMPT_TRACKER_FILE)
    count = int(data.get(e, 0)) + 1
    data[e] = count
    save_json(ATTEMPT_TRACKER_FILE, data)
    app.logger.info(f"[attempts] {e} -> {count}")
    return count

def reset_attempt(email):
    e = norm_email(email)
    data = load_json(ATTEMPT_TRACKER_FILE)
    data[e] = 0
    save_json(ATTEMPT_TRACKER_FILE, data)
    app.logger.info(f"[attempts] {e} reset -> 0")

# ---------- Message store (demo) ----------
def store_message_temp(user_id, message: str):
    data = load_json(MESSAGE_FILE)
    data[str(user_id)] = message
    save_json(MESSAGE_FILE, data)
    app.logger.info(f"[store_message] user_id={user_id}")
    return True, None

def get_and_delete_message(user_id):
    data = load_json(MESSAGE_FILE)
    message = data.pop(str(user_id), None)
    if message:
        save_json(MESSAGE_FILE, data)
        return message, None
    return None, "No message found"

# ---------- External user lookup ----------
def fetch_user_id_by_email(email: str):
    try:
        resp = requests.get(EXTERNAL_LOOKUP_BASE, params={"email": email}, timeout=120)
        if resp.status_code != 200:
            return None, f"lookup failed: {resp.status_code}"
        data = resp.json()
        app.logger.info(f"[lookup] {email}: {data}")
        user_id = (
            data.get("id")
            or data.get("userId")
            or (data.get("user") or {}).get("id")
            or (data.get("data") or {}).get("id")
            or (data.get("result") or {}).get("id")
        )
        if not user_id:
            return None, "id not found in response"
        return user_id, None
    except Exception as e:
        return None, str(e)

# ---------- Notify placeholder (wire to your real pipeline) ----------
def send_in_app_message(user_id, message: str):
    # Replace with Socket.IO emit / Notifications API / DB insert
    app.logger.warning(f"[notify] user_id={user_id} message={message}")
    store_message_temp(user_id, message)
    return True, None

# ---------- Routes ----------
@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.get("/get-message")
def get_message():
    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"error": "userId query parameter is required"}), 400
    message, err = get_and_delete_message(user_id)
    if message:
        return jsonify({"user_id": user_id, "message": message}), 200
    return jsonify({"error": err, "user_id": user_id}), 404

@app.post("/login")
def login():
    """
    Demo: treats any password as wrong to show attempts + alert flow.
    For real login, add DB bcrypt verification; then call increment_attempt only when wrong.
    """
    body = request.get_json(force=True) or {}
    email = body.get("email")
    password = body.get("password")

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    # WRONG password demo: increment attempts
    wrong_attempts = increment_attempt(email)

    if wrong_attempts >= ATTEMPT_THRESHOLD:
        reset_attempt(email)
        ext_user_id, lookup_err = fetch_user_id_by_email(email)
        notify_status, notify_error = (None, None)
        if ext_user_id:
            notify_status, notify_error = send_in_app_message(
                ext_user_id,
                "⚠ WARNING: multiple wrong login attempts detected for your account!"
            )
        return jsonify({
            "error": "Invalid password",
            "attempts": ATTEMPT_THRESHOLD,
            "external_user_id": ext_user_id,
            "external_lookup_error": lookup_err,
            "notify_sent": bool(notify_status),
            "notify_error": notify_error
        }), 403

    return jsonify({"error": "Invalid password", "attempts": wrong_attempts}), 403

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
