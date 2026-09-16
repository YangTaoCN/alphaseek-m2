#!/usr/bin/env bash
# Install / uninstall the AlphaSeek-M2 launchd job (weekdays 16:15 local time).
#
#   ./deploy/install_launchd.sh            # install (or reinstall)
#   ./deploy/install_launchd.sh --uninstall
#   ./deploy/install_launchd.sh --dry-run  # print the generated plist only
set -euo pipefail

LABEL="com.alphaseek.m2.scan"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="${PROJECT_DIR}/deploy/${LABEL}.plist"
TARGET_DIR="${HOME}/Library/LaunchAgents"
TARGET="${TARGET_DIR}/${LABEL}.plist"
PYTHON="${PROJECT_DIR}/venv/bin/python"
ACTION="${1:-install}"

if [[ ! -x "${PYTHON}" ]]; then
  echo "!! No virtualenv interpreter at ${PYTHON}" >&2
  echo "   Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

render() {
  sed -e "s|__PYTHON__|${PYTHON}|g" -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" "${TEMPLATE}"
}

case "${ACTION}" in
  --uninstall)
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || launchctl unload "${TARGET}" 2>/dev/null || true
    rm -f "${TARGET}"
    echo "Uninstalled ${LABEL}"
    ;;
  --dry-run)
    render
    ;;
  *)
    mkdir -p "${TARGET_DIR}" "${PROJECT_DIR}/logs"
    render > "${TARGET}"
    plutil -lint "${TARGET}" >/dev/null
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "${TARGET}" 2>/dev/null || launchctl load "${TARGET}"
    echo "Installed ${LABEL}"
    echo "  plist:  ${TARGET}"
    echo "  python: ${PYTHON}"
    echo "  logs:   ${PROJECT_DIR}/logs/launchd.{out,err}.log"
    echo
    echo "Trigger a test run now:  launchctl kickstart -k gui/$(id -u)/${LABEL}"
    echo "Check status:            launchctl print gui/$(id -u)/${LABEL} | head -20"
    ;;
esac
