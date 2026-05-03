#!/usr/bin/env bash
# Backup pillywiggins PostgreSQL database via docker compose exec.
#
# Usage:
#   ./scripts/backup-db.sh              # backup to ./backups/ with timestamp
#   ./scripts/backup-db.sh /path/to/    # backup to custom directory
#
# Outputs:
#   - ./backups/pillywiggins_YYYY-MM-DD_HH-MM-SS.sql.gz (compressed SQL dump)
#   - symlink ./backups/pillywiggins_latest.sql.gz → most recent backup
#
# Cron example (run at 3 AM daily):
#   0 3 * * * cd /path/to/pillywiggins && ./scripts/backup-db.sh >> /var/log/pillywiggins-backup.log 2>&1

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yaml}"
BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="${BACKUP_DIR}/pillywiggins_${TIMESTAMP}.sql.gz"
LATEST_LINK="${BACKUP_DIR}/pillywiggins_latest.sql.gz"
KEEP_DAYS="${KEEP_DAYS:-14}"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

# Check if postgres service is running
if ! docker compose -f "$COMPOSE_FILE" ps postgres | grep -q "running\|Up"; then
    echo "ERROR: postgres service is not running" >&2
    exit 1
fi

# Run pg_dump inside the postgres container and stream to compressed file
echo "Starting backup at ${TIMESTAMP}..."
docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U pillywiggins -d pillywiggins \
    --clean --if-exists --no-owner --no-privileges \
    | gzip > "$BACKUP_FILE"

# Update latest symlink
rm -f "$LATEST_LINK"
ln -s "$(basename "$BACKUP_FILE")" "$LATEST_LINK"

# Clean up old backups
if command -v find >/dev/null 2>&1; then
    echo "Removing backups older than ${KEEP_DAYS} days..."
    find "$BACKUP_DIR" -name "pillywiggins_*.sql.gz" -type f -mtime +"$KEEP_DAYS" -delete
fi

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup complete: ${BACKUP_FILE} (${BACKUP_SIZE})"
