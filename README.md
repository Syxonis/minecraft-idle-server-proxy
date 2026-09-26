# Minecraft Idle Server Proxy

A lightweight Python proxy for Minecraft Forge servers.

The proxy keeps a Forge server offline while nobody is playing. A Minecraft
server-list ping does **not** start the server. When a player tries to join,
the proxy starts Forge in the background and tells the player to reconnect
after startup is complete.

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

The Python source can be checked on Windows, but the included `install.sh`,
Crafty integration, and optional `systemd` service setup are intended mainly
for Linux systems.

## Requirements

- Python **3.11** or newer
- A working Minecraft Forge server
- Java compatible with the selected Forge/Minecraft version
- Forge configured to listen on a local backend port
- Permission to bind the public Minecraft port, normally `25565`

Python 3.11 is required because this project uses Python's built-in `tomllib`
module to read TOML configuration files.

Check the Python version:

```bash
python3 --version
```

On Windows PowerShell:

```powershell
py -3.11 --version
```

## Installation

### Quick Install from GitHub (Linux)

Clone the repository and start the interactive Linux setup helper:

```bash
git clone https://github.com/Syxonis/minecraft-idle-server-proxy.git && \
cd minecraft-idle-server-proxy && \
chmod +x install.sh && \
./install.sh
```

The setup helper creates a local configuration, asks for the Forge server
directory, optionally enables Crafty integration, validates the configuration,
and can create a `systemd` service.

> The proxy repository should normally be installed separately from the Forge
> server directory. During setup, `install.sh` asks for the absolute path to
> the directory containing the Forge server files.

### Option A: Interactive Setup Helper for Linux

If the repository was already cloned or downloaded, run:

```bash
chmod +x install.sh
./install.sh
```

The setup helper can:

- Check for Python 3.11 or newer
- Check that required project files exist
- Create `idle-server.toml` from `idle-server.toml.example`
- Detect possible Forge server directories
- Ask for the absolute Forge server directory
- Keep or overwrite an existing local configuration after confirmation
- Enable or disable optional Crafty Controller console integration
- Validate the configuration
- Optionally create a `systemd` service
- Optionally enable and start the created `systemd` service

The helper does **not**:

- Install Java
- Install Forge
- Modify Forge files or world files
- Delete `session.lock`
- Modify `server.properties`
- Modify firewall or router rules
- Overwrite `idle-server.toml` without confirmation

> Crafty console integration and a `systemd` service are alternative deployment
> methods. Do not use both to run the same proxy instance.

### Option B: Manual Installation

#### 1. Clone the Repository

```bash
git clone https://github.com/Syxonis/minecraft-idle-server-proxy.git
cd minecraft-idle-server-proxy
```

Alternatively, download the repository as a ZIP file and extract it.

#### 2. Make the Start Script Executable

The repository includes `start-proxy.sh`, which starts the proxy using Python
with unbuffered output.

```bash
chmod +x start-proxy.sh
```

You can start the proxy manually with:

```bash
./start-proxy.sh
```

#### 3. Create the Local Configuration

Linux/macOS:

```bash
cp idle-server.toml.example idle-server.toml
```

Windows PowerShell:

```powershell
Copy-Item idle-server.toml.example idle-server.toml
```

The local `idle-server.toml` is ignored by Git. This allows every server owner
to use their own paths, ports, commands, and server messages.

#### 4. Configure the Forge Server Directory

Open `idle-server.toml` and configure the `[server]` section.

Example for Forge 1.20.1:

