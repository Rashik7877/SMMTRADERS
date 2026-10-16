"""Generate a salted scrypt hash for ADMIN_PASSWORD_HASH.

Usage:
    python scripts/hash_password.py

Prompts for the password twice, prints the value to paste into your
environment variables (Vercel project settings or local .env).
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth  # noqa: E402


def main() -> int:
    print("SMMTRADERS SuperAdmin password hasher")
    print("-" * 42)
    password = getpass.getpass("Password: ")
    if not password:
        print("No password entered; nothing generated.", file=sys.stderr)
        return 1
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    if len(password) < 8:
        print(
            "Warning: password shorter than 8 characters is not recommended.",
            file=sys.stderr,
        )
    print()
    print("ADMIN_USERNAME=SMMTRADERS")
    print(f"ADMIN_PASSWORD_HASH={auth.hash_password(password)}")
    print()
    print(
        "Set these in your .env file or in Vercel "
        "(Project Settings -> Environment Variables), then redeploy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
