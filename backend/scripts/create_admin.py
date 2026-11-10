import sys
import argparse
from pathlib import Path
from getpass import getpass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlmodel import Session, select
from app.db.database import engine, init_db
from app.db.models import User
from app.services.auth_service import hash_password


def make_admin(email: str = None, password: str = None, full_name: str = "Super Admin"):
    init_db()

    if not email:
        email = input("Admin Email: ").strip()
    else:
        email = email.strip()

    if not email or "@" not in email:
        print("❌ Invalid email format.")
        sys.exit(1)

    if not password:
        password = getpass("Admin Password (min 8 chars): ").strip()

    if len(password) < 8:
        print("❌ Password must be at least 8 characters long.")
        sys.exit(1)

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.email == email.lower())).first()
        if existing:
            existing.is_admin = True
            existing.is_active = True
            existing.hashed_password = hash_password(password)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            print(f"✅ Successfully updated existing user '{existing.email}' to Super Admin.")
        else:
            admin = User(
                email=email.lower(),
                hashed_password=hash_password(password),
                full_name=full_name,
                is_admin=True,
                is_active=True,
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)
            print(f"✅ Successfully created new Super Admin account: '{admin.email}' (ID: {admin.id}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or promote an administrator account for TalentFlow AI.")
    parser.add_argument("--email", type=str, help="Admin email address")
    parser.add_argument("--password", type=str, help="Admin password (omit for interactive prompt)")
    parser.add_argument("--name", type=str, default="Super Admin", help="Full name for the admin user")

    args = parser.parse_args()
    make_admin(email=args.email, password=args.password, full_name=args.name)