```toml
[server]
directory = "/path/to/your/forge-server"

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

The `directory` setting must point to the directory containing your Forge
server files, such as `mods/`, `world/`, `libraries/`, `server.properties`,
and `user_jvm_args.txt`.

#### 5. Configure `server.properties`

Forge must use a different port than the public proxy port.

Recommended Forge configuration:

```properties
server-ip=127.0.0.1
server-port=25566
```

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

Players should not connect directly to the Forge backend port.

#### 6. Validate the Configuration

Linux:

```bash
python3 idle-server.py --check-config
```

Windows PowerShell:

```powershell
py -3.11 idle-server.py --check-config
```

Expected output:

```text
Configuration is valid: /path/to/idle-server.toml
```

#### 7. Start the Proxy

Recommended on Linux:

```bash
./start-proxy.sh
```

Alternatively:

```bash
python3 idle-server.py
```

On Windows PowerShell:

```powershell
py -3.11 idle-server.py
```

The proxy remains online while Forge is sleeping.

## Command-Line Options

Show the installed proxy version:

```bash
python3 idle-server.py --version
```

Validate the configuration without starting the proxy:

```bash
python3 idle-server.py --check-config
```

Check Python syntax:

```bash
python3 -m py_compile idle-server.py
```

On Windows PowerShell, use `py -3.11` instead of `python3`.

## Configuration

### Recommended Directory Layout

Keep the proxy repository separate from the Forge server directory:

```text
/opt/minecraft/
├── minecraft-idle-server-proxy/
│   ├── idle-server.py
│   ├── idle-server.toml
│   ├── idle-server.toml.example
│   ├── start-proxy.sh
│   └── install.sh
│
└── forge-server/
    ├── libraries/
    ├── mods/
    ├── world/
    ├── server.properties
    └── user_jvm_args.txt
```

Example configuration:

```toml
[server]
directory = "/opt/minecraft/forge-server"
```

The proxy changes its working directory to `server.directory` before starting
Forge. Relative paths in `server.command` are therefore resolved inside the
Forge server directory.

### Server and Proxy Ports

Example:

```toml
[server]
host = "127.0.0.1"
port = 25566

[proxy]
bind = "0.0.0.0"
public_port = 25565
```

The backend port and public proxy port must be different:

```text
Public proxy:  0.0.0.0:25565
Forge backend: 127.0.0.1:25566
```

### Time Settings

```toml
[time]
# Stop Forge after this many seconds without online players.
sleep_after = 600

# Maximum time Forge may take to open its backend port.
start_timeout = 300

# Expected startup time used only in status and join messages.
estimated_start_time = 90

# Interval for checking the online player count.
player_check_interval = 15
```

`estimated_start_time` is only an estimate shown to players. It does not
change the actual startup timeout.

The estimated remaining time is calculated as:

```text
remaining = max(0, estimated_start_time - elapsed_startup_time)
```

### Dynamic Message Placeholders

The following placeholders can be used in startup and join messages:

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

## Crafty Controller Integration

Crafty integration is optional and disabled by default:

```toml
[crafty]
enabled = false
forward_console_commands = true
show_forge_output = true
```

Enable it when Crafty is used to start the proxy:

```toml
[crafty]
enabled = true
forward_console_commands = true
show_forge_output = true
```

When enabled:

- `status` displays proxy and backend status.
- `stop`, `exit`, or `quit` stops the proxy.
- Forge is stopped too, but only if it was started by this proxy.
- Other console commands can be forwarded to Forge when
  `forward_console_commands` is enabled.
- Forge output can be written to the proxy log and Crafty console when
  `show_forge_output` is enabled.

Example Forge commands that can be forwarded through Crafty:

```text
list
say Hello from the proxy
whitelist add PlayerName
```

### Crafty Start Script

The included `start-proxy.sh` script starts the proxy with unbuffered Python
output. This allows proxy logs and Forge output to appear immediately in the
Crafty console.

Make it executable:

```bash
chmod +x start-proxy.sh
```

Crafty must start `start-proxy.sh`, not Forge's usual `run.sh`, `server.jar`,
or Java command.

### Crafty Configuration

The recommended setup keeps the proxy repository separate from the Forge
server directory.

Use the following values in Crafty:

```text
Working Directory:
  /path/to/minecraft-idle-server-proxy

Execution Command:
  ./start-proxy.sh

Stop Command:
  stop

Log Location:
  ./idle-server.log

Server IP:
  127.0.0.1

Server Port:
  25565
