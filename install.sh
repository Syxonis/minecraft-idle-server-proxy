#!/usr/bin/env bash
#
# Minecraft Idle Server Proxy - Interactive Setup Helper
#
# This script:
# - Checks for Python 3.11+
# - Creates idle-server.toml from idle-server.toml.example
# - Asks for the Forge server directory
# - Configures optional Crafty console integration
# - Validates the configuration
# - Optionally creates a systemd service
#
# This script does NOT:
# - Install Java or Forge
# - Modify Forge files, worlds, or server.properties
# - Modify firewall or router rules
# - Overwrite an existing configuration without confirmation
#

set -Eeuo pipefail

APP_NAME="Minecraft Idle Server Proxy"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

PROXY_SCRIPT="$SCRIPT_DIR/idle-server.py"
START_SCRIPT="$SCRIPT_DIR/start-proxy.sh"
CONFIG_EXAMPLE="$SCRIPT_DIR/idle-server.toml.example"
CONFIG_FILE="$SCRIPT_DIR/idle-server.toml"

SERVICE_NAME="minecraft-idle-server-proxy"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

CURRENT_USER="$(id -un)"
PYTHON_PATH=""
FORGE_DIRECTORY=""
WANTS_SYSTEMD_SERVICE=false
CRAFTY_ENABLED=false


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
# Forge server directory detection
# -------------------------------------------------------------------

