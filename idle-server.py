#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minecraft Idle Server Proxy

A lightweight TCP proxy that keeps a Minecraft Forge server offline while
nobody is playing.

Behaviour:
- Status pings while sleeping receive a custom MOTD and do not start Forge.
- Login attempts while sleeping start Forge in the background.
- Players receive a Login Disconnect message asking them to reconnect later.
- Once Forge is ready, traffic is transparently proxied to the backend.
- Forge is stopped after a configurable idle period with zero online players.

Requirements:
- Python 3.11 or newer
- Forge backend configured to listen on localhost only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

if sys.version_info < (3, 11):
    print(
        "ERROR: Python 3.11 or newer is required.",
        file=sys.stderr,
    )
    sys.exit(1)

import tomllib


APP_NAME = "Minecraft Idle Server Proxy"
APP_VERSION = "0.2.0"


# -------------------------------------------------------------------
# Command-line arguments
# -------------------------------------------------------------------


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=APP_NAME,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION}",
        help="Show program version and exit.",
    )

    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate idle-server.toml and exit.",
    )

    return parser.parse_args()


ARGS = parse_arguments()


# -------------------------------------------------------------------
# Configuration loading and validation
# -------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "idle-server.toml"


def load_config() -> dict:
    """Load the local TOML configuration file."""
    if not CONFIG_FILE.exists():
        print(
            f"ERROR: Configuration file not found: {CONFIG_FILE}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with open(CONFIG_FILE, "rb") as file:
            return tomllib.load(file)

    except tomllib.TOMLDecodeError as exc:
        print(
            f"ERROR: Invalid TOML configuration in {CONFIG_FILE}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    except OSError as exc:
        print(
            f"ERROR: Could not read configuration file: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def get_section(config: dict, name: str) -> dict:
    """Return a required TOML table."""
    section = config.get(name)

    if not isinstance(section, dict):
        raise ValueError(f'Missing or invalid "[{name}]" configuration section.')

    return section


def validate_string(value, name: str, allow_empty: bool = False) -> str:
    """Validate a configuration string."""
    if not isinstance(value, str):
        raise ValueError(f'"{name}" must be a string.')

    if not allow_empty and not value.strip():
        raise ValueError(f'"{name}" must not be empty.')

    return value


def validate_boolean(value, name: str) -> bool:
    """Validate a TOML boolean."""
    if not isinstance(value, bool):
        raise ValueError(f'"{name}" must be true or false.')

    return value


def validate_port(value, name: str) -> int:
    """Validate a TCP/UDP port."""
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'"{name}" must be a valid port number.') from exc

    if not 1 <= port <= 65535:
        raise ValueError(f'"{name}" must be between 1 and 65535.')

    return port


def validate_positive_integer(value, name: str, allow_zero: bool = False) -> int:
    """Validate a positive integer, optionally allowing zero."""
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'"{name}" must be an integer.') from exc

    minimum = 0 if allow_zero else 1

    if number < minimum:
        comparison = "zero or greater" if allow_zero else "greater than zero"
        raise ValueError(f'"{name}" must be {comparison}.')

    return number


def validate_config(config: dict):
    """Validate required configuration values before starting the proxy."""
    server = get_section(config, "server")
    proxy = get_section(config, "proxy")
    time_config = get_section(config, "time")
    motd = get_section(config, "motd")
    join = get_section(config, "join")
    log_config = get_section(config, "log")

    command = server.get("command")

    if not isinstance(command, list) or not command:
        raise ValueError(
            '"server.command" must be a non-empty TOML array.'
        )

    if not all(isinstance(item, str) and item.strip() for item in command):
        raise ValueError(
            '"server.command" may only contain non-empty strings.'
        )

    server_directory = server.get("directory", ".")

    if not isinstance(server_directory, str):
        raise ValueError('"server.directory" must be a string.')

    resolved_server_dir = (SCRIPT_DIR / server_directory).resolve()

    if not resolved_server_dir.is_dir():
        raise ValueError(
            f"Server directory does not exist: {resolved_server_dir}"
        )

    validate_string(server.get("host", "127.0.0.1"), "server.host")
    validate_port(server.get("port"), "server.port")
    validate_string(
        server.get(
            "minecraft_version",
            server.get("version", "Unknown"),
        ),
        "server.minecraft_version",
    )
    validate_positive_integer(
        server.get("protocol"),
        "server.protocol",
        allow_zero=True,
    )
    validate_positive_integer(server.get("max_players"), "server.max_players")

    validate_string(proxy.get("bind", "0.0.0.0"), "proxy.bind")
    validate_port(proxy.get("public_port"), "proxy.public_port")

    if int(server["port"]) == int(proxy["public_port"]):
        raise ValueError(
            '"server.port" and "proxy.public_port" must not be identical.'
        )

    validate_positive_integer(time_config.get("sleep_after"), "time.sleep_after")
    validate_positive_integer(
        time_config.get("start_timeout"),
        "time.start_timeout",
    )
    validate_positive_integer(
        time_config.get("estimated_start_time", 90),
        "time.estimated_start_time",
        allow_zero=True,
    )
    validate_positive_integer(
        time_config.get("player_check_interval"),
        "time.player_check_interval",
    )

    for key in (
        "sleeping",
        "starting",
        "starting_detail",
        "starting_slow",
        "failed",
    ):
        if key in motd:
            validate_string(motd[key], f"motd.{key}", allow_empty=True)

    for key in ("sleeping", "starting", "failed"):
        if key not in motd:
            raise ValueError(f'Missing required configuration value "motd.{key}".')

    for key in ("starting", "failed"):
        validate_string(join.get(key), f"join.{key}", allow_empty=True)

    crafty_config = config.get("crafty", {})

    if not isinstance(crafty_config, dict):
        raise ValueError('"crafty" must be a TOML table.')

    for key in (
        "enabled",
        "forward_console_commands",
        "show_forge_output",
    ):
        if key in crafty_config:
            validate_boolean(crafty_config[key], f"crafty.{key}")

    validate_string(log_config.get("file"), "log.file")
    validate_string(log_config.get("level", "INFO"), "log.level")
    validate_positive_integer(log_config.get("max_bytes"), "log.max_bytes")
    validate_positive_integer(
        log_config.get("backup_count"),
        "log.backup_count",
        allow_zero=True,
    )


CFG = load_config()

try:
    validate_config(CFG)
except ValueError as exc:
    print(f"ERROR: Invalid configuration: {exc}", file=sys.stderr)
    sys.exit(1)

if ARGS.check_config:
    print(f"Configuration is valid: {CONFIG_FILE}")
    sys.exit(0)


# -------------------------------------------------------------------
# Configuration values
# -------------------------------------------------------------------

SERVER_DIR = (SCRIPT_DIR / CFG["server"].get("directory", ".")).resolve()
SERVER_COMMAND = CFG["server"]["command"]

BACKEND_HOST = CFG["server"].get("host", "127.0.0.1")
BACKEND_PORT = int(CFG["server"]["port"])

# "version" remains supported as a compatibility fallback.
VERSION = str(
    CFG["server"].get(
        "minecraft_version",
        CFG["server"].get("version", "Unknown"),
    )
)

PROTOCOL = int(CFG["server"]["protocol"])
MAX_PLAYERS = int(CFG["server"]["max_players"])

PUBLIC_BIND = CFG["proxy"].get("bind", "0.0.0.0")
PUBLIC_PORT = int(CFG["proxy"]["public_port"])

SLEEP_AFTER = int(CFG["time"]["sleep_after"])
START_TIMEOUT = int(CFG["time"]["start_timeout"])
ESTIMATED_START_TIME = int(
    CFG["time"].get("estimated_start_time", 90)
)
PLAYER_CHECK_INTERVAL = int(CFG["time"]["player_check_interval"])

MOTD_SLEEPING = CFG["motd"]["sleeping"]
MOTD_STARTING = CFG["motd"]["starting"]
MOTD_STARTING_DETAIL = CFG["motd"].get(
    "starting_detail",
    "§7Started {elapsed}s ago - about {remaining}s remaining",
)
MOTD_STARTING_SLOW = CFG["motd"].get(
    "starting_slow",
    "§e☻ Startup is taking longer than expected",
)
MOTD_FAILED = CFG["motd"]["failed"]

JOIN_STARTING = CFG["join"]["starting"]
JOIN_FAILED = CFG["join"]["failed"]

CRAFTY_CFG = CFG.get("crafty", {})

CRAFTY_ENABLED = bool(CRAFTY_CFG.get("enabled", False))
CRAFTY_FORWARD_COMMANDS = bool(
    CRAFTY_CFG.get("forward_console_commands", True)
)
CRAFTY_SHOW_FORGE_OUTPUT = bool(
    CRAFTY_CFG.get("show_forge_output", True)
)

LOG_FILE = SCRIPT_DIR / CFG["log"]["file"]
LOG_LEVEL = CFG["log"].get("level", "INFO").upper()
LOG_MAX_BYTES = int(CFG["log"]["max_bytes"])
LOG_BACKUP_COUNT = int(CFG["log"]["backup_count"])


# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("idle-server")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logger.handlers.clear()

formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


# -------------------------------------------------------------------
# Runtime state
# -------------------------------------------------------------------

os.chdir(SERVER_DIR)

state_lock = threading.RLock()

# Process started by this script.
# It remains None if Forge was started manually.
minecraft_process: subprocess.Popen | None = None

# Possible values:
# "sleeping", "starting", "running", "failed"
server_state = "sleeping"

# Unix timestamp for the current startup attempt.
# None while sleeping, running, or failed.
startup_started_at: float | None = None

# Timestamp of the last detected online player.
last_player_seen = time.time()

# Set on Ctrl+C, SIGTERM, or Crafty stop command.
shutdown_requested = threading.Event()


# -------------------------------------------------------------------
# Minecraft protocol helpers
# -------------------------------------------------------------------


def write_varint(value: int) -> bytes:
    """Encode a Minecraft VarInt."""
    value &= 0xFFFFFFFF
    result = bytearray()

    while True:
        current = value & 0x7F
        value >>= 7

        if value != 0:
            result.append(current | 0x80)
        else:
            result.append(current)
            return bytes(result)


def read_varint_from_bytes(data: bytes, offset: int = 0):
    """Return a tuple containing (value, new_offset)."""
    value = 0
    position = 0

    while True:
        if offset >= len(data):
            raise ValueError("Unexpected end while reading VarInt.")

        current = data[offset]
        offset += 1

        value |= (current & 0x7F) << position

        if (current & 0x80) == 0:
            return value, offset

        position += 7

        if position > 35:
            raise ValueError("VarInt is too large.")


def recv_exact(sock: socket.socket, amount: int) -> bytes:
    """Receive exactly the requested number of bytes."""
    result = bytearray()

    while len(result) < amount:
        chunk = sock.recv(amount - len(result))

        if not chunk:
            raise ConnectionError("Connection closed.")

        result.extend(chunk)

    return bytes(result)


def recv_varint(sock: socket.socket) -> int:
    """Read a Minecraft VarInt directly from a socket."""
    value = 0
    position = 0

    while True:
        raw = sock.recv(1)

        if not raw:
            raise ConnectionError("Connection closed while reading VarInt.")

        current = raw[0]
        value |= (current & 0x7F) << position

        if (current & 0x80) == 0:
            return value

        position += 7

        if position > 35:
            raise ValueError("VarInt is too large.")


def recv_frame(sock: socket.socket) -> bytes:
    """
    Read a normal Minecraft packet frame and return its payload.

    Frame format:
    VarInt packet_length
    packet_payload
    """
    packet_length = recv_varint(sock)

    if packet_length < 0 or packet_length > 2_097_152:
        raise ValueError(f"Invalid packet length: {packet_length}")

    return recv_exact(sock, packet_length)


def make_frame(payload: bytes) -> bytes:
    """Add a Minecraft packet-length VarInt to a payload."""
    return write_varint(len(payload)) + payload


# -------------------------------------------------------------------
# MOTD and status packets
# -------------------------------------------------------------------

COLOR_MAP = {
    "0": "black",
    "1": "dark_blue",
    "2": "dark_green",
    "3": "dark_aqua",
    "4": "dark_red",
    "5": "dark_purple",
    "6": "gold",
    "7": "gray",
    "8": "dark_gray",
    "9": "blue",
    "a": "green",
    "b": "aqua",
    "c": "red",
    "d": "light_purple",
    "e": "yellow",
    "f": "white",
}


def motd_to_component(text: str) -> dict:
    """
    Convert basic Minecraft § color codes into a JSON chat component.

    This intentionally supports colors and reset only.
    """
    if "§" not in text:
        return {"text": text}

    parts = []
    current_text = ""
    current_color = None
    index = 0

    def flush():
        nonlocal current_text

        if current_text:
            item = {"text": current_text}

            if current_color:
                item["color"] = current_color

            parts.append(item)
            current_text = ""

    while index < len(text):
        if text[index] == "§" and index + 1 < len(text):
            code = text[index + 1].lower()

            if code in COLOR_MAP:
                flush()
                current_color = COLOR_MAP[code]
                index += 2
                continue

            if code == "r":
                flush()
                current_color = None
                index += 2
                continue

        current_text += text[index]
        index += 1

    flush()

    if not parts:
        return {"text": ""}

    if len(parts) == 1:
        return parts[0]

    return {"text": "", "extra": parts}


def build_status_response(motd: str, online: int = 0) -> bytes:
    """Build a Minecraft status response packet."""
    status = {
        "version": {
            "name": VERSION,
            "protocol": PROTOCOL,
        },
        "players": {
            "max": MAX_PLAYERS,
            "online": online,
        },
        "description": motd_to_component(motd),
    }

    status_json = json.dumps(
        status,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    payload = (
        write_varint(0)
        + write_varint(len(status_json))
        + status_json
    )

    return make_frame(payload)


def build_login_disconnect(reason: str) -> bytes:
    """
    Build a Login-state Disconnect packet for Minecraft 1.20.1.

    Packet ID: 0
    Payload: Chat component JSON String
    """
    component = json.dumps(
        {"text": reason},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    payload = (
        write_varint(0)
        + write_varint(len(component))
        + component
    )

    return make_frame(payload)


# -------------------------------------------------------------------
# Dynamic startup messages
# -------------------------------------------------------------------


def get_startup_values() -> dict[str, int]:
    """
    Return safe values for supported message placeholders.

    Available placeholders:
    {elapsed}
    {remaining}
    {estimate}
    {timeout}
    """
    with state_lock:
        started_at = startup_started_at

    if started_at is None:
        elapsed = 0
    else:
        elapsed = max(0, int(time.time() - started_at))

    remaining = max(0, ESTIMATED_START_TIME - elapsed)

    return {
        "elapsed": elapsed,
        "remaining": remaining,
        "estimate": ESTIMATED_START_TIME,
        "timeout": START_TIMEOUT,
    }


def replace_message_placeholders(text: str) -> str:
    """
    Replace only documented message placeholders.

    str.format() is intentionally not used. This means arbitrary braces in
    custom user text do not cause formatting errors.
    """
    values = get_startup_values()

    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))

    return text


def get_starting_motd() -> str:
    """Build the dynamic two-line MOTD while Forge is starting."""
    values = get_startup_values()

    if values["elapsed"] > ESTIMATED_START_TIME:
        detail = replace_message_placeholders(MOTD_STARTING_SLOW)
    else:
        detail = replace_message_placeholders(MOTD_STARTING_DETAIL)

    return f"{MOTD_STARTING}\n{detail}"


# -------------------------------------------------------------------
# Backend status and player counter
# -------------------------------------------------------------------


def backend_port_open() -> bool:
    """Return whether the Forge backend currently accepts TCP connections."""
    try:
        sock = socket.create_connection(
            (BACKEND_HOST, BACKEND_PORT),
            timeout=1.0,
        )
        sock.close()
        return True

    except OSError:
        return False


def query_backend_players() -> int | None:
    """
    Query Forge using the Minecraft status protocol.

    Returns:
        int: Number of online players.
        None: Backend did not answer correctly.
    """
    sock = None

    try:
        sock = socket.create_connection(
            (BACKEND_HOST, BACKEND_PORT),
            timeout=3.0,
        )
        sock.settimeout(5.0)

        host_raw = BACKEND_HOST.encode("utf-8")

        # Handshake:
        # packet ID 0, protocol, host string, port u16, next state 1.
        handshake = (
            write_varint(0)
            + write_varint(PROTOCOL)
            + write_varint(len(host_raw))
            + host_raw
            + struct.pack(">H", BACKEND_PORT)
            + write_varint(1)
        )

        sock.sendall(make_frame(handshake))

        # Status Request: packet ID 0.
        sock.sendall(make_frame(write_varint(0)))

        response = recv_frame(sock)
        packet_id, offset = read_varint_from_bytes(response)

        if packet_id != 0:
            return None

        json_length, offset = read_varint_from_bytes(response, offset)
        json_data = response[offset:offset + json_length]

        status = json.loads(json_data.decode("utf-8"))
        return int(status.get("players", {}).get("online", 0))

    except Exception as exc:
        logger.debug(f"Backend status query failed: {exc}")
        return None

    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


# -------------------------------------------------------------------
# Optional Crafty console integration
# -------------------------------------------------------------------


def forge_output_reader(process: subprocess.Popen):
    """Forward Forge stdout/stderr to the proxy log."""
    try:
        if process.stdout is None:
            return

        for raw_line in iter(process.stdout.readline, b""):
            line = raw_line.decode(
                "utf-8",
                errors="replace",
            ).rstrip("\r\n")

            if line:
                logger.info(f"[Forge] {line}")

    except Exception as exc:
        logger.debug(f"Forge output reader ended: {exc}")


def crafty_console_reader():
    """
    Read commands from the Crafty console.

    Built-in commands:
    - status
    - stop
    - exit
    - quit

    Other commands may be forwarded to Forge if enabled in the configuration.
    """
    global minecraft_process

    while not shutdown_requested.is_set():
        try:
            line = sys.stdin.readline()
        except Exception:
            return

        # No interactive stdin available.
        if line == "":
            return

        command = line.strip()

        if not command:
            continue

        command_lower = command.lower()

        if command_lower == "status":
            with state_lock:
                pid = minecraft_process.pid if minecraft_process else "-"
                state = server_state
                startup_values = get_startup_values()

            logger.info(
                "[Idle Proxy] "
                f"state={state}, "
                f"forge_pid={pid}, "
                f"backend_port="
                f"{'open' if backend_port_open() else 'closed'}, "
                f"startup_elapsed={startup_values['elapsed']}s"
            )
            continue

        if command_lower in ("stop", "exit", "quit"):
            logger.info("[Crafty] Stop requested.")
            shutdown_requested.set()
            continue

        if not CRAFTY_FORWARD_COMMANDS:
            logger.info(
                "[Idle Proxy] Console command forwarding is disabled."
            )
            continue

        with state_lock:
            process = minecraft_process

        if (
            process is None
            or process.poll() is not None
            or process.stdin is None
        ):
            logger.info(
                f"[Idle Proxy] Forge is sleeping; command ignored: {command}"
            )
            continue

        try:
            process.stdin.write((command + "\n").encode("utf-8"))
            process.stdin.flush()
            logger.info(f"[Crafty -> Forge] {command}")

        except Exception as exc:
            logger.warning(f"Could not forward command to Forge: {exc}")


# -------------------------------------------------------------------
# Forge process management
# -------------------------------------------------------------------


def stop_process_after_failed_start(process: subprocess.Popen):
    """Try to stop a Forge process after a startup timeout."""
    if process.poll() is not None:
        return

    logger.warning("Stopping Forge after failed startup.")

    try:
        if process.stdin is not None:
            process.stdin.write(b"stop\n")
            process.stdin.flush()

    except Exception:
        pass

    try:
        process.wait(timeout=30)

    except subprocess.TimeoutExpired:
        logger.warning("Forge did not stop after startup timeout; terminating.")
        process.terminate()

        try:
            process.wait(timeout=15)

        except subprocess.TimeoutExpired:
            logger.warning("Forge is still alive; killing process.")
            process.kill()
            process.wait()


def start_backend_worker():
    """
    Start Forge in a background thread.

    The state is already set to "starting" by start_backend_async() before
    this worker is created. This prevents simultaneous startup attempts.
    """
    global minecraft_process
    global server_state
    global last_player_seen
    global startup_started_at

    if backend_port_open():
        with state_lock:
            server_state = "running"
            startup_started_at = None

        logger.info("Forge backend was already running.")
        return

    logger.info("Starting Forge backend...")

    try:
        process = subprocess.Popen(
            SERVER_COMMAND,
            cwd=SERVER_DIR,
            stdin=subprocess.PIPE,
            stdout=(
                subprocess.PIPE
                if CRAFTY_SHOW_FORGE_OUTPUT
                else subprocess.DEVNULL
            ),
            stderr=subprocess.STDOUT,
            bufsize=0,
        )

    except Exception as exc:
        logger.exception(f"Could not start Forge: {exc}")

        with state_lock:
            minecraft_process = None
            server_state = "failed"
            startup_started_at = None

        return

    with state_lock:
        minecraft_process = process

    if CRAFTY_SHOW_FORGE_OUTPUT:
        threading.Thread(
            target=forge_output_reader,
            args=(process,),
            name="forge-output",
            daemon=True,
        ).start()

    logger.info(f"Forge process started with PID {process.pid}.")

    for second in range(1, START_TIMEOUT + 1):
        if shutdown_requested.is_set():
            logger.info("Shutdown requested during Forge startup.")
            stop_process_after_failed_start(process)

            with state_lock:
                minecraft_process = None
                server_state = "sleeping"
                startup_started_at = None

            return

        time.sleep(1)

        if process.poll() is not None:
            logger.error(
                "Forge stopped during startup "
                f"(exit code {process.returncode})."
            )

            with state_lock:
                minecraft_process = None
                server_state = "failed"
                startup_started_at = None

            return

        if backend_port_open():
            logger.info(f"Forge backend is ready after {second}s.")

            with state_lock:
                server_state = "running"
                startup_started_at = None
                last_player_seen = time.time()

            return

    logger.error(
        f"Forge did not open port {BACKEND_PORT} "
        f"within {START_TIMEOUT}s."
    )

    stop_process_after_failed_start(process)

    with state_lock:
        minecraft_process = None
        server_state = "failed"
        startup_started_at = None


def start_backend_async():
    """
    Start Forge asynchronously if it is not already running or starting.

    Setting state="starting" before the thread is created prevents multiple
    players joining simultaneously from spawning multiple Forge processes.
    """
    global server_state
    global startup_started_at

    with state_lock:
        if backend_port_open():
            server_state = "running"
            startup_started_at = None
            return

        if server_state == "starting":
            return

        server_state = "starting"
        startup_started_at = time.time()

    thread = threading.Thread(
        target=start_backend_worker,
        name="forge-starter",
        daemon=True,
    )
    thread.start()


def stop_backend():
    """
    Stop only a Forge process started by this script.

    A manually started Forge backend is intentionally never stopped.
    """
    global minecraft_process
    global server_state
    global startup_started_at

    with state_lock:
        process = minecraft_process

    if process is None:
        if backend_port_open():
            logger.info(
                "Backend was not started by this script; not stopping it."
            )

            with state_lock:
                server_state = "running"
                startup_started_at = None

        else:
            with state_lock:
                server_state = "sleeping"
                startup_started_at = None

        return

    if process.poll() is not None:
        with state_lock:
            minecraft_process = None
            server_state = "sleeping"
            startup_started_at = None

        return

    logger.info("Stopping Forge backend gracefully...")

    try:
        if process.stdin is not None:
            process.stdin.write(b"stop\n")
            process.stdin.flush()

    except Exception as exc:
        logger.warning(f"Could not send stop command to Forge: {exc}")

    try:
        process.wait(timeout=45)
        logger.info("Forge backend stopped cleanly.")

    except subprocess.TimeoutExpired:
        logger.warning("Forge did not stop within 45 seconds; terminating.")
        process.terminate()

        try:
            process.wait(timeout=15)

        except subprocess.TimeoutExpired:
            logger.warning("Forge is still alive; killing process.")
            process.kill()
            process.wait()

    with state_lock:
        minecraft_process = None
        server_state = "sleeping"
        startup_started_at = None


# -------------------------------------------------------------------
# Transparent TCP proxy
# -------------------------------------------------------------------


def forward_stream(source: socket.socket, destination: socket.socket):
    """Forward all data from one socket to another."""
    try:
        while True:
            data = source.recv(65536)

            if not data:
                return

            destination.sendall(data)

    except OSError:
        pass

    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def proxy_to_backend(
    client_sock: socket.socket,
    client_addr,
    first_frame: bytes,
):
    """
    Connect the client to Forge and forward traffic in both directions.

    The already-read Minecraft handshake frame is sent to Forge first.
    """
    backend_sock = None

    try:
        backend_sock = socket.create_connection(
            (BACKEND_HOST, BACKEND_PORT),
            timeout=5.0,
        )

        backend_sock.sendall(first_frame)

        # Do not use short timeouts during actual gameplay.
        client_sock.settimeout(None)
        backend_sock.settimeout(None)

        logger.debug(f"Proxying {client_addr} to Forge backend.")

        client_to_backend = threading.Thread(
            target=forward_stream,
            args=(client_sock, backend_sock),
            daemon=True,
        )

        backend_to_client = threading.Thread(
            target=forward_stream,
            args=(backend_sock, client_sock),
            daemon=True,
        )

        client_to_backend.start()
        backend_to_client.start()

        client_to_backend.join()
        backend_to_client.join()

    except Exception as exc:
        logger.debug(f"Proxy error for {client_addr}: {exc}")

    finally:
        if backend_sock is not None:
            try:
                backend_sock.close()
            except OSError:
                pass


# -------------------------------------------------------------------
# Client protocol handling
# -------------------------------------------------------------------


def parse_handshake(payload: bytes):
    """
    Parse a Minecraft handshake packet.

    Returns:
        protocol, hostname, port, next_state

    next_state:
        1 = Status
        2 = Login
    """
    packet_id, offset = read_varint_from_bytes(payload)

    if packet_id != 0:
        raise ValueError(
            f"Expected handshake packet ID 0, got {packet_id}."
        )

    protocol, offset = read_varint_from_bytes(payload, offset)
    host_length, offset = read_varint_from_bytes(payload, offset)

    if offset + host_length > len(payload):
        raise ValueError("Invalid handshake hostname length.")

    hostname = payload[offset:offset + host_length].decode(
        "utf-8",
        errors="replace",
    )
    offset += host_length

    if offset + 2 > len(payload):
        raise ValueError("Handshake does not contain a port.")

    port = struct.unpack(">H", payload[offset:offset + 2])[0]
    offset += 2

    next_state, offset = read_varint_from_bytes(payload, offset)

    return protocol, hostname, port, next_state


def handle_sleeping_status(client_sock: socket.socket, motd: str):
    """
    Answer a server-list status request without starting Forge.

    The client may send an optional ping packet afterwards. If so, it is
    returned unchanged.
    """
    client_sock.sendall(build_status_response(motd, online=0))

    try:
        client_sock.settimeout(5.0)

        ping_payload = recv_frame(client_sock)
        packet_id, _ = read_varint_from_bytes(ping_payload)

        # Status ping packet ID is 1.
        if packet_id == 1:
            client_sock.sendall(make_frame(ping_payload))

    except Exception:
        # Many server lists close before sending a ping packet.
        pass


def wait_for_login_start(client_sock: socket.socket) -> bool:
    """
    Wait for the Login Start packet.

    Reading this first ensures the client is definitely in Login state before
    receiving the Login Disconnect response.
    """
    client_sock.settimeout(5.0)

    try:
        login_start = recv_frame(client_sock)
        packet_id, _ = read_varint_from_bytes(login_start)

        # Minecraft 1.20.1 Login Start packet ID is 0.
        return packet_id == 0

    except Exception:
        return False


def handle_client(client_sock: socket.socket, client_addr):
    """Handle one incoming Minecraft connection."""
    global server_state

    try:
        client_sock.settimeout(10.0)

        handshake_payload = recv_frame(client_sock)
        handshake_frame = make_frame(handshake_payload)

        _, _, _, next_state = parse_handshake(handshake_payload)

        backend_running = backend_port_open()

        if backend_running:
            with state_lock:
                server_state = "running"

        # -----------------------------------------------------------
        # Minecraft server-list status ping
        # -----------------------------------------------------------
        if next_state == 1:
            if backend_running:
                proxy_to_backend(
                    client_sock,
                    client_addr,
                    handshake_frame,
                )
                return

            with state_lock:
                current_state = server_state

            if current_state == "starting":
                handle_sleeping_status(
                    client_sock,
                    get_starting_motd(),
                )

            elif current_state == "failed":
                handle_sleeping_status(client_sock, MOTD_FAILED)

            else:
                handle_sleeping_status(client_sock, MOTD_SLEEPING)

            return

        # -----------------------------------------------------------
        # Minecraft login
        # -----------------------------------------------------------
        if next_state == 2:
            if backend_running:
                proxy_to_backend(
                    client_sock,
                    client_addr,
                    handshake_frame,
                )
                return

            # Only a real Login Start packet may wake Forge.
            if not wait_for_login_start(client_sock):
                logger.debug(
                    f"Client {client_addr} did not send a valid "
                    "Login Start packet."
                )
                return

            # A valid login attempt wakes Forge asynchronously.
            start_backend_async()

            with state_lock:
                current_state = server_state

            if current_state == "failed":
                reason = replace_message_placeholders(JOIN_FAILED)
            else:
                reason = replace_message_placeholders(JOIN_STARTING)

            client_sock.sendall(build_login_disconnect(reason))

            logger.info(
                f"Sent startup/reconnect message to {client_addr}."
            )
            return

        logger.debug(
            f"Unknown handshake next_state={next_state} "
            f"from {client_addr}."
        )

    except Exception as exc:
        logger.debug(f"Client handler error for {client_addr}: {exc}")

    finally:
        try:
            client_sock.close()
        except OSError:
            pass


# -------------------------------------------------------------------
# Idle monitor
# -------------------------------------------------------------------


def idle_monitor():
    """
    Monitor the Forge backend.

    Every configured interval:
    - Detect whether Forge is reachable.
    - Query the online player count.
    - Reset idle time if players are online.
    - Stop Forge after sleep_after seconds without players.
    """
    global last_player_seen
    global minecraft_process
    global server_state
    global startup_started_at

    while not shutdown_requested.is_set():
        time.sleep(PLAYER_CHECK_INTERVAL)

        if shutdown_requested.is_set():
            return

        if not backend_port_open():
            with state_lock:
                if server_state == "running":
                    logger.warning("Forge backend disappeared.")
                    server_state = "sleeping"

                if (
                    minecraft_process is not None
                    and minecraft_process.poll() is not None
                ):
                    minecraft_process = None

                if server_state != "starting":
                    startup_started_at = None

            continue

        with state_lock:
            current_state = server_state

        # Forge may open its port shortly before start_backend_worker()
        # changes state from "starting" to "running". Never perform idle
        # shutdown checks during this short transition period.
        if current_state == "starting":
            continue

        with state_lock:
            server_state = "running"
            startup_started_at = None

        player_count = query_backend_players()

        if player_count is None:
            logger.debug(
                "Could not query player count; skipping idle check."
            )
            continue

        if player_count > 0:
            last_player_seen = time.time()
            logger.debug(f"Forge players online: {player_count}")
            continue

        idle_seconds = int(time.time() - last_player_seen)

        if idle_seconds >= SLEEP_AFTER:
            logger.info(
                f"No players for {idle_seconds}s; "
                "stopping Forge backend."
            )
            stop_backend()


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------


def main():
    """Start the idle proxy."""
    global server_state
    global startup_started_at

    logger.info("------------------------------------------------------------")
    logger.info(f"{APP_NAME} {APP_VERSION} starting")
    logger.info(f"Public address: {PUBLIC_BIND}:{PUBLIC_PORT}")
    logger.info(f"Forge backend: {BACKEND_HOST}:{BACKEND_PORT}")
    logger.info(f"Server directory: {SERVER_DIR}")
    logger.info(f"Sleep after: {SLEEP_AFTER}s")
    logger.info(f"Start timeout: {START_TIMEOUT}s")
    logger.info(f"Estimated start time: {ESTIMATED_START_TIME}s")
    logger.info("------------------------------------------------------------")

    if backend_port_open():
        with state_lock:
            server_state = "running"
            startup_started_at = None

        logger.info("Forge backend was already running.")

    else:
        with state_lock:
            server_state = "sleeping"
            startup_started_at = None

        logger.info("Forge backend is sleeping.")

    monitor_thread = threading.Thread(
        target=idle_monitor,
        name="idle-monitor",
        daemon=True,
    )
    monitor_thread.start()

    if CRAFTY_ENABLED:
        logger.info("Crafty console integration is enabled.")

        threading.Thread(
            target=crafty_console_reader,
            name="crafty-console",
            daemon=True,
        ).start()

    else:
        logger.info("Crafty console integration is disabled.")

    def on_shutdown_signal(signum, frame):
        logger.info(f"Received signal {signum}; shutting down.")
        shutdown_requested.set()

    signal.signal(signal.SIGTERM, on_shutdown_signal)
    signal.signal(signal.SIGINT, on_shutdown_signal)

    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen_socket.bind((PUBLIC_BIND, PUBLIC_PORT))
    listen_socket.listen(50)
    listen_socket.settimeout(1.0)

    logger.info(
        f"Listening for Minecraft clients on "
        f"{PUBLIC_BIND}:{PUBLIC_PORT}"
    )

    try:
        while not shutdown_requested.is_set():
            try:
                client_sock, client_addr = listen_socket.accept()

            except socket.timeout:
                continue

            thread = threading.Thread(
                target=handle_client,
                args=(client_sock, client_addr),
                daemon=True,
            )
            thread.start()

    finally:
        logger.info("Stopping Idle Minecraft Proxy...")

        # Stop only Java/Forge started by this script.
        stop_backend()

        try:
            listen_socket.close()
        except OSError:
            pass

        logger.info("Idle Minecraft Proxy stopped.")


if __name__ == "__main__":
    main()