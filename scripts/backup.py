"""Consistent copy of the SQLite database (safe while the app runs). Keeps the last 30 backups.

Usage:  python -m scripts.backup [backup_dir]
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from app.config import BASE_DIR, get_settings

KEEP = 30


def main() -> None:
    db_path = Path(get_settings().database_url.removeprefix("sqlite:///"))
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"app-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(db_path) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    for old in sorted(out_dir.glob("app-*.db"))[:-KEEP]:
        old.unlink()
    print(f"Backup written to {target}")


if __name__ == "__main__":
    main()
