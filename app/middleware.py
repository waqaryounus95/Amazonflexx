import os
import jwt
from datetime import datetime
from flask import request, jsonify, abort

def simple_middleware(app):
    """
    Registers a before-request middleware that verifies a JWT token.
    Public endpoints (like signup, login, auto_start, favicon) bypass token verification.
    """

    @app.before_request
    def jwt_middleware():
        if request.method == 'OPTIONS':
            return

        public_paths = ['/signup', '/login','/accept_offer']
        if any(public in request.path for public in public_paths):
            return

        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': "Authorization Token is Required"}), 400

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return jsonify({'error': "Invalid Authorization header format"}), 401

        token = parts[1]
        try:
            secret_key = os.environ.get('SECRET_KEY', 'secret')
            decoded = jwt.decode(token, secret_key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except (jwt.InvalidTokenError) as e:
            return jsonify({'error': 'Invalid token'}), 401

        email = decoded.get('email')
        expiry = decoded.get('expiry')
        if not email or not expiry:
            return jsonify({'error': 'Invalid token payload'}), 401

        current_time = datetime.now().timestamp()
        if current_time > expiry:
            return jsonify({'error': 'Token has expired'}), 401

        request.authuser = email

    