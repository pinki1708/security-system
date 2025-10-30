import os
import json
import requests
import bcrypt
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

EXTERNAL_LOOKUP_BASE = "https://super-duper-carnival.onrender.com/api/users/by-email"

# Demo persistence (use Redis/DB in production)
MESSAGE_FILE = "messages.json"
ATTEMPT_TRACKER_FILE = "attempts.json"

# ---------- helpers ----------
def norm_email(e: str) -> str:
    return (e or "").strip().lower()

# ---------- Postgres connection ----------
def get_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        dbname=os.getenv("PGDATABASE"),
        port=int(os.getenv("PGPORT", "5432")),
    )

def get_user_from_db(email: str):
    """
    Returns { id, email, password_hash } (case-insensitive email match).
    Ensure users.password_hash stores a full bcrypt hash string like $2b$...
    """
    email_norm = norm_email(email)
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, email, password_hash FROM users WHERE lower(email)=lower(%s) LIMIT 1",
                (email_norm,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"id": row["id"], "email": row["email"], "password_hash": row["password_hash"]}
    finally:
        conn.close()

# ---------- JSON utils (demo) ----------
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
    app.logger.info(f"[store_message] user_id={user_id}")
    return True, None

def get_and_delete_message(user_id):
    data = load_json(MESSAGE_FILE)
    message = data.pop(str(user_id), None)
    if message:
        save_json(MESSAGE_FILE, data)
        return message, None
    return None, "No message found"

# ---------- Attempts tracking (demo, file-based) ----------
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

# ---------- Notification trigger (wire to real pipeline) ----------
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
    Flow:
    - Fetch user from Postgres (id, email, password_hash) with case-insensitive email.
    - bcrypt.checkpw to verify.
    - On success: reset attempts.
    - On wrong: attempts++ ; on 3rd wrong, fetch external userId and notify.
    """
    data = request.get_json(force=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    user = get_user_from_db(email)
    if not user:
        # User truly not in DB; do not increment attempts for non-existent accounts
        return jsonify({"error": "User not found"}), 404

    stored_hash = user.get("password_hash")
    if not stored_hash:
        return jsonify({"error": "User hash missing"}), 500

    if isinstance(stored_hash, str):
        stored_hash_bytes = stored_hash.encode("utf-8")
    else:
        stored_hash_bytes = stored_hash

    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash_bytes)
    except Exception as e:
        app.logger.error(f"[hash] error for {email}: {e}")
        return jsonify({"error": "Server hash error"}), 500

    if ok:
        reset_attempt(email)
        return jsonify({"success": True, "message": "Logged in successfully"}), 200

    # Wrong password → increment attempts
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

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)

