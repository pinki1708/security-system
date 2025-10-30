import os
import json
from flask import Flask, request, jsonify
import requests
import bcrypt  # ensure bcrypt in requirements

app = Flask(__name__)

# Render/Flask settings
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

# External user lookup API (returns user id by email)
EXTERNAL_LOOKUP_BASE = "https://super-duper-carnival.onrender.com/api/users/by-email"

# Demo persistence files (use Redis/DB in production)
MESSAGE_FILE = "messages.json"
ATTEMPT_TRACKER_FILE = "attempts.json"

# ---------- JSON utils ----------
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

# ---------- Message store (demo) ----------
def store_message_temp(user_id, message: str):
    data = load_json(MESSAGE_FILE)
    data[str(user_id)] = message
    save_json(MESSAGE_FILE, data)
    app.logger.info(f"[store_message] Stored message for user_id={user_id}")
    return True, None

def get_and_delete_message(user_id):
    data = load_json(MESSAGE_FILE)
    message = data.pop(str(user_id), None)
    if message:
        save_json(MESSAGE_FILE, data)
        return message, None
    return None, "No message found"

# ---------- Attempts tracking (demo) ----------
def get_attempts(email):
    data = load_json(ATTEMPT_TRACKER_FILE)
    return int(data.get(email, 0))

def increment_attempt(email):
    data = load_json(ATTEMPT_TRACKER_FILE)
    count = int(data.get(email, 0)) + 1
    data[email] = count
    save_json(ATTEMPT_TRACKER_FILE, data)
    return count

def reset_attempt(email):
    data = load_json(ATTEMPT_TRACKER_FILE)
    data[email] = 0
    save_json(ATTEMPT_TRACKER_FILE, data)

# ---------- External user lookup ----------
def fetch_user_id_by_email(email: str):
    try:
        # Use 120s timeout to tolerate inactive/cold services
        resp = requests.get(EXTERNAL_LOOKUP_BASE, params={"email": email}, timeout=120)
        if resp.status_code != 200:
            return None, f"lookup failed: {resp.status_code}"
        data = resp.json()
        app.logger.info(f"[lookup] payload for {email}: {data}")

        # Try common shapes; adjust to your API's actual JSON
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

# ---------- Notification trigger (wire to your real pipeline) ----------
def send_in_app_message(user_id, message: str):
    # Replace this with your real notifier: Socket.IO emit, SSE push, or Notifications API/DB insert
    app.logger.warning(f"[notify] user_id={user_id} message={message}")
    store_message_temp(user_id, message)
    return True, None

# ---------- Your DB lookup for user + hash ----------
def get_user_from_db(email: str):
    """
    Replace this with your real DB query.
    Must return dict like: { "id": 123, "email": "...", "password_hash": "<bcrypt-hash-string>" }
    """
    # Example:
    # row = db.fetch_one("SELECT id, email, password_hash FROM users WHERE email=%s", (email,))
    # if not row: return None
    # return {"id": row["id"], "email": row["email"], "password_hash": row["password_hash"]}
    return None  # placeholder; implement with your DB

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
    Correct flow:
    1) Fetch user from YOUR DB (must include bcrypt hash).
    2) Verify password using bcrypt.checkpw.
    3) If correct: reset attempts and return success.
    4) If wrong: increment attempts; on 3rd, fetch external userId and send in-app alert.
    """
    data = request.get_json(force=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    # 1) Fetch user from your DB
    user = get_user_from_db(email)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # 2) Verify password with bcrypt
    try:
        stored_hash = user.get("password_hash")
        # Ensure bytes for checkpw
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode("utf-8")
        ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash)
    except Exception as e:
        app.logger.error(f"[hash] error for {email}: {e}")
        return jsonify({"error": "Server hash error"}), 500

    if ok:
        # 3) Success → reset attempts
        reset_attempt(email)
        return jsonify({"success": True, "message": "Logged in successfully"}), 200

    # 4) Wrong password → increment attempts
    wrong_attempts = increment_attempt(email)

    if wrong_attempts == 3:
        reset_attempt(email)

        # External user lookup to get userId by email
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

if __name__ == "__main__":
    # Render-ready binding
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
