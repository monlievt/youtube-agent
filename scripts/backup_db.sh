#!/bin/bash
# scripts/backup_db.sh
# Backup MySQL database ke NFS.
# Sesuai blueprint: daily backup ke /NAS/Backups/db/YYYY-MM-DD.sql.gz
# Retention: 30 hari

set -euo pipefail

# Load dari .env jika ada
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

BACKUP_DIR="${NFS_BACKUPS_PATH:-/mnt/omv-backups}/db"
DATE=$(date +%Y-%m-%d)
FILENAME="${BACKUP_DIR}/${DATE}.sql.gz"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup..."

# Dump dan kompres
docker compose exec -T db \
    mysqldump \
    -u "${MYSQL_USER:-hermes_user}" \
    "-p${MYSQL_PASSWORD}" \
    "${MYSQL_DATABASE:-hermes}" \
    --single-transaction \
    --routines \
    --triggers \
    | gzip > "$FILENAME"

SIZE=$(du -h "$FILENAME" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup selesai: $FILENAME ($SIZE)"

# Hapus backup lama (> RETENTION_DAYS hari)
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup: hapus backup lebih dari $RETENTION_DAYS hari"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done."
