#!/usr/bin/env bash
# Local daily backup for MPTS: PostgreSQL dump + media/ archive (docs/DEPLOY.md
# "備份與還原" / docs/VM_UPDATE_WORKFLOW.md 6.1). Intended to run as root via
# deploy/systemd/mpts-backup.service + .timer, not interactively.
#
# IMPORTANT — this is a LOCAL-DISK backup only. It protects against application-level
# mistakes (bad migration, accidental deletion, bad deploy) but NOT against loss of the
# VM or its system disk, since /var/backups/mpts lives on the same disk as everything
# else (`lsblk` on the 2026-08-17 handoff VM shows only the single 150GB system disk —
# the "600G backup HD" mentioned in the IT Center's allocation email is not attached to
# this VM as a block device, so it is presumably part of the Center's own separately
# managed quarterly full-VM backup, not something this script can write to). Copying
# these backups to a genuinely separate location (NFS, off-site) is still an open item —
# see docs/DEPLOY.md "上線前仍待確認".
#
# Stored outside /opt/mpts and owned by root so that the unprivileged `mpts` application
# service account (which the app runs as, and which has no sudo) cannot read, modify, or
# delete backups even if the application itself were compromised — matches "備份帳號與
# 應用程式帳號分離，採最小權限" (docs/DEPLOY.md 5.3 / VULNERABILITY_SCAN_IMPROVEMENTS.md).

set -euo pipefail

APP_DIR="/opt/mpts"
BACKUP_ROOT="/var/backups/mpts"
RETENTION_DAYS="${MPTS_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_ROOT}/${TIMESTAMP}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must run as root (needs to read /opt/mpts/media owned by mpts, and" >&2
  echo "run pg_dump as the postgres OS role)." >&2
  exit 1
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo "Cannot find ${APP_DIR}/.env — is APP_DIR correct?" >&2
  exit 1
fi

# Read POSTGRES_DB without exporting the whole .env (it also holds SECRET_KEY/passwords
# we don't need here and shouldn't pull into this process's environment needlessly).
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' "${APP_DIR}/.env" | head -1 | cut -d= -f2-)"
if [[ -z "${POSTGRES_DB}" ]]; then
  echo "POSTGRES_DB not found in ${APP_DIR}/.env" >&2
  exit 1
fi

mkdir -p "${DEST}"
chmod 700 "${BACKUP_ROOT}" "${DEST}"

echo "[$(date -Iseconds)] Dumping database '${POSTGRES_DB}'..."
# Custom format (-Fc): compressed, supports selective/parallel restore via pg_restore.
# Runs as the `postgres` OS user, which peer-authenticates locally as the Postgres
# superuser (see pg_hba.conf `local all postgres peer`) — no application DB password
# needed or read here. Deliberately `> file` instead of pg_dump's own `-f`: `-f` would
# have pg_dump itself (running as `postgres`) open the file, which fails against
# BACKUP_ROOT's root-only 700 permissions; shell redirection opens the file as root
# (this script's own euid) before exec'ing the sudo'd pg_dump, so pg_dump just inherits
# an already-writable fd on stdout.
sudo -u postgres pg_dump -Fc -d "${POSTGRES_DB}" > "${DEST}/db.dump"

echo "[$(date -Iseconds)] Archiving media/..."
tar -czf "${DEST}/media.tar.gz" -C "${APP_DIR}" media

chmod 600 "${DEST}/db.dump" "${DEST}/media.tar.gz"

echo "[$(date -Iseconds)] Backup written to ${DEST}:"
du -sh "${DEST}/db.dump" "${DEST}/media.tar.gz"

echo "[$(date -Iseconds)] Pruning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" -print -exec rm -rf {} \;

echo "[$(date -Iseconds)] Done. Current backups:"
ls -1 "${BACKUP_ROOT}"
