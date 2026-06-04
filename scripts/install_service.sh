#!/usr/bin/env bash
# install_service.sh — install the powerdog system service
#
# Run with sudo from the deployed app directory (e.g. ~/PowerDog/):
#   sudo ./install_service.sh

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

generate_service_file() {
    cat <<EOF
[Unit]
Description=${SERVICE_NAME^} BLE to MQTT Client
After=network-online.target bluetooth.target
Wants=network-online.target bluetooth.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${INSTALL_DATA_DIR}
Environment=PYTHONPATH=${INSTALL_APP_DIR}/src
ExecStart=${INSTALL_APP_DIR}/.venv/bin/python ${INSTALL_APP_DIR}/src/${SERVICE_NAME}/app.py --config-file ${INSTALL_CONF_DIR}/config.ini
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF
}

# ── preflight ─────────────────────────────────────────────────────────────────

require_root

SOURCE_SRC="${SCRIPT_DIR}/src"
SOURCE_CONF="${SCRIPT_DIR}/config.ini"
SOURCE_REQS="${SCRIPT_DIR}/requirements.txt"

for f in "${SOURCE_SRC}" "${SOURCE_CONF}" "${SOURCE_REQS}"; do
    if [[ ! -e "$f" ]]; then
        echo "Error: required file/directory not found: ${f}"
        exit 1
    fi
done

# ── step 0: installation parameters ──────────────────────────────────────────

echo ""
echo "Powerdog service installer"
echo ""
echo "[ Step 0 ] Installation parameters"
echo "  (Press Enter to accept the default shown in brackets.)"
echo ""

# Load prior answers if available
[[ -f "${STATE_FILE}" ]] && source "${STATE_FILE}"

ask "Service name"             "${SERVICE_NAME:-powerdog}"                                     SERVICE_NAME
SERVICE_FILE="${SERVICE_NAME}.service"
SERVICE_USER="${SERVICE_NAME}"
SERVICE_GROUP="${SERVICE_NAME}"

ask "App install directory"    "${INSTALL_APP_DIR:-/usr/share/${SERVICE_NAME}}"               INSTALL_APP_DIR
ask "Config directory"         "${INSTALL_CONF_DIR:-/etc/${SERVICE_NAME}}"                    INSTALL_CONF_DIR
ask "Runtime data directory"   "${INSTALL_DATA_DIR:-/var/lib/${SERVICE_NAME}}"                INSTALL_DATA_DIR
ask "Service file destination" "${INSTALL_SERVICE_DEST:-/etc/systemd/system/${SERVICE_FILE}}" INSTALL_SERVICE_DEST

# Persist answers for next run
{
    echo "SERVICE_NAME=${SERVICE_NAME}"
    echo "INSTALL_APP_DIR=${INSTALL_APP_DIR}"
    echo "INSTALL_CONF_DIR=${INSTALL_CONF_DIR}"
    echo "INSTALL_DATA_DIR=${INSTALL_DATA_DIR}"
    echo "INSTALL_SERVICE_DEST=${INSTALL_SERVICE_DEST}"
} > "${STATE_FILE}"
chmod 600 "${STATE_FILE}"

echo ""
echo "  Service      : ${SERVICE_NAME}"
echo "  App source   : ${SOURCE_SRC}"
echo "  Install app  : ${INSTALL_APP_DIR}"
echo "  Install conf : ${INSTALL_CONF_DIR}/config.ini"
echo "  Runtime data : ${INSTALL_DATA_DIR}"
echo "  Service file : ${INSTALL_SERVICE_DEST}"
echo "  Run as user  : ${SERVICE_USER}"
echo ""

# ── step 1: create system user ────────────────────────────────────────────────

echo "[ Step 1 ] System user"
if id "${SERVICE_USER}" &>/dev/null; then
    info "User '${SERVICE_USER}' already exists. Skipping."
else
    if confirm "Create system user '${SERVICE_USER}' (no login shell, no home directory)?"; then
        useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
        info "Created system user '${SERVICE_USER}'."
    else
        abort
    fi
fi
echo ""

# ── step 2: bluetooth group membership ───────────────────────────────────────

echo "[ Step 2 ] Bluetooth group"
if groups "${SERVICE_USER}" | grep -qw bluetooth; then
    info "User '${SERVICE_USER}' is already in the bluetooth group. Skipping."
else
    if confirm "Add '${SERVICE_USER}' to the bluetooth group (required for BLE access)?"; then
        usermod -aG bluetooth "${SERVICE_USER}"
        info "Added '${SERVICE_USER}' to bluetooth group."
    else
        warn "Skipped. The service may fail to access BLE."
    fi
fi
echo ""

# ── step 3: install app files ────────────────────────────────────────────────

