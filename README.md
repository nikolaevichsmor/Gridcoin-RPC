# Gridcoin Discord Rich Presence

A lightweight, resilient Python daemon that displays your live **Gridcoin** staking balance, estimated reward, and elapsed time since the last stake on your Discord profile via Discord Rich Presence (IPC).

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Discord Rich Presence](https://img.shields.io/badge/Discord-Rich%20Presence-5865F2.svg)](https://discord.com/)
[![Gridcoin](https://img.shields.io/badge/Network-Gridcoin-purple.svg)](https://gridcoin.us/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Preview

```text
+--------------------------------------------------+
|  Playing a game                                  |
|  [Gridcoin Icon]  Gridcoin                       |
|                   Staking: 59,468.15 GRC         |
|                   Est. Reward: 1,298.79 GRC      |
|                   159:04:33 elapsed              |
|                                                  |
|                   [ GitHub ]                     |
+--------------------------------------------------+
```

- **App Name / Header**: `Gridcoin` (managed via Discord Application ID).
- **Staking**: Active staking coins with 2 decimal places and thousands separators (e.g. `Staking: 59,468.15 GRC`).
- **Estimated Reward**: Estimated reward on next stake (10 GRC CBR + pending BOINC researcher reward, e.g. `Est. Reward: 1,298.79 GRC`).
- **Elapsed Timer**: Passes the timestamp of your last stake transaction to Discord's native counter (`159:04:33 elapsed` / `2 days elapsed`).
- **GitHub Button**: Clickable button linking directly to this repository.
- **Fail-safe Recovery**: If the Gridcoin node goes offline or restarts, the daemon automatically updates the status to `Wallet Offline` / `Reconnecting...` without crashing, and restores stats as soon as the node is back.

---

## Prerequisites

- **Python 3.8** or newer
- **Discord** desktop application running locally
- **Gridcoin Research** core wallet (GUI or daemon) with JSON-RPC enabled

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/nikolaevichsmor/Gridcoin-RPC.git
cd Gridcoin-RPC
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Configuration

### 1. Configure Gridcoin Node for RPC

Ensure your `gridcoinresearch.conf` has RPC enabled (`server=1`) and valid credentials:

```ini
server=1
rpcuser=your_rpc_username
rpcpassword=your_rpc_password
rpcport=15715
```

Default config locations:
- **Windows**: `%APPDATA%\GridcoinResearch\gridcoinresearch.conf`
- **Linux**: `~/.GridcoinResearch/gridcoinresearch.conf`
- **macOS**: `~/Library/Application Support/GridcoinResearch/gridcoinresearch.conf`

*Note: If you made changes to `gridcoinresearch.conf`, restart your Gridcoin wallet.*

---

### 2. Configure the Daemon (`.env`)

Copy `.env.example` to `.env`:

**On Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**On Linux / macOS:**
```bash
cp .env.example .env
```

Open `.env` in a text editor and fill in your RPC credentials:

```ini
# Discord Application Client ID (Defaults to pre-registered Gridcoin application)
DISCORD_CLIENT_ID=1545044211945177139

# Gridcoin RPC Credentials
RPC_USER=your_rpc_username
RPC_PASSWORD=your_rpc_password
RPC_HOST=127.0.0.1
RPC_PORT=15715

# Polling interval in seconds (minimum 15 to respect Discord rate limits)
UPDATE_INTERVAL=15
```

### Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DISCORD_CLIENT_ID` | Discord Application Client ID | `1545044211945177139` |
| `RPC_USER` | RPC username from `gridcoinresearch.conf` | *Auto-detected* |
| `RPC_PASSWORD` | RPC password from `gridcoinresearch.conf` | *Auto-detected* |
| `RPC_HOST` | Gridcoin node host address | `127.0.0.1` |
| `RPC_PORT` | Gridcoin JSON-RPC port | `15715` |
| `UPDATE_INTERVAL` | Polling frequency in seconds (minimum `15`) | `15` |

---

## Running the Daemon

### Option 1: Standalone Executable (Windows)

Download `Gridcoin-RPC.exe` from [Releases](https://github.com/nikolaevichsmor/Gridcoin-RPC/releases):
- Double-click `Gridcoin-RPC.exe` to run.
- **Single Instance**: Opening it multiple times will not spawn duplicates.
- **System Tray Icon**: An icon appears in your Windows system tray (near the clock):
  - **Turn Off / On Presence**: Toggle presence broadcast without quitting.
  - **GitHub Repository**: Quick link to project source.
  - **Quit**: Cleanly removes presence from Discord and terminates the process.

### Option 2: One-Click Background Scripts

If running from source on Windows:
- **Start**: Double-click `start_background.bat` (or `main.pyw`).
- **Stop**: Double-click `stop_background.bat` or use the system tray icon.
- **Logs**: Real-time activity and RPC status are logged to `daemon.log`.

### Option 3: Terminal

Run directly from command prompt or PowerShell:
```bash
python main.py
```
To stop, press `Ctrl + C` or exit via the system tray.

---

## Testing

A comprehensive unit test suite is included:

```bash
python -m unittest test_daemon.py
```

---

## Notes & FAQ

> [!NOTE]
> **Discord Button Clicking**:
> By design in Discord, profile buttons cannot be clicked by the owner of the profile inside their own Discord client (Discord disables button interaction on self-cards to prevent accidental clicks). However, the button is **fully clickable and functional for all other Discord users and friends** who view your profile.

> [!TIP]
> **Discord IPC Rate Limits**:
> Discord enforces a rate limit on IPC rich presence updates. The daemon automatically enforces a minimum polling interval of 15 seconds (`POLL_INTERVAL >= 15`).

---

## License

This project is open-source and available under the [MIT License](LICENSE).
