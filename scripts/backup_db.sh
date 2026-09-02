#!/usr/bin/env bash
# Daily SQLite backup. Schedule with cron, e.g.:
#   0 3 * * * /path/to/VPN\ MARSI/scripts/backup_db.sh >> /var/log/vpnmarsi_backup.log 2>&1
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_FILE="$PROJECT_DIR/vpn_marsi.db"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

if [ -f "$DB_FILE" ]; then
  cp "$DB_FILE" "$BACKUP_DIR/vpn_marsi_${TIMESTAMP}.db"
  find "$BACKUP_DIR" -name 'vpn_marsi_*.db' -mtime +30 -delete
  echo "Backup created: vpn_marsi_${TIMESTAMP}.db"
else
  echo "DB file not found at $DB_FILE" >&2
  exit 1
fi
