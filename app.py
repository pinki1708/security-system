import os
from flask import Flask, request, jsonify, session
import bcrypt
import requests  # NEW: for calling external API

app = Flask(__name__)

# Secret key for Flask sessions (set via env on Render)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

# Demo user store: replace with your database integration
USERS = {
    "user@example.com": {
        "password_hash": bcrypt.hashpw(b"SuperSecurePassword", bcrypt.gensalt()),
        "email": "user@example.com"
    }
}

EXTERNAL_LOOKUP_BASE = "https://super-duper-carnival.onrender.com/api/users/by-email"

def fetch_user_id_by_email(email: str):
    """
    Calls external service to fetch user id by email.
    Expected JSON should contain the id somewhere. Adjust parsing as per actual shape.
    """
    try:
        resp = requests.get(EXTERNAL_LOOKUP_BASE, params={"email": email}, timeout=120)
        if resp.status_code != 200:
            return None, f"lookup non-200: {resp.status_code}"
        data = resp.json()
        # Adjust these keys as per your API's real response
        user_id = data.get("id") or data.get("userId") or data.get("user", {}).get("id")
        if not user_id:
            return None, "id not found in response"
        return user_id, None
    except Exception as e:
        return None, f"lookup error: {e}"

def send_in_app_message(user_id, message: str):
    """
    Placeholder for pushing an in-app alert/message to a specific user_id.
    TODO: Replace with your real notification pipeline (WebSocket/SSE/notifications API/DB insert).
    """
    try:
        # Example placeholder (log or call your internal notification API here)
        print(f"[notify] user_id={user_id} message={message}")
        return True, None
    except Exception as e:
        return False, str(e)

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.post("/login")
def login():
    data = request.get_json(force=True)
    email = data.get("email")
    password = data.get("password")

    user = USERS.get(email)
    if not user:
        return jsonify({"error": "User not found"}), 404

    attempts_key = f"wrong_attempts_{email}"
    wrong_attempts = session.get(attempts_key, 0)

    if not bcrypt.checkpw(password.encode(), user["password_hash"]):
        wrong_attempts += 1
        session[attempts_key] = wrong_attempts

        if wrong_attempts == 3:
            session[attempts_key] = 0

            # NEW: 1) external lookup to get userId by email
            ext_user_id, lookup_err = fetch_user_id_by_email(email)

            # NEW: 2) send in-app message for that userId
            notify_status, notify_error = (None, None)
            if ext_user_id:
                notify_status, notify_error = send_in_app_message(
                    ext_user_id,
                    "WARNING: 3 wrong login attempts detected for your account!"
                )

            # Respond including external user id and notify status for visibility
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

    session[attempts_key] = 0
    return jsonify({"success": True, "message": "Logged in successfully"}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)