echo "[ Step 3 ] App files  →  ${INSTALL_APP_DIR}"
if confirm "Copy app source to ${INSTALL_APP_DIR} and build virtual environment?"; then
    mkdir -p "${INSTALL_APP_DIR}"
    rsync -a --delete "${SOURCE_SRC}" "${SOURCE_REQS}" "${INSTALL_APP_DIR}/"
    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_APP_DIR}"
    info "Copied source files."

    info "Creating virtual environment..."
    python3 -m venv "${INSTALL_APP_DIR}/.venv"

    info "Installing dependencies..."
    "${INSTALL_APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
    "${INSTALL_APP_DIR}/.venv/bin/pip" install --quiet --requirement "${INSTALL_APP_DIR}/requirements.txt"

    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_APP_DIR}/.venv"
    info "Virtual environment ready."
else
    abort
fi
echo ""

# ── step 4: install config ────────────────────────────────────────────────────

echo "[ Step 4 ] Config  →  ${INSTALL_CONF_DIR}/config.ini"
mkdir -p "${INSTALL_CONF_DIR}"
if [[ -f "${INSTALL_CONF_DIR}/config.ini" ]]; then
    info "Existing config found — keeping it (prior settings preserved)."
else
    cp "${SOURCE_CONF}" "${INSTALL_CONF_DIR}/config.ini"
    chmod 640 "${INSTALL_CONF_DIR}/config.ini"
    chown "root:${SERVICE_GROUP}" "${INSTALL_CONF_DIR}/config.ini"
    info "Default config installed from ${SOURCE_CONF}."
fi

EDITOR_CMD="${EDITOR:-nano}"
if confirm "Open config in ${EDITOR_CMD} before continuing?"; then
    "${EDITOR_CMD}" "${INSTALL_CONF_DIR}/config.ini"
else
    warn "Skipped editor. Review ${INSTALL_CONF_DIR}/config.ini before starting the service."
fi
echo ""

# ── step 5: create runtime data directory ────────────────────────────────────

echo "[ Step 5 ] Runtime data directory  →  ${INSTALL_DATA_DIR}"
if [[ -d "${INSTALL_DATA_DIR}" ]]; then
    info "Directory already exists. Skipping."
else
    if confirm "Create runtime data directory ${INSTALL_DATA_DIR}?"; then
        mkdir -p "${INSTALL_DATA_DIR}/data"
        chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DATA_DIR}"
        chmod 750 "${INSTALL_DATA_DIR}"
        info "Created ${INSTALL_DATA_DIR}."
    else
        warn "Skipped. The service may fail to write runtime data."
    fi
fi
echo ""

# ── step 6: write service file ────────────────────────────────────────────────

echo "[ Step 6 ] Service file  →  ${INSTALL_SERVICE_DEST}"
if [[ -f "${INSTALL_SERVICE_DEST}" ]]; then
    warn "A service file already exists at ${INSTALL_SERVICE_DEST}."
    if confirm "Overwrite it?"; then
        generate_service_file > "${INSTALL_SERVICE_DEST}"
        chmod 644 "${INSTALL_SERVICE_DEST}"
        info "Service file updated."
    else
        info "Kept existing service file."
    fi
else
    if confirm "Write ${SERVICE_FILE} to ${INSTALL_SERVICE_DEST}?"; then
        generate_service_file > "${INSTALL_SERVICE_DEST}"
        chmod 644 "${INSTALL_SERVICE_DEST}"
        info "Service file written."
    else
        abort
    fi
fi
echo ""

# ── step 7: systemctl daemon-reload ──────────────────────────────────────────

echo "[ Step 7 ] Reload systemd"
if confirm "Run 'systemctl daemon-reload'?"; then
    systemctl daemon-reload
    info "systemd configuration reloaded."
else
    warn "Skipped. Run 'sudo systemctl daemon-reload' before starting the service."
fi
echo ""

# ── step 8: enable service ────────────────────────────────────────────────────

echo "[ Step 8 ] Enable service"
if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    info "Service '${SERVICE_NAME}' is already enabled."
else
    if confirm "Enable '${SERVICE_NAME}' to start automatically on boot?"; then
        systemctl enable "${SERVICE_NAME}"
        info "Service '${SERVICE_NAME}' enabled."
    else
        info "Skipped. Enable manually with: sudo systemctl enable ${SERVICE_NAME}"
    fi
fi
echo ""

# ── step 9: start / restart service ──────────────────────────────────────────

echo "[ Step 9 ] Start service"
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    info "Service '${SERVICE_NAME}' is already running."
    if confirm "Restart it now?"; then
        systemctl restart "${SERVICE_NAME}"
        info "Service '${SERVICE_NAME}' restarted."
    else
        info "Skipped. Restart manually with: sudo systemctl restart ${SERVICE_NAME}"
    fi
else
    if confirm "Start '${SERVICE_NAME}' now?"; then
        systemctl start "${SERVICE_NAME}"
        info "Service '${SERVICE_NAME}' started."
    else
        info "Skipped. Start manually with: sudo systemctl start ${SERVICE_NAME}"
    fi
fi

echo ""
echo "Done. Useful commands:"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo "  sudo nano ${INSTALL_CONF_DIR}/config.ini"
