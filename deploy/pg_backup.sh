#!/usr/bin/env bash
# Runs ON the Raspberry Pi via cron (installed by pi-setup.sh). Dumps the
# live Postgres database to a timestamped, compressed file and prunes
# anything older than 14 days, so there is always a recent, restorable
# backup regardless of what future failure mode ever damages the live
# database — the lesson from 2026-09-21's SQLite corruption saga.
set -euo pipefail

BACKUP_DIR="/home/xpair/aci/backend/db_backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILE="$BACKUP_DIR/aci_${TIMESTAMP}.sql.gz"

PGPASSWORD=aci pg_dump -h localhost -U aci -d aci | gzip > "$FILE"

# Keep 14 days of history — plenty to recover from anything short of a
# problem that went unnoticed for two full weeks.
find "$BACKUP_DIR" -name "aci_*.sql.gz" -mtime +14 -delete

echo "$(date -Iseconds) backup ok: $FILE ($(du -h "$FILE" | cut -f1))"
