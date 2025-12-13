"""
One-off helper: refresh Access Token for a token row by ID using stored ST (preferred) or RT,
then write the new AT + computed expiry_time back to SQLite.

Safety:
- Never prints AT/ST/RT to stdout.
- TokenManager logging has been redacted to avoid writing full tokens into logs.txt.

Usage:
  python3 scripts/refresh_token_by_id.py --id 42
  python3 scripts/refresh_token_by_id.py --id 42 --db /absolute/path/to/hancat.db
"""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Optional
import hashlib

# Ensure repo root is on sys.path so `import src...` works when running as a script
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.database import Database
from src.services.token_manager import TokenManager


def _parse_expires_fallback(expires: str) -> Optional[datetime]:
    """
    Best-effort parse for ISO-ish strings like:
      2025-12-20T22:55:21.000Z
      2025-12-20T22:55:21Z
      2025-12-20T22:55:21+00:00
    Returns **naive local-time** datetime for DB consistency.
    """
    if not expires:
        return None
    try:
        s = expires.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        # Normalize to naive local time for consistency with existing DB usage
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


async def _run(token_id: int, db_path: Optional[str]):
    db = Database(db_path=db_path)
    token_manager = TokenManager(db)

    token_row = await db.get_token(token_id)
    if not token_row:
        raise SystemExit(f"token_id={token_id} not found in DB: {db.db_path}")

    old_expiry = token_row.expiry_time
    email = getattr(token_row, "email", None)
    old_token = getattr(token_row, "token", None)
    old_hash = hashlib.sha256(old_token.encode("utf-8")).hexdigest()[:12] if old_token else None
    old_jwt_exp: Optional[datetime] = None
    if old_token:
        try:
            decoded_old = await token_manager.decode_jwt(old_token)
            if "exp" in decoded_old:
                old_jwt_exp = datetime.fromtimestamp(int(decoded_old["exp"]))  # naive local time
        except Exception:
            pass

    # Prefer ST; fallback to RT
    if token_row.st:
        result = await token_manager.st_to_at(token_row.st)
    elif token_row.rt:
        result = await token_manager.rt_to_at(token_row.rt, client_id=token_row.client_id)
    else:
        raise SystemExit(f"token_id={token_id} has neither ST nor RT; cannot refresh")

    new_at = result.get("access_token")
    if not new_at:
        raise SystemExit("Refresh did not return access_token")

    # Compute expiry_time primarily from JWT exp
    new_expiry: Optional[datetime] = None
    try:
        decoded = await token_manager.decode_jwt(new_at)
        if "exp" in decoded:
            new_expiry = datetime.fromtimestamp(int(decoded["exp"]))  # naive local time (matches existing code)
    except Exception:
        pass

    # If JWT decoding fails, fall back to 'expires' field (ST flow) when provided
    if new_expiry is None:
        new_expiry = _parse_expires_fallback(result.get("expires"))

    await db.update_token(token_id, token=new_at, expiry_time=new_expiry)
    updated = await db.get_token(token_id)
    new_hash = hashlib.sha256(new_at.encode("utf-8")).hexdigest()[:12]

    # Output only non-sensitive info
    print("✅ refreshed token")
    print(f"- token_id: {token_id}")
    print(f"- email: {email}")
    print(f"- db: {Path(db.db_path).resolve()}")
    print(f"- token_sha256_prefix (before): {old_hash}")
    print(f"- token_sha256_prefix (after):  {new_hash}")
    print(f"- jwt_exp (before): {old_jwt_exp.isoformat() if old_jwt_exp else None}")
    print(f"- jwt_exp (after):  {new_expiry.isoformat() if new_expiry else None}")
    print(f"- expiry_time (before): {old_expiry.isoformat() if old_expiry else None}")
    print(f"- expiry_time (after):  {updated.expiry_time.isoformat() if updated and updated.expiry_time else None}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, default=42, help="tokens.id to refresh")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="SQLite DB path (default uses src/core/database.py default: data/hancat.db)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args.id, args.db))


if __name__ == "__main__":
    main()


