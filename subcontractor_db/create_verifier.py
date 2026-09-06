"""
Creates a verifier account. Deliberately a terminal-only tool, not a web
form - letting anyone self-register as a verifier would defeat the whole
point of this rebuild (accountable, authenticated checks only).

Run this once to create your first ADMIN account, and again for each
person who'll actually be doing CIPC/CIDB checks.

Usage:
    python create_verifier.py
"""

import getpass
import os
import sqlite3
from datetime import datetime, timezone

import db
import auth

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subcontractors.db")


def main():
    print("=== Create a verifier account ===\n")
    db.init_db(DB_PATH)

    name = input("Full name: ").strip()
    email = input("Email (used to log in): ").strip().lower()

    role = ""
    while role not in ("ADMIN", "VERIFIER"):
        role = input("Role (ADMIN or VERIFIER): ").strip().upper()

    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("Passwords didn't match - nothing created.")
        return
    if len(password) < 8:
        print("Password should be at least 8 characters - nothing created.")
        return

    password_hash = auth.hash_password(password)

    conn = db.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO verifier_users (name, email, password_hash, role, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (name, email, password_hash, role, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        conn.commit()
        print(f"\nCreated {role} account for {name} ({email}).")
    except sqlite3.IntegrityError:
        print(f"\nA verifier with email {email} already exists - nothing created.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()