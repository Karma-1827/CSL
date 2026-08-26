#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this wrapper with sudo." >&2
  exit 2
fi

stamp="$(date +%Y%m%d_%H%M%S)_$$"
database="mpts_loadtest_${stamp}"
unit="mpts-loadtest-${stamp//_/-}"
runner="/var/tmp/mpts-loadtest/isolated_vm_loadtest.py"
loadtest_mode="full"

if [[ "${1:-}" == "--post-only" ]]; then
  loadtest_mode="post-only"
elif [[ "${1:-}" == "--300-only" ]]; then
  loadtest_mode="300-only"
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--post-only|--300-only]" >&2
  exit 2
fi

if [[ ! -r "${runner}" ]]; then
  echo "Missing ${runner}" >&2
  exit 2
fi

cleanup() {
  sudo -u postgres dropdb --if-exists --force "${database}" >/dev/null 2>&1 || true
  systemctl reset-failed "${unit}.service" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Creating disposable database ${database}..."
sudo -u postgres createdb --owner=mpts_app "${database}"

echo "Starting isolated MPTS load test..."
systemd-run \
  --quiet --wait --pipe --collect \
  --unit="${unit}" \
  --uid=mpts --gid=mpts \
  --working-directory=/opt/mpts \
  --property="EnvironmentFile=/opt/mpts/.env" \
  --property="RuntimeMaxSec=20min" \
  /usr/bin/env \
  "POSTGRES_DB=${database}" \
  "DJANGO_DEBUG=0" \
  "MPTS_LOADTEST_MODE=${loadtest_mode}" \
  /opt/mpts/.venv/bin/python "${runner}"

echo "Isolated load test completed; disposable database will now be removed."
