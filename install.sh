#!/usr/bin/env bash
#
# Minecraft Idle Server Proxy - Interactive Setup Helper
#
# This script can:
# - Check for Python 3.11+
# - Create idle-server.toml from idle-server.toml.example
# - Enable or disable optional Crafty console integration
# - Validate the configuration
# - Create and optionally enable a systemd service
#
# This script does NOT:
# - Install Java or Forge
# - Modify Forge files or worlds
# - Modify server.properties
# - Modify firewall rules
# - Overwrite an existing configuration without confirmation
#

set -Eeuo pipefail

APP_NAME="Minecraft Idle Server Proxy"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

PROXY_SCRIPT="$SCRIPT_DIR/idle-server.py"
CONFIG_EXAMPLE="$SCRIPT_DIR/idle-server.toml.example"
CONFIG_FILE="$SCRIPT_DIR/idle-server.toml"

SERVICE_NAME="minecraft-idle-server-proxy"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

CURRENT_USER="$(id -un)"
PYTHON_PATH=""

WANTS_SYSTEMD_SERVICE=false


# -------------------------------------------------------------------
# Output helpers
# -------------------------------------------------------------------

print_header() {
    echo
    echo "------------------------------------------------------------"
    echo "$*"
    echo "------------------------------------------------------------"
}

print_info() {
    echo "[INFO] $*"
}

print_warning() {
    echo "[WARNING] $*" >&2
}

print_error() {
    echo "[ERROR] $*" >&2
}

die() {
    print_error "$*"
    exit 1
}


# -------------------------------------------------------------------
# Interactive helpers
# -------------------------------------------------------------------

ask_yes_no() {
    local question="$1"
    local default_answer="${2:-y}"
    local answer=""

    while true; do
        if [[ "$default_answer" == "y" ]]; then
            read -r -p "$question [Y/n]: " answer
            answer="${answer:-y}"
        else
            read -r -p "$question [y/N]: " answer
            answer="${answer:-n}"
        fi

        case "$answer" in
            y|Y|yes|YES|Yes)
                return 0
                ;;
            n|N|no|NO|No)
                return 1
                ;;
            *)
                print_warning "Please answer yes or no."
                ;;
        esac
    done
}


# -------------------------------------------------------------------
# Validation helpers
# -------------------------------------------------------------------

check_project_files() {
    [[ -f "$PROXY_SCRIPT" ]] || die "Missing required file: idle-server.py"
    [[ -f "$CONFIG_EXAMPLE" ]] || die "Missing required file: idle-server.toml.example"
}


check_python() {
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        die "Python was not found. Please install Python 3.11 or newer."
    fi

    PYTHON_PATH="$(command -v "$PYTHON_BIN")"

    local python_version
    python_version="$(
        "$PYTHON_BIN" -c \
        'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
    )"

    local python_major="${python_version%%.*}"
    local python_minor="${python_version##*.}"

    if (( python_major < MIN_PYTHON_MAJOR )) || \
       (( python_major == MIN_PYTHON_MAJOR && python_minor < MIN_PYTHON_MINOR )); then
        die "Python 3.11 or newer is required. Found Python ${python_version}."
    fi

    print_info "Using Python ${python_version}: ${PYTHON_PATH}"
}


validate_config() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        print_warning "No local configuration file exists yet."
        return 1
    fi

    print_info "Validating configuration..."

    if "$PYTHON_BIN" "$PROXY_SCRIPT" --check-config; then
        print_info "Configuration is valid."
        return 0
    fi

    print_warning "Configuration validation failed."
    print_warning "Edit idle-server.toml and run this script again."
    return 1
}


# -------------------------------------------------------------------
# Configuration helpers
# -------------------------------------------------------------------