```

Replace `/path/to/minecraft-idle-server-proxy` with the absolute path to this
proxy repository.

The Forge directory is configured separately in `idle-server.toml`:

```toml
[server]
directory = "/path/to/your/forge-server"
```

Crafty's displayed server IP and port should point to the public proxy,
normally `127.0.0.1:25565`, rather than the Forge backend port.

## systemd Service

The interactive setup helper can optionally create a service named:

```text
minecraft-idle-server-proxy.service
```

Useful commands after installation:

```bash
sudo systemctl status minecraft-idle-server-proxy
sudo systemctl start minecraft-idle-server-proxy
sudo systemctl stop minecraft-idle-server-proxy
sudo systemctl restart minecraft-idle-server-proxy
sudo journalctl -u minecraft-idle-server-proxy -f
```

The service starts the proxy after system boot. Forge itself remains asleep
until a player attempts to join.

Do not configure Crafty to start the proxy when the same proxy instance is
already managed by `systemd`.

## Important Notes

### First Join Requires a Reconnect

When Forge is sleeping, the first player who tries to join wakes the server.
That player receives a message asking them to reconnect after startup.

This is intentional. Holding a Minecraft login connection open while a large
Forge server starts is unreliable and can cause client timeouts.

### Existing Forge Processes

If Forge was started manually or by another service before the proxy starts,
the proxy recognizes it as running and forwards connections to it.

For safety, the proxy does not stop Forge processes that it did not start
itself.

### Do Not Expose the Backend Port

The recommended setup is:

```properties
server-ip=127.0.0.1
server-port=25566
```

If Forge must listen on all network interfaces, block the backend port using a
firewall and do not expose it through your router.

Only the public proxy port should be accessible to players.

### Do Not Use the Same Port Twice

Incorrect configuration:

```text
Public proxy:  0.0.0.0:25565
Forge backend: 0.0.0.0:25565
```

Correct configuration:

```text
Public proxy:  0.0.0.0:25565
Forge backend: 127.0.0.1:25566
```

## Logs

By default, logs are written to:

```text
idle-server.log
```

Log rotation is configured in `idle-server.toml`:

```toml
[log]
file = "idle-server.log"
level = "INFO"
max_bytes = 5242880
backup_count = 3
```

Available log levels:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

## Troubleshooting

### Configuration File Not Found

Create the local configuration file:

```bash
cp idle-server.toml.example idle-server.toml
```

On Windows PowerShell:

```powershell
Copy-Item idle-server.toml.example idle-server.toml
```

### Python 3.11 Is Required

Check your Python version:

```bash
python3 --version
```

On Windows PowerShell:

```powershell
py --version
```

Install Python 3.11 or newer if necessary.

### Start Script Is Not Executable

Make the script executable:

```bash
chmod +x start-proxy.sh
```

Then start it again:

```bash
./start-proxy.sh
```

### Address Already in Use

Another program is already using the public proxy port or Forge backend port.

Check listening ports on Linux:

```bash
ss -tulpn | grep -E '25565|25566'
```

### Forge Does Not Start

Check the proxy log:

```bash
tail -f idle-server.log
```

Then verify:

- `server.directory` is correct.
- The Forge `command` is correct.
- Java is installed and available through `PATH`.
- Forge starts normally without this proxy.
- The backend port matches `server.properties`.
- Forge is not already using the public proxy port.

### Players Can Connect Directly to Forge

Ensure Forge binds locally:

```properties
server-ip=127.0.0.1
server-port=25566
```

Also ensure the backend port is not exposed through your firewall, hosting
panel, or router.

### systemd Service Does Not Start

Check service status and logs:

```bash
sudo systemctl status minecraft-idle-server-proxy
sudo journalctl -u minecraft-idle-server-proxy -n 100 --no-pager
```

Verify that:

- The project directory still exists.
- The configured service user can access the Forge directory.
- Python 3.11 or newer is available.
- `idle-server.toml` exists and passes `--check-config`.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for
details.

## Disclaimer

This is an independent community project and is not affiliated with, endorsed
by, or associated with Mojang Studios, Microsoft, Forge, or Crafty Controller.
Minecraft is a trademark of Microsoft.