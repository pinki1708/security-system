import os
from flask import Flask, request, jsonify, session
import requests

app = Flask(__name__)

# Secret key for Flask sessions (required for attempt tracking)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

# Your external user-lookup API
EXTERNAL_LOOKUP_BASE = "https://super-duper-carnival.onrender.com/api/users/by-email"

def fetch_user_id_by_email(email: str):
    """
    Fetch user id from external service using email.
    - 120s timeout (as requested) to tolerate inactive/cold services.
    - 1 retry in case the first attempt hits a cold start.
    - Logs payload to confirm JSON shape.
    """
    try:
        last_err = None
        for _ in range(2):  # one retry
            resp = requests.get(EXTERNAL_LOOKUP_BASE, params={"email": email}, timeout=120)
            if resp.status_code != 200:
                last_err = f"lookup non-200: {resp.status_code}"
                continue
            data = resp.json()
            app.logger.info(f"[lookup] payload for {email}: {data}")

            # Try common shapes; adjust if your API differs
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
        return None, last_err or "lookup failed"
    except Exception as e:
        return None, f"lookup error: {e}"

def send_in_app_message(user_id, message: str):
    """
    Placeholder: push an in-app alert to this user_id.
    Replace with your real pipeline (WebSocket/SSE/notifications API/DB insert).
    """
    try:
        app.logger.warning(f"[notify] user_id={user_id} message={message}")
        return True, None
    except Exception as e:
        return False, str(e)

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.post("/login")
def login():
    """
    No local DB validation here. This endpoint only demonstrates:
    - Counting wrong attempts per email using Flask session.
    - On the 3rd wrong attempt: call external API (120s timeout) to get user_id,
      then send an in-app message to that user_id.
    """
    data = request.get_json(force=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    attempts_key = f"wrong_attempts_{email}"
    wrong_attempts = session.get(attempts_key, 0) + 1
    session[attempts_key] = wrong_attempts

    if wrong_attempts == 3:
        session[attempts_key] = 0

        # 1) External lookup to get userId by email (120s timeout + retry)
        ext_user_id, lookup_err = fetch_user_id_by_email(email)

        # 2) Send in-app message for that userId
        notify_status, notify_error = (None, None)
        if ext_user_id:
            notify_status, notify_error = send_in_app_message(
                ext_user_id,
                "WARNING: 3 wrong login attempts detected for your account!"
            )

        return jsonify({
            "error": "Invalid password",
            "attempts": 3,
            "external_user_id": ext_user_id,
            "external_lookup_error": lookup_err,
            "notify_sent": bool(notify_status),
            "notify_error": notify_error,
            "notification": "WARNING: 3 wrong login attempts detected for your account!"
        }), 403

    return jsonify({"error": "Invalid password", "attempts": wrong_attempts}), 403

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