create_config_if_requested() {
    if [[ -f "$CONFIG_FILE" ]]; then
        print_info "Local configuration already exists:"
        echo "       $CONFIG_FILE"

        if ask_yes_no "Do you want to overwrite it with the example configuration?" "n"; then
            cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
            print_info "Configuration was replaced with the example file."
        else
            print_info "Existing configuration was kept."
        fi

        return
    fi

    if ask_yes_no "Create idle-server.toml from idle-server.toml.example?" "y"; then
        cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"

        print_info "Created local configuration:"
        echo "       $CONFIG_FILE"

        echo
        print_warning "You must edit idle-server.toml before production use."
        print_warning "Check server.directory, server.command, ports, and messages."
    else
        print_warning "No local configuration file was created."
    fi
}


set_crafty_enabled() {
    local enabled_value="$1"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        print_warning "Crafty integration cannot be configured without idle-server.toml."
        return 1
    fi

    "$PYTHON_BIN" - "$CONFIG_FILE" "$enabled_value" <<'PYTHON'
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
enabled_value = sys.argv[2]

lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)

inside_crafty = False
updated = False
result = []

for line in lines:
    stripped = line.strip()

    if stripped.startswith("[") and stripped.endswith("]"):
        inside_crafty = stripped == "[crafty]"

    if inside_crafty:
        match = re.match(
            r"^(\s*enabled\s*=\s*)(true|false)(\s*(?:#.*)?)(\r?\n)?$",
            line,
            flags=re.IGNORECASE,
        )

        if match:
            newline = match.group(4) or "\n"
            line = f"{match.group(1)}{enabled_value}{match.group(3)}{newline}"
            updated = True

    result.append(line)

if not updated:
    if result and not result[-1].endswith(("\n", "\r")):
        result[-1] += "\n"

    result.extend(
        [
            "\n",
            "[crafty]\n",
            f"enabled = {enabled_value}\n",
            "forward_console_commands = true\n",
            "show_forge_output = true\n",
        ]
    )

config_path.write_text("".join(result), encoding="utf-8")
PYTHON

    print_info "Set crafty.enabled = ${enabled_value}"
}


configure_crafty() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        print_warning "Skipping Crafty setup because idle-server.toml does not exist."
        return
    fi

    echo
    echo "Crafty Controller integration is optional."
    echo "It allows proxy console commands such as status and stop."
    echo

    if "$WANTS_SYSTEMD_SERVICE"; then
        print_warning "A systemd service does not provide an interactive Crafty console."
        print_warning "Crafty console integration is not useful with this setup."

        if ask_yes_no "Keep Crafty integration disabled?" "y"; then
            set_crafty_enabled "false"
            return
        fi

        print_warning "Crafty will still be disabled to avoid a misleading setup."
        set_crafty_enabled "false"
        return
    fi

    if ask_yes_no "Enable Crafty Controller console integration?" "n"; then
        set_crafty_enabled "true"

        echo
        print_info "Crafty integration was enabled."
        print_info "Forge output logging is controlled separately by:"
        echo "       crafty.show_forge_output = true"
    else
        set_crafty_enabled "false"
        print_info "Crafty integration remains disabled."
    fi
}


# -------------------------------------------------------------------
# Optional editor helper
# -------------------------------------------------------------------

open_config_editor() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        return
    fi

    if ! ask_yes_no "Open idle-server.toml in an editor now?" "n"; then
        return
    fi

    local editor_command="${EDITOR:-}"

    if [[ -z "$editor_command" ]]; then
        if command -v nano >/dev/null 2>&1; then
            editor_command="nano"
        elif command -v vi >/dev/null 2>&1; then
            editor_command="vi"
        else
            print_warning "No editor was found."
            print_warning "Edit this file manually:"
            echo "       $CONFIG_FILE"
            return
        fi
    fi

    "$editor_command" "$CONFIG_FILE"
}


# -------------------------------------------------------------------
# systemd service setup
# -------------------------------------------------------------------

