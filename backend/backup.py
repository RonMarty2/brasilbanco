import sqlite3
from datetime import datetime
from pathlib import Path

import database as db

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "storage" / "respaldos"
MAX_RESPALDOS = 30


def respaldar() -> Path:
    """Crea una copia en caliente de la base SQLite usando conn.backup() y conserva los últimos 30 respaldos."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    nombre = f"remesas_{datetime.now().strftime('%Y-%m-%d_%H%M')}.db"
    destino = BACKUP_DIR / nombre

    src = db.get_db_connection()
    dst = sqlite3.connect(str(destino))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    respaldos = sorted(
        BACKUP_DIR.glob("remesas_*.db"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    for antiguo in respaldos[MAX_RESPALDOS:]:
        try:
            antiguo.unlink()
        except OSError:
            pass

    return destino
