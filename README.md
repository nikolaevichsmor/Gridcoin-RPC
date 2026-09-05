# Gridcoin Discord Rich Presence

A lightweight daemon and portable utility that displays your live Gridcoin staking status, estimated pending reward, network difficulty, top BOINC project RAC, total magnitude, block height, pool share, and time since last stake directly on your Discord profile.

[![Tests](https://github.com/nikolaevichsmor/Gridcoin-RPC/actions/workflows/tests.yml/badge.svg)](https://github.com/nikolaevichsmor/Gridcoin-RPC/actions/workflows/tests.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Discord Rich Presence](https://img.shields.io/badge/Discord-Rich%20Presence-5865F2.svg)](https://discord.com/)
[![Gridcoin](https://img.shields.io/badge/Network-Gridcoin-purple.svg)](https://gridcoin.us/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Preview

```text
+-------------------------------------------------------------+
|  Playing a game                                             |
|  [Gridcoin Icon]  Gridcoin                                  |
|                   Staking: 59,468.15 GRC                    |
|                   Est. Reward: 1,304.02 GRC                 |
|                   (cycles: Reward / Difficulty / RAC / ...) |
|                   161:51:54 elapsed                         |
|                                                             |
|            [ GitHub ]             [ What is this? ]         |
+-------------------------------------------------------------+
```

- **Smart Staking Status (Line 1)**: Displays your active staking coin balance with thousands separators (e.g. `Staking: 59,468.15 GRC`). If your wallet is locked or staking is disabled, automatically reflects this with `Not Staking: 59,468.15 GRC` or `Staking: Inactive`.
- **Configurable Rotating Stats (Line 2)**:
  - **First-Run Default**: On first launch, **only 1 checkbox is enabled by default** — **Estimated Reward**.
  - Users can enable any combination of the 6 available metrics via the system tray submenu:
    1. **Estimated Reward**: Pending BOINC research reward (`Est. Reward: 1,304.02 GRC`) or Proof-of-Stake hunt status (**`Searching for Blocks`** if pending reward is 0 / investor mode).
    2. **Difficulty**: Current network difficulty (`Difficulty: 12.34`).
    3. **Top Project RAC**: Top contributing BOINC project by Recent Average Credit (`odlk1 RAC: 38,426`).
    4. **Total Magnitude**: Total BOINC magnitude across projects (`Magnitude: 142.50` or `Magnitude: 100`).
    5. **Block Height**: Current network block count (`Block: #3,201,400`).
    6. **Pool Share**: Percentage of current active staking coins relative to total network stake weight (`Pool Share: 0.05%`, or up to 4 decimal places for smaller stakes e.g. `Pool Share: 0.0042%`).
  - When multiple metrics are enabled, the display smoothly alternates between them every N update cycles (configurable via `SWITCH_CYCLES`).
  - **Constraint Guard**: At least one metric must always remain active (the app prevents unchecking the last remaining active metric).
- **Elapsed Timer**: Live timer counting up from your last confirmed stake transaction.
- **Dual Buttons**: Direct profile links to project source on GitHub and the official Gridcoin website ("What is this?").
- **Auto-Reconnect**: If your wallet is closed or restarted, the status updates to `Wallet Offline` and reconnects as soon as the wallet opens.
- **Settings Persistence**: Custom tray selections (presence toggle, active display stats) automatically persist across restarts in `settings.json`.
- **Safe Log Rotation**: Built-in rotating log handler ensures `daemon.log` never exceeds 5 MB (with 2 backups).

---

## Quick Start (Windows Portable)

The easiest way to run the daemon on Windows:

1. Download **`Gridcoin-RPC-v1.2-win64.zip`** from [Releases](https://github.com/nikolaevichsmor/Gridcoin-RPC/releases).
2. Unzip the archive to any folder.
3. Make sure your Gridcoin wallet is open.
4. Launch `Gridcoin-RPC.exe`.

It automatically reads your RPC credentials from `%APPDATA%\GridcoinResearch\gridcoinresearch.conf`, places an icon in your system tray (near the clock), and starts broadcasting to Discord.

### System Tray Controls
Right-click the Gridcoin icon in your tray to:
- **Turn Off / On Presence**: Pause or resume Discord broadcasting without closing the app.
- **Cycle Stats (Line 2)**: Hover to open the stats submenu and toggle checkmarks (✓) for:
  - [x] **Estimated Reward** *(Enabled by default on first launch)*
  - [ ] **Difficulty**
  - [ ] **Top Project RAC**
  - [ ] **Total Magnitude**
  - [ ] **Block Height**
  - [ ] **Pool Share**
  *(Applies immediately to Discord and automatically persists in `settings.json`; at least one stat must remain active)*.
- **Start with Windows**: Toggle automatic startup on Windows boot (safely manages `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- **What is Gridcoin? (Website)**: Open gridcoin.us in your browser.
- **GitHub Repository**: Open this project page in your browser.
- **Quit**: Clear your Discord status and exit cleanly.

---

## Quick Start (Linux Standalone)

For Linux (x86_64), no Python installation is required:

1. Download **`Gridcoin-RPC-v1.2-linux-x86_64.tar.gz`** from [Releases](https://github.com/nikolaevichsmor/Gridcoin-RPC/releases).
2. Extract and run:
   ```bash
   tar -xzvf Gridcoin-RPC-*-linux-x86_64.tar.gz
   chmod +x Gridcoin-RPC
   ./Gridcoin-RPC
   ```
It automatically finds `~/.GridcoinResearch/gridcoinresearch.conf`, runs headlessly as a background daemon, and supports graceful shutdown via `SIGTERM` / `SIGINT`.

---

## Running from Source (Python)

If you prefer running from Python source on Windows, Linux, or macOS:

### 1. Requirements
- Python 3.8+
- Gridcoin core wallet running locally with RPC enabled (`server=1` in `gridcoinresearch.conf`)
- Discord desktop app running

### 2. Setup
```bash
git clone https://github.com/nikolaevichsmor/Gridcoin-RPC.git
cd Gridcoin-RPC
pip install -r requirements.txt
```

### 3. Run
- **Direct run**:
  ```bash
  python main.py
  ```
- **Silent background run (Windows)**:
  Double-click `scripts/start_background.bat`. To stop, double-click `scripts/stop_background.bat` or use the tray icon.
- Logs are written to `daemon.log` (with automatic size rotation up to 5 MB per file).

---

## Configuration (Optional)

By default, the application automatically locates your `gridcoinresearch.conf` on Windows, Linux, and macOS. 

If your wallet runs on a non-standard port or remote machine, create a `.env` file from the provided template:

```bash
cp .env.example .env
```

Available variables:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DISCORD_CLIENT_ID` | Discord Application ID | Pre-configured Gridcoin app |
| `RPC_USER` | RPC username | Auto-detected from `gridcoinresearch.conf` |
| `RPC_PASSWORD` | RPC password | Auto-detected from `gridcoinresearch.conf` |
| `RPC_HOST` | Gridcoin node IP | `127.0.0.1` |
| `RPC_PORT` | Gridcoin RPC port | `15715` |
| `UPDATE_INTERVAL` | Status refresh interval in seconds | `15` (minimum to respect Discord rate limits) |
| `SWITCH_CYCLES` | Number of update cycles before alternating between selected stats | `2` |
| `DISCORD_LARGE_IMAGE` | Asset key for large profile image | `gridcoin` |
| `DISCORD_LARGE_TEXT` | Tooltip for large profile image | `Gridcoin Network` |
| `DISCORD_SMALL_IMAGE_STAKING` | Badge asset key when staking is active | `staking` |
| `DISCORD_SMALL_IMAGE_OFFLINE` | Badge asset key when wallet is locked or offline | `offline` |

---

## Testing

Run the included test suite:

```bash
python -m unittest discover tests
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