detect_possible_servers() {
    local base
    local directory
    local selection
    local manual
    local confirmation
    local index
    local path

    local -a base_dirs=(
        "$SCRIPT_DIR/../servers"
        "$SCRIPT_DIR/servers"
        "/var/opt/minecraft/crafty/crafty-4/servers"
        "/opt/minecraft/servers"
        "$HOME/servers"
    )

    local -a found=()
    local -a possible_servers=()

    for base in "${base_dirs[@]}"; do
        [[ -d "$base" ]] || continue

        for directory in "$base"/*/; do
            [[ -d "$directory" ]] || continue

            directory="${directory%/}"

            if [[ -f "$directory/user_jvm_args.txt" ]] || \
               [[ -f "$directory/server.properties" ]] || \
               [[ -d "$directory/mods" ]]; then
                found+=("$directory")
            fi
        done
    done

    if (( ${#found[@]} > 0 )); then
        mapfile -t possible_servers < <(
            printf "%s\n" "${found[@]}" | awk '!seen[$0]++'
        )
    fi

    if (( ${#possible_servers[@]} > 0 )); then
        echo
        echo "Detected possible Forge server directories:"

        index=1

        for path in "${possible_servers[@]}"; do
            echo "  [$index] $path"
            ((index += 1))
        done

        while true; do
            read -r -p \
                "Select number, or press ENTER to input manually: " \
                selection

            if [[ -z "$selection" ]]; then
                read -r -p \
                    "Enter the absolute Forge server directory path: " \
                    manual

                if [[ -d "$manual" ]]; then
                    FORGE_DIRECTORY="$manual"
                    return 0
                fi

                print_warning "Directory not found: $manual"
                continue
            fi

            if [[ "$selection" =~ ^[0-9]+$ ]] && \
               (( selection >= 1 && selection <= ${#possible_servers[@]} )); then

                FORGE_DIRECTORY="${possible_servers[$((selection - 1))]}"

                read -r -p \
                    "Is this correct? $FORGE_DIRECTORY [Y/n]: " \
                    confirmation

                confirmation="${confirmation:-y}"

                if [[ "$confirmation" =~ ^[Yy] ]]; then
                    return 0
                fi

                print_info "Choose another directory."
                continue
            fi

            print_warning "Invalid selection."
        done
    fi

    while true; do
        read -r -p \
            "No server directory detected; enter the absolute Forge server directory path: " \
            manual

        if [[ -d "$manual" ]]; then
            FORGE_DIRECTORY="$manual"
            return 0
        fi

        print_warning "Directory not found: $manual"
    done
}


# -------------------------------------------------------------------
# Validation helpers
# -------------------------------------------------------------------

check_project_files() {
    [[ -f "$PROXY_SCRIPT" ]] || \
        die "Missing required file: idle-server.py"

    [[ -f "$START_SCRIPT" ]] || \
        die "Missing required file: start-proxy.sh"

    [[ -f "$CONFIG_EXAMPLE" ]] || \
        die "Missing required file: idle-server.toml.example"
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
    return 1
}


# -------------------------------------------------------------------
# TOML editing helpers
# -------------------------------------------------------------------

set_toml_value() {
    local section="$1"
    local key="$2"
    local value="$3"

    "$PYTHON_BIN" - "$CONFIG_FILE" "$section" "$key" "$value" <<'PYTHON'
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
target_section = sys.argv[2]
target_key = sys.argv[3]
new_value = sys.argv[4]

lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)

current_section = None
updated = False

for index, line in enumerate(lines):
    stripped = line.strip()

    if stripped.startswith("[") and "]" in stripped:
        current_section = stripped[1:stripped.index("]")].strip()
        continue

    if current_section != target_section:
        continue

    without_indent = line.lstrip()

    if not without_indent.startswith(target_key):
        continue

    remainder = without_indent[len(target_key):].lstrip()

    if not remainder.startswith("="):
        continue

    indentation = line[:len(line) - len(without_indent)]
    lines[index] = f"{indentation}{target_key} = {new_value}\n"
    updated = True
    break

if not updated:
    raise SystemExit(
        f'Could not find "{target_key}" in [{target_section}] '
        f'within {config_path}.'
    )

config_path.write_text("".join(lines), encoding="utf-8")
PYTHON
}


# -------------------------------------------------------------------
# Configuration setup
# -------------------------------------------------------------------

create_or_update_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        print_info "Local configuration already exists:"
        echo "       $CONFIG_FILE"

        if ask_yes_no "Replace it with the example configuration?" "n"; then
            cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
            print_info "Configuration was replaced."
        else
            print_info "Existing configuration was kept."

            if ask_yes_no \
                "Update the configured Forge server directory?" \
                "y"; then

                detect_possible_servers

                set_toml_value \
                    "server" \
                    "directory" \
                    "\"$FORGE_DIRECTORY\""

                print_info "Updated server.directory."
            fi

            return
        fi
    else
        cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
        print_info "Created local configuration:"
        echo "       $CONFIG_FILE"
    fi

    detect_possible_servers

    set_toml_value \
        "server" \
        "directory" \
        "\"$FORGE_DIRECTORY\""

    print_info "Configured Forge server directory:"
    echo "       $FORGE_DIRECTORY"
}


configure_crafty() {
    echo
    echo "Crafty Controller integration is optional."
    echo "Enable it only when Crafty starts this proxy process."
    echo

    if [[ "$WANTS_SYSTEMD_SERVICE" == "true" ]]; then
        print_warning "systemd does not provide Crafty's interactive console."
        print_warning "Crafty console integration will be disabled."

        set_toml_value "crafty" "enabled" "false"
        CRAFTY_ENABLED=false
        return
    fi

    if ask_yes_no "Enable Crafty Controller console integration?" "n"; then
        set_toml_value "crafty" "enabled" "true"
        CRAFTY_ENABLED=true
        print_info "Crafty integration enabled."
    else
        set_toml_value "crafty" "enabled" "false"
        CRAFTY_ENABLED=false
        print_info "Crafty integration disabled."
    fi
}


open_config_editor() {
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
            print_warning "Edit this file manually: $CONFIG_FILE"
            return
        fi
    fi

    "$editor_command" "$CONFIG_FILE"
}


# -------------------------------------------------------------------
# Optional systemd service
# -------------------------------------------------------------------

create_systemd_service() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        print_warning "systemd service creation is supported only on Linux."
        return 1
    fi

    if ! command -v systemctl >/dev/null 2>&1; then
        print_warning "systemctl was not found."
        return 1
    fi

    if [[ "$CURRENT_USER" == "root" ]]; then
        print_warning "Run this setup as the normal user owning the Forge files."
        return 1
    fi

    if ! validate_config; then
        print_warning \
            "The systemd service was not created because the configuration is invalid."
        return 1
    fi

    print_header "systemd Service Preview"

    cat <<EOF
Service file:
  $SERVICE_FILE

Service user:
  $CURRENT_USER

Working directory:
  $SCRIPT_DIR

Start command:
  $START_SCRIPT
EOF

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
ExecStart=$START_SCRIPT
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

    if ask_yes_no "Enable and start the service now?" "y"; then
        sudo systemctl enable --now "$SERVICE_NAME"
        print_info "Service was enabled and started."
    else
        print_info "Service was created but not started."
        echo "Start it with: sudo systemctl enable --now $SERVICE_NAME"
    fi
}


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

main() {
    print_header "$APP_NAME - Interactive Setup"

    echo "This proxy repository should be stored inside or separately from"
    echo "your Forge server directory. The setup asks where Forge is located."
    echo
    echo "This setup does not modify Forge, worlds, server.properties,"
    echo "firewall rules, or router settings."

    check_project_files
    chmod +x "$START_SCRIPT"
    check_python

    echo
    create_or_update_config

    echo
    if ask_yes_no "Create a systemd service?" "n"; then
        WANTS_SYSTEMD_SERVICE=true
    fi

    configure_crafty

    echo
    open_config_editor

    echo
    if ! validate_config; then
        die "Setup stopped because idle-server.toml is invalid."
    fi

    if [[ "$WANTS_SYSTEMD_SERVICE" == "true" ]]; then
        create_systemd_service
    fi

    print_header "Setup Complete"

    echo "Proxy project directory:"
    echo "  $SCRIPT_DIR"

    if [[ -n "$FORGE_DIRECTORY" ]]; then
        echo
        echo "Forge server directory:"
        echo "  $FORGE_DIRECTORY"
    fi

    echo
    echo "Manual proxy start command:"
    echo "  $START_SCRIPT"

    echo
    echo "Forge server.properties should use:"
    echo "  server-ip=127.0.0.1"
    echo "  server-port=25566"

    if [[ "$CRAFTY_ENABLED" == "true" ]]; then
        print_header "CRAFTY CONFIGURATION (copy & paste)"

        cat <<EOF
Working Directory:
  $FORGE_DIRECTORY

Execution Command:
  ./$(basename "$SCRIPT_DIR")/start-proxy.sh

Stop Command:
  stop

Log Location (relative to Working Directory):
  ./$(basename "$SCRIPT_DIR")/idle-server.log

Crafty server IP (for stats):
  127.0.0.1

Crafty server Port (for stats):
  25565
EOF
    fi
}

main "$@"