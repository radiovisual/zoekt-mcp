"""Tiny Flask app used as a verification corpus for zoekt-mcp.

Intentionally kept close in shape to examples/express-app/index.js so
cross-language Zoekt queries like ``sym:users`` should surface matches
in both files.
"""

from flask import Flask, jsonify

app = Flask(__name__)

USERS = [
    {"id": 1, "name": "ada", "role": "admin"},
    {"id": 2, "name": "grace", "role": "editor"},
    {"id": 3, "name": "linus", "role": "viewer"},
]


@app.route("/")
def hello():
    return "Hello from flask-app!"


@app.route("/users")
def list_users():
    return jsonify({"users": USERS, "count": len(USERS)})


@app.route("/users/<int:user_id>")
def get_user(user_id: int):
    for user in USERS:
        if user["id"] == user_id:
            return jsonify(user)
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
