#!/usr/bin/env bash
# uninstall_service.sh — remove the powerdog system service and installed files
#
# Run with sudo from the deployed app directory (e.g. ~/PowerDog/):
#   sudo ./uninstall_service.sh

set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
STATE_FILE="${SCRIPT_DIR}/.install_state"

# ── helpers ───────────────────────────────────────────────────────────────────

confirm() {
    local prompt="$1"
    local response
    read -r -p "${prompt} [Y/n] " response
    [[ -z "${response}" || "${response,,}" == "y" ]]
}

ask() {
    local prompt="$1" default="$2" var_name="$3"
    local response
    read -r -p "  ${prompt} [${default}]: " response
    printf -v "${var_name}" '%s' "${response:-${default}}"
}

info()  { echo "  $*"; }
warn()  { echo "  WARNING: $*"; }
abort() { echo "Aborted."; exit 1; }

require_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "This script must be run with sudo:"
        echo "  sudo $0"
        exit 1
    fi
}

# ── preflight ─────────────────────────────────────────────────────────────────

require_root

# ── step 0: installation parameters ──────────────────────────────────────────

echo ""
echo "Powerdog service uninstaller"
echo ""
echo "[ Step 0 ] Installation parameters"
echo "  (Press Enter to accept the default shown in brackets.)"
echo ""

if [[ ! -f "${STATE_FILE}" ]]; then
    warn "No .install_state found at ${STATE_FILE}."
    warn "Verify the values below match your installation before proceeding."
    echo ""
fi

[[ -f "${STATE_FILE}" ]] && source "${STATE_FILE}"

ask "Service name"             "${SERVICE_NAME:-powerdog}"                                     SERVICE_NAME
SERVICE_FILE="${SERVICE_NAME}.service"

ask "App install directory"    "${INSTALL_APP_DIR:-/usr/share/${SERVICE_NAME}}"               INSTALL_APP_DIR
ask "Config directory"         "${INSTALL_CONF_DIR:-/etc/${SERVICE_NAME}}"                    INSTALL_CONF_DIR
ask "Runtime data directory"   "${INSTALL_DATA_DIR:-/var/lib/${SERVICE_NAME}}"                INSTALL_DATA_DIR
ask "Service file destination" "${INSTALL_SERVICE_DEST:-/etc/systemd/system/${SERVICE_FILE}}" INSTALL_SERVICE_DEST

echo ""
echo "  Service      : ${SERVICE_NAME}"
echo "  App files    : ${INSTALL_APP_DIR}"
echo "  Config       : ${INSTALL_CONF_DIR}"
echo "  Runtime data : ${INSTALL_DATA_DIR}"
echo "  Service file : ${INSTALL_SERVICE_DEST}"
echo "  System user  : ${SERVICE_NAME}"
echo ""

if ! confirm "Proceed with uninstall?"; then
    abort
fi
echo ""

# ── step 1: stop service ──────────────────────────────────────────────────────

echo "[ Step 1 ] Stop service"
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    if confirm "Stop '${SERVICE_NAME}' now?"; then
        systemctl stop "${SERVICE_NAME}"
        info "Service '${SERVICE_NAME}' stopped."
    else
        abort
    fi
else
    info "Service '${SERVICE_NAME}' is not running. Skipping."
fi
echo ""

# ── step 2: disable service ───────────────────────────────────────────────────

echo "[ Step 2 ] Disable service"
if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    if confirm "Disable '${SERVICE_NAME}' (remove from boot)?"; then
        systemctl disable "${SERVICE_NAME}"
        info "Service '${SERVICE_NAME}' disabled."
    else
        warn "Skipped. The service will start again on next boot."
    fi
else
    info "Service '${SERVICE_NAME}' is not enabled. Skipping."
fi
echo ""

# ── step 3: remove service file ───────────────────────────────────────────────

echo "[ Step 3 ] Service file  →  ${INSTALL_SERVICE_DEST}"
if [[ -f "${INSTALL_SERVICE_DEST}" ]]; then
    if confirm "Remove ${INSTALL_SERVICE_DEST}?"; then
        rm "${INSTALL_SERVICE_DEST}"
        systemctl daemon-reload
        info "Service file removed and systemd reloaded."
    else
        warn "Skipped. The service file remains at ${INSTALL_SERVICE_DEST}."
    fi
else
    info "No service file found at ${INSTALL_SERVICE_DEST}. Skipping."
fi
echo ""

# ── step 4: remove app files ──────────────────────────────────────────────────

echo "[ Step 4 ] App files  →  ${INSTALL_APP_DIR}"
if [[ -d "${INSTALL_APP_DIR}" ]]; then
    if confirm "Remove ${INSTALL_APP_DIR} and all contents?"; then
        rm -rf "${INSTALL_APP_DIR}"
        info "Removed ${INSTALL_APP_DIR}."
    else
        warn "Skipped. App files remain at ${INSTALL_APP_DIR}."
    fi
else
    info "No app directory found at ${INSTALL_APP_DIR}. Skipping."
fi
echo ""

# ── step 5: remove config ─────────────────────────────────────────────────────

echo "[ Step 5 ] Config  →  ${INSTALL_CONF_DIR}"
if [[ -d "${INSTALL_CONF_DIR}" ]]; then
    warn "This will permanently delete ${INSTALL_CONF_DIR} and any customised config inside it."
    if confirm "Remove ${INSTALL_CONF_DIR}?"; then
        rm -rf "${INSTALL_CONF_DIR}"
        info "Removed ${INSTALL_CONF_DIR}."
    else
        warn "Skipped. Config remains at ${INSTALL_CONF_DIR}."
    fi
else
    info "No config directory found at ${INSTALL_CONF_DIR}. Skipping."
fi
echo ""

# ── step 6: remove runtime data ───────────────────────────────────────────────

echo "[ Step 6 ] Runtime data  →  ${INSTALL_DATA_DIR}"
if [[ -d "${INSTALL_DATA_DIR}" ]]; then
    warn "This will permanently delete ${INSTALL_DATA_DIR} and all runtime data inside it."
    if confirm "Remove ${INSTALL_DATA_DIR}?"; then
        rm -rf "${INSTALL_DATA_DIR}"
        info "Removed ${INSTALL_DATA_DIR}."
    else
        warn "Skipped. Runtime data remains at ${INSTALL_DATA_DIR}."
    fi
else
    info "No data directory found at ${INSTALL_DATA_DIR}. Skipping."
fi
echo ""

# ── step 7: remove system user ────────────────────────────────────────────────

echo "[ Step 7 ] System user  →  ${SERVICE_NAME}"
if id "${SERVICE_NAME}" &>/dev/null; then
    if confirm "Remove system user '${SERVICE_NAME}'?"; then
        userdel "${SERVICE_NAME}"
        info "Removed system user '${SERVICE_NAME}'."
    else
        warn "Skipped. System user '${SERVICE_NAME}' remains."
    fi
else
    info "System user '${SERVICE_NAME}' does not exist. Skipping."
fi
echo ""

# ── step 8: remove install state ─────────────────────────────────────────────

echo "[ Step 8 ] Install state  →  ${STATE_FILE}"
if [[ -f "${STATE_FILE}" ]]; then
    if confirm "Remove saved install parameters (${STATE_FILE})?"; then
        rm "${STATE_FILE}"
        info "Removed ${STATE_FILE}."
    else
        info "Kept ${STATE_FILE}."
    fi
else
    info "No install state file found. Skipping."
fi

echo ""
echo "Done."
