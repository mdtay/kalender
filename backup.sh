#!/bin/bash
BACKUP_DIR="/mnt/kalender/backups"
DB_PATH="/home/tay/kalender/kalender.db"
DATE=$(date +%Y-%m-%d)
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"
cp "$DB_PATH" "$BACKUP_DIR/kalender_${DATE}.db"
find "$BACKUP_DIR" -name "kalender_*.db" -mtime +${KEEP_DAYS} -delete

echo "$(date): Backup erstellt: $BACKUP_DIR/kalender_${DATE}.db"
