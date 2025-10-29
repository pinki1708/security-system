import os
from flask import Flask, request, jsonify, session
import bcrypt

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
            return jsonify({
                "error": "Invalid password",
                "attempts": 3,
                "notification": "WARNING: 3 wrong login attempts detected for your account!"
            }), 403

        return jsonify({"error": "Invalid password", "attempts": wrong_attempts}), 403

    session[attempts_key] = 0
    return jsonify({"success": True, "message": "Logged in successfully"}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
