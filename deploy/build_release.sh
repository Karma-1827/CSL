#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-${ROOT_DIR}/output/releases}"
VERSION="${2:-$(date +%Y%m%d-%H%M%S)}"
INCLUDE_PRIVATE_ASSETS="${INCLUDE_PRIVATE_ASSETS:-0}"
STAGE_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${STAGE_DIR}"
}
trap cleanup EXIT

command -v rsync >/dev/null || { echo "rsync is required." >&2; exit 1; }
command -v zip >/dev/null || { echo "zip is required." >&2; exit 1; }

mkdir -p "${OUTPUT_DIR}" "${STAGE_DIR}/mpts"
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
ARCHIVE_PATH="${OUTPUT_DIR}/mpts-${VERSION}.zip"

copy_item() {
  local item="$1"
  local destination="${STAGE_DIR}/mpts/$(dirname "${item}")"
  mkdir -p "${destination}"
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='Icon?' \
    --exclude='*.doc' \
    --exclude='*.docx' \
    "${ROOT_DIR}/${item}" "${destination}/"
}

for item in \
  accounts config tutoring templates static deploy \
  manage.py requirements.txt requirements-dev.txt pyproject.toml \
  README.md CLAUDE.md .env.example .gitignore
do
  copy_item "${item}"
done

for document in \
  "docs/DEPLOY.md" \
  "docs/PROGRESS.md" \
  "docs/SECURITY_CHECKLIST.md" \
  "docs/PRE_DEPLOYMENT_CHECK_2026-08-17.md"
do
  copy_item "${document}"
done

# Openly distributable fallback fonts are always included. The licensed LiSong/
# Helvetica files and internal department stamp are only added for an authorized,
# private VM transfer when INCLUDE_PRIVATE_ASSETS=1 is explicitly set.
mkdir -p "${STAGE_DIR}/mpts/assets/fonts"
for font in \
  "assets/fonts/LICENSES.md" \
  "assets/fonts/TW-Kai.ttf" \
  "assets/fonts/LiberationSerif-Regular.ttf" \
  "assets/fonts/LiberationSerif-Bold.ttf"
do
  copy_item "${font}"
done

if [[ "${INCLUDE_PRIVATE_ASSETS}" == "1" ]]; then
  for private_asset in \
    "assets/fonts/DFLiSongStd-W3.ttf" \
    "assets/fonts/DFLiSongStd-W7.ttf" \
    "assets/fonts/Helvetica Neue Condensed Bold.ttf" \
    "assets/certificates/CSL stamp.png"
  do
    [[ -f "${ROOT_DIR}/${private_asset}" ]] || {
      echo "Required private deployment asset is missing: ${private_asset}" >&2
      exit 1
    }
    copy_item "${private_asset}"
  done
fi

mkdir -p "${STAGE_DIR}/mpts/media" "${STAGE_DIR}/mpts/staticfiles"
touch "${STAGE_DIR}/mpts/media/.gitkeep" "${STAGE_DIR}/mpts/staticfiles/.gitkeep"

{
  if git -C "${ROOT_DIR}" diff --quiet && git -C "${ROOT_DIR}" diff --cached --quiet; then
    working_tree_state="tracked files clean"
  else
    working_tree_state="contains reviewed working-tree changes"
  fi
  echo "MPTS deployment package"
  echo "Built at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Source commit: $(git -C "${ROOT_DIR}" rev-parse HEAD)"
  echo "Build state: ${working_tree_state}"
  echo "Private certificate assets included: ${INCLUDE_PRIVATE_ASSETS}"
  echo "Local database, media uploads, Demo data, .env secrets, caches and previews are excluded."
} > "${STAGE_DIR}/mpts/RELEASE_INFO.txt"

rm -f "${ARCHIVE_PATH}"
(
  cd "${STAGE_DIR}"
  zip -qr "${ARCHIVE_PATH}" mpts
)

echo "${ARCHIVE_PATH}"
