#!/bin/bash
BACKUP_DIR="/mnt/kalender/backups"
DB_PATH="/home/tay/kalender/kalender.db"
DATE=$(date +%Y-%m-%d)
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"
# SQLite-Backup statt cp: liefert auch dann eine konsistente Kopie, wenn die
# App gerade in die Datenbank schreibt.
python3 - "$DB_PATH" "$BACKUP_DIR/kalender_${DATE}.db" <<'EOF'
import sqlite3, sys
quelle = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
ziel = sqlite3.connect(sys.argv[2])
quelle.backup(ziel)
pruefung = ziel.execute("PRAGMA integrity_check").fetchone()[0]
ziel.close()
quelle.close()
if pruefung != "ok":
    sys.exit(f"Integritaetspruefung der Sicherung fehlgeschlagen: {pruefung}")
EOF
find "$BACKUP_DIR" -name "kalender_*.db" -mtime +${KEEP_DAYS} -delete

echo "$(date): Backup erstellt: $BACKUP_DIR/kalender_${DATE}.db"