create_systemd_service() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        print_warning "systemd service creation is only supported on Linux."
        return 1
    fi

    if ! command -v systemctl >/dev/null 2>&1; then
        print_warning "systemctl was not found. This system does not appear to use systemd."
        return 1
    fi

    if [[ "$CURRENT_USER" == "root" ]]; then
        print_warning "Do not run this setup script as root."
        print_warning "Run it as the normal user that owns the Forge server files."
        return 1
    fi

    if ! validate_config; then
        print_warning "The systemd service was not created because the configuration is invalid."
        return 1
    fi

    print_header "systemd Service Preview"

    cat <<EOF
The following systemd service will be created:

Service file:
  $SERVICE_FILE

Service user:
  $CURRENT_USER

Working directory:
  $SCRIPT_DIR

Start command:
  $PYTHON_PATH $PROXY_SCRIPT

The service starts the proxy automatically after boot.
The proxy starts Forge only when a player tries to join.
EOF

    echo

    if ! ask_yes_no "Create this systemd service?" "n"; then
        print_info "Skipped systemd service creation."
        return 0
    fi

    local temporary_service_file
    temporary_service_file="$(mktemp)"

    cat >"$temporary_service_file" <<EOF
[Unit]
Description=Minecraft Idle Server Proxy
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_PATH $PROXY_SCRIPT
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
EOF

    print_info "Installing systemd service. sudo permission may be requested."

    sudo install \
        -o root \
        -g root \
        -m 0644 \
        "$temporary_service_file" \
        "$SERVICE_FILE"

    rm -f "$temporary_service_file"

    sudo systemctl daemon-reload

    print_info "Created systemd service:"
    echo "       $SERVICE_FILE"

    echo

    if ask_yes_no "Enable and start the service now?" "y"; then
        sudo systemctl enable --now "$SERVICE_NAME"

        echo
        print_info "Service was enabled and started."

        echo
        echo "Useful commands:"
        echo "  sudo systemctl status $SERVICE_NAME"
        echo "  sudo systemctl restart $SERVICE_NAME"
        echo "  sudo systemctl stop $SERVICE_NAME"
        echo "  sudo journalctl -u $SERVICE_NAME -f"
    else
        echo
        print_info "The service was created but not started."

        echo
        echo "Start it later with:"
        echo "  sudo systemctl enable --now $SERVICE_NAME"
    fi
}


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

main() {
    print_header "$APP_NAME - Interactive Setup"

    echo "This helper can create a local configuration file, configure"
    echo "optional Crafty support, and optionally create a systemd service."
    echo
    echo "It does not install Forge or Java and does not modify your world,"
    echo "server.properties, firewall, or router configuration."
    echo

    check_project_files
    check_python

    echo
    create_config_if_requested

    echo
    if ask_yes_no "Do you want to create a systemd service?" "n"; then
        WANTS_SYSTEMD_SERVICE=true
    else
        WANTS_SYSTEMD_SERVICE=false
    fi

    configure_crafty

    echo
    open_config_editor

    echo
    if [[ -f "$CONFIG_FILE" ]]; then
        if ! validate_config; then
            print_warning "Setup stopped because the configuration is invalid."
            print_warning "Fix idle-server.toml, then run this script again."
            exit 1
        fi
    else
        print_warning "No idle-server.toml exists. Setup is incomplete."
        exit 1
    fi

    if "$WANTS_SYSTEMD_SERVICE"; then
        echo
        create_systemd_service
    fi

    print_header "Setup Complete"

    echo "Configuration file:"
    echo "  $CONFIG_FILE"
    echo
    echo "Manual start command:"
    echo "  $PYTHON_BIN $PROXY_SCRIPT"
    echo
    echo "Important Forge server.properties example:"
    echo "  server-ip=127.0.0.1"
    echo "  server-port=25566"
    echo
    echo "Players should connect to the public proxy port, usually:"
    echo "  your-server-address:25565"
    echo
}

main "$@"