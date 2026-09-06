"""
Authentication for verifier accounts.

Uses werkzeug's password hashing (already a Flask dependency, no new
package needed) and Flask's built-in session (signed cookie) rather than
pulling in a full auth framework - appropriate at pilot scale, and the
one thing that matters most (never storing a plain-text password, never
letting an unauthenticated request record a verification) is covered.
"""

from functools import wraps

from flask import session, redirect, url_for, request
from werkzeug.security import generate_password_hash, check_password_hash


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, plain)


def current_user_id():
    return session.get("verifier_id")


def current_user_name():
    return session.get("verifier_name")


def current_user_role():
    return session.get("verifier_role")


def login_required(view_func):
    """Redirects to /login if no verifier is signed in, preserving where
    they were trying to go so they land back there after logging in."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user_id():
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped