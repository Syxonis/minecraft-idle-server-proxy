# Minecraft Idle Server Proxy

A lightweight Python proxy for Minecraft Forge servers.

The proxy keeps a Forge server offline while nobody is playing. A Minecraft
server-list ping does **not** start Forge. When a player tries to join, the
proxy starts Forge in the background and tells the player to reconnect after
startup is complete.

Once Forge is running, the proxy transparently forwards Minecraft traffic to
the backend server. After a configurable period without online players, Forge
is stopped again.

> Current protocol support is intended for Minecraft Forge 1.20.1 using
> protocol version `763`.

## Features

- Does not start Forge because of server-list pings
- Starts Forge when a player attempts to log in
- Requires a valid Login Start packet before waking Forge
- Configurable sleeping, starting, and failed-start MOTDs
- Dynamic startup messages with elapsed and estimated remaining time
- Transparent TCP proxy while Forge is running
- Automatically stops Forge after a configurable idle period
- Queries the real Minecraft player count through the status protocol
- Graceful Forge shutdown using the `stop` command
- No external Python packages required
- Optional Crafty Controller console integration
- Optional interactive Linux setup helper
- Optional `systemd` service setup through the setup helper
- Rotating log files
- Configuration validation with `--check-config`

## How It Works

```text
Minecraft Client
       │
       ▼
Idle Server Proxy (:25565)
       │
       ├── Forge sleeping
       │   ├── Server-list ping → Custom sleeping MOTD
       │   └── Login attempt → Start Forge and ask player to reconnect
       │
       └── Forge running
           └── Transparent TCP proxy → Forge backend (:25566)
```

In short:

```text
Server-list ping     → Does not start Forge
Player login attempt → Starts Forge
Forge ready          → Player reconnects and joins normally
No players online    → Forge stops after the configured idle period
```

## Compatibility

This version is intended for:

- Minecraft Forge `1.20.1`
- Minecraft protocol version `763`
- Python `3.11` or newer
- Linux for production deployments

The Python source can also be checked on Windows, but `install.sh`, Crafty
integration, and optional `systemd` service setup are primarily intended for
Linux.

## Requirements

- Python **3.11** or newer
- A working Minecraft Forge server
- Java compatible with the selected Forge/Minecraft version
- Forge configured to listen on a local backend port
- Permission to bind the public Minecraft port, normally `25565`

Python 3.11 is required because this project uses Python's built-in `tomllib`
module to read TOML configuration files.

Check your Python version:

```bash
python3 --version
```

## Installation

### Quick Install

Clone the repository into the Forge server directory:

```bash
cd /path/to/your/forge-server

git clone https://github.com/Syxonis/minecraft-idle-server-proxy.git

cd minecraft-idle-server-proxy

chmod +x install.sh start-proxy.sh

./install.sh
```

The setup helper creates `idle-server.toml`, asks for the Forge server
directory, optionally enables Crafty integration, validates the configuration,
and can create a `systemd` service.

## Recommended Directory Layout

For Crafty Controller, install the proxy inside the actual Forge server
directory:

```text
/path/to/forge-server/
├── libraries/
├── logs/
├── mods/
├── world/
├── server.properties
├── user_jvm_args.txt
│
└── minecraft-idle-server-proxy/
    ├── idle-server.py
    ├── idle-server.toml
    ├── idle-server.toml.example
    ├── install.sh
    ├── start-proxy.sh
    └── idle-server.log
```

For example, Crafty server directories commonly look like this:

```text
/var/opt/minecraft/crafty/crafty-4/servers/
└── e82847a6-38b2-4699-acf4-ca36d62ba064/
    ├── libraries/
    ├── logs/
    ├── mods/
    ├── world/
    ├── server.properties
    ├── user_jvm_args.txt
    │
    └── minecraft-idle-server-proxy/
        ├── idle-server.py
        ├── idle-server.toml
        ├── install.sh
        └── start-proxy.sh
```

> Crafty's **Working Directory** must be the actual Forge server directory,
> not the `minecraft-idle-server-proxy` subdirectory.

## Interactive Setup Helper

Run these commands inside the proxy directory:

```bash
chmod +x install.sh start-proxy.sh
./install.sh
```

The setup helper can:

- Check for Python 3.11 or newer
- Check that required project files exist
- Create `idle-server.toml` from `idle-server.toml.example`
- Detect possible Forge server directories
- Ask for the Forge server directory
- Keep or replace an existing local configuration after confirmation
- Enable or disable Crafty Controller console integration
- Validate the configuration
- Optionally create a `systemd` service

The setup helper does **not**:

- Install Java
- Install Forge
- Modify Forge files or worlds
- Modify `server.properties`
- Modify firewall or router rules
- Overwrite `idle-server.toml` without confirmation

> Crafty integration and `systemd` are alternative deployment methods.
> Do not use both to start the same proxy instance.

## Manual Installation

### 1. Clone the Repository

Clone the repository into the Forge server directory:

```bash
cd /path/to/your/forge-server

git clone https://github.com/Syxonis/minecraft-idle-server-proxy.git

cd minecraft-idle-server-proxy
```

### 2. Make the Scripts Executable

```bash
chmod +x install.sh
chmod +x start-proxy.sh
```

### 3. Create the Local Configuration

```bash
cp idle-server.toml.example idle-server.toml
```

### 4. Configure the Forge Directory

Open `idle-server.toml` and set `server.directory` to the actual Forge server
directory, not the proxy directory.

```toml
[server]
directory = "/path/to/forge-server"

command = [
  "java",
  "@user_jvm_args.txt",
  "@libraries/net/minecraftforge/forge/1.20.1-47.4.23/unix_args.txt",
  "nogui"
]

host = "127.0.0.1"
port = 25566

minecraft_version = "1.20.1"
protocol = 763
max_players = 20
```

For the example Crafty directory above:

```toml
[server]
directory = "/var/opt/minecraft/crafty/crafty-4/servers/e82847a6-38b2-4699-acf4-ca36d62ba064"
```

### 5. Configure Forge `server.properties`

Forge must listen on a different port than the proxy.

```properties
server-ip=127.0.0.1
server-port=25566
```

### 6. Configure the Proxy Port

The proxy listens publicly on port `25565` by default:

```toml
[proxy]
bind = "0.0.0.0"
public_port = 25565
```

Players connect to:

```text
your-domain-or-ip:25565
```

Players should not connect directly to Forge on port `25566`.

### 7. Validate the Configuration

```bash
python3 idle-server.py --check-config
```

Expected output:

```text
Configuration is valid: /path/to/idle-server.toml
```

### 8. Start the Proxy Manually

```bash
./start-proxy.sh
```

Alternatively:

```bash
python3 idle-server.py
```

## Crafty Controller Integration

Crafty integration is disabled by default:

```toml
[crafty]
enabled = false
forward_console_commands = true
show_forge_output = true
```

Enable it when Crafty starts the proxy:

```toml
[crafty]
enabled = true
forward_console_commands = true
show_forge_output = true
```

When Crafty integration is enabled:

- `status` displays proxy and backend status.
- `stop`, `exit`, or `quit` stops the proxy.
- Forge is stopped only when it was started by this proxy.
- Other Crafty console commands can be forwarded to Forge while Forge runs.
- Forge output can be displayed in Crafty's console and the proxy log.

Example forwarded Forge commands:

```text
list
say Hello from the proxy
whitelist add PlayerName
```

### Crafty Start Script

`start-proxy.sh` finds its own directory and starts `idle-server.py`.

Therefore it works correctly even if Crafty's Working Directory is the Forge
server directory while the script itself is stored in the proxy subdirectory.

Make it executable:

```bash
chmod +x minecraft-idle-server-proxy/start-proxy.sh
```

Crafty must start `start-proxy.sh`, **not** Forge's normal `run.sh`, Java
command, or `server.jar`.

### Crafty Configuration

If the proxy is installed as `minecraft-idle-server-proxy/` inside the Forge
server directory, use these values in Crafty:

```text
Working Directory:
  /path/to/forge-server

Execution Command:
  ./minecraft-idle-server-proxy/start-proxy.sh

Stop Command:
  stop

Log Location:
  ./minecraft-idle-server-proxy/idle-server.log

Server IP:
  127.0.0.1

Server Port:
  25565
```

For the example Crafty directory:

```text
Working Directory:
  /var/opt/minecraft/crafty/crafty-4/servers/e82847a6-38b2-4699-acf4-ca36d62ba064

Execution Command:
  ./minecraft-idle-server-proxy/start-proxy.sh

Stop Command:
  stop

Log Location:
  ./minecraft-idle-server-proxy/idle-server.log

Server IP:
  127.0.0.1

Server Port:
  25565
```

The IP and port configured in Crafty must point to the public proxy:

```text
127.0.0.1:25565
```

Forge itself should listen only on:

```text
127.0.0.1:25566
```

## Command-Line Options

Show the installed version:

```bash
python3 idle-server.py --version
```

Validate the configuration:

```bash
python3 idle-server.py --check-config
```

Check Python syntax:

```bash
python3 -m py_compile idle-server.py
```

## Configuration

### Ports

```toml
[server]
host = "127.0.0.1"
port = 25566

[proxy]
bind = "0.0.0.0"
public_port = 25565
```

The ports must be different:

```text
Public proxy:  0.0.0.0:25565
Forge backend: 127.0.0.1:25566
```

### Time Settings

```toml
[time]
sleep_after = 600
start_timeout = 300
estimated_start_time = 90
player_check_interval = 15
```

`estimated_start_time` is only used for player-facing startup messages and
does not change the actual startup timeout.

### Dynamic Message Placeholders

| Placeholder | Description |
|---|---|
| `{elapsed}` | Seconds since the current Forge startup began |
| `{remaining}` | Estimated seconds remaining until Forge is ready |
| `{estimate}` | Configured `estimated_start_time` |
| `{timeout}` | Configured `start_timeout` |

Example:

```toml
[join]
starting = "§2☻ The server is starting!\n§7Please wait about {remaining} seconds\n§7and reconnect."
```

### MOTD Settings

```toml
[motd]
sleeping = "§8☾ Server sleeping§7 - Join to wake it"
starting = "§2☻ Server starting..."
starting_detail = "§7Started {elapsed}s ago - about {remaining}s remaining"
starting_slow = "§e☻ Startup is taking longer than expected"
failed = "§4✖ Server failed to start"
```

Minecraft formatting color codes using `§` are supported for proxy MOTDs.

## systemd Service

The setup helper can optionally create:

```text
minecraft-idle-server-proxy.service
```

Useful commands:

```bash
sudo systemctl status minecraft-idle-server-proxy
sudo systemctl start minecraft-idle-server-proxy
sudo systemctl stop minecraft-idle-server-proxy
sudo systemctl restart minecraft-idle-server-proxy
sudo journalctl -u minecraft-idle-server-proxy -f
```

Do not configure Crafty to start the proxy if the same proxy is managed by
`systemd`.

## Important Notes

### First Join Requires a Reconnect

When Forge is sleeping, the first player who joins wakes the server and
receives a message asking them to reconnect after startup.

This is intentional because holding a Minecraft login connection open while a
large Forge server starts can cause client timeouts.

### Existing Forge Processes

If Forge was started manually or by another service before the proxy starts,
the proxy recognizes it as running and forwards connections to it.

For safety, the proxy does not stop Forge processes it did not start itself.

### Do Not Expose the Backend Port

Use this Forge configuration:

```properties
server-ip=127.0.0.1
server-port=25566
```

Only the public proxy port should be reachable by players.

### Do Not Use the Same Port Twice

Incorrect:

```text
Public proxy:  0.0.0.0:25565
Forge backend: 0.0.0.0:25565
```

Correct:

```text
Public proxy:  0.0.0.0:25565
Forge backend: 127.0.0.1:25566
```

## Logs

By default, logs are written to:

```text
idle-server.log
```

With the recommended Crafty layout, the file is located here:

```text
/path/to/forge-server/minecraft-idle-server-proxy/idle-server.log
```

Log rotation is configured in `idle-server.toml`:

```toml
[log]
file = "idle-server.log"
level = "INFO"
max_bytes = 5242880
backup_count = 3
```

## Troubleshooting

### Configuration File Not Found

```bash
cp idle-server.toml.example idle-server.toml
```

### Python 3.11 Is Required

```bash
python3 --version
```

Install Python 3.11 or newer if necessary.

### Start Script Is Not Executable

```bash
chmod +x start-proxy.sh
./start-proxy.sh
```

### Address Already in Use

```bash
ss -tulpn | grep -E '25565|25566'
```

### Forge Does Not Start

Check the proxy log:

```bash
tail -f idle-server.log
```

Then verify:

- `server.directory` points to the Forge server directory.
- The Forge `command` is correct.
- Java is available through `PATH`.
- Forge starts normally without the proxy.
- The backend port matches `server.properties`.
- Forge is not using port `25565`.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for
details.

## Disclaimer

This is an independent community project and is not affiliated with, endorsed
by, or associated with Mojang Studios, Microsoft, Forge, or Crafty Controller.
Minecraft is a trademark of Microsoft.