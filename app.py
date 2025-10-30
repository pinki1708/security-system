import os
import json
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# External user lookup API
EXTERNAL_LOOKUP_BASE = "https://super-duper-carnival.onrender.com/api/users/by-email"

# Persistent message file
MESSAGE_FILE = "messages.json"

# Persistent attempt tracking
ATTEMPT_TRACKER_FILE = "attempts.json"


# ========== Utility: Load & Save JSON safely ==========
def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f)


# ========== Persistent message storage ==========
def store_message_temp(user_id, message: str):
    """Store message persistently for a given user_id."""
    data = load_json(MESSAGE_FILE)
    data[user_id] = message
    save_json(MESSAGE_FILE, data)
    app.logger.info(f"[store_message] Stored message for user_id={user_id}")
    return True, None


def get_and_delete_message(user_id):
    """Retrieve and delete stored message for a given user_id."""
    data = load_json(MESSAGE_FILE)
    message = data.pop(user_id, None)
    if message:
        save_json(MESSAGE_FILE, data)
        return message, None
    return None, "No message found"


# ========== Persistent attempt tracking ==========
def get_attempts(email):
    data = load_json(ATTEMPT_TRACKER_FILE)
    return data.get(email, 0)


def increment_attempt(email):
    data = load_json(ATTEMPT_TRACKER_FILE)
    count = data.get(email, 0) + 1
    data[email] = count
    save_json(ATTEMPT_TRACKER_FILE, data)
    return count


def reset_attempt(email):
    data = load_json(ATTEMPT_TRACKER_FILE)
    data[email] = 0
    save_json(ATTEMPT_TRACKER_FILE, data)


# ========== External user lookup ==========
def fetch_user_id_by_email(email: str):
    try:
        resp = requests.get(EXTERNAL_LOOKUP_BASE, params={"email": email}, timeout=10)
        if resp.status_code != 200:
            return None, f"lookup failed: {resp.status_code}"
        data = resp.json()

        user_id = (
            data.get("id")
            or data.get("userId")
            or (data.get("user") or {}).get("id")
            or (data.get("data") or {}).get("id")
            or (data.get("result") or {}).get("id")
        )
        return user_id, None
    except Exception as e:
        return None, str(e)


# ========== Simulated notification ==========
def send_in_app_message(user_id, message: str):
    """Simulate in-app notification and store message persistently."""
    app.logger.warning(f"[notify] user_id={user_id} message={message}")
    store_message_temp(user_id, message)
    return True, None


# ========== API Routes ==========
@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/login")
def login():
    """Login simulation with persistent 3-attempt tracking."""
    data = request.get_json(force=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    wrong_attempts = increment_attempt(email)
    if wrong_attempts == 3:
        reset_attempt(email)

        ext_user_id, lookup_err = fetch_user_id_by_email(email)

        notify_status, notify_error = (None, None)
        if ext_user_id:
            notify_status, notify_error = send_in_app_message(
                ext_user_id,
                "⚠ WARNING: 3 wrong login attempts detected for your account!"
            )

        return jsonify({
            "error": "Invalid password",
            "attempts": 3,
            "external_user_id": ext_user_id,
            "external_lookup_error": lookup_err,
            "notify_sent": bool(notify_status),
            "notify_error": notify_error,
        }), 403

    return jsonify({"error": "Invalid password", "attempts": wrong_attempts}), 403


@app.get("/get-message")
def get_message():
    """Return and delete stored message for the given user_id."""
    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"error": "userId query parameter is required"}), 400

    message, err = get_and_delete_message(user_id)
    if message:
        return jsonify({"user_id": user_id, "message": message}), 200
    else:
        return jsonify({"error": err, "user_id": user_id}), 404


# ========== Run ==========
if _name_ == "_main_":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)

