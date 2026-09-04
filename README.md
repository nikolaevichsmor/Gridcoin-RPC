# Gridcoin Discord Rich Presence

A lightweight daemon and portable Windows utility that shows your live Gridcoin staking status, estimated pending reward, network difficulty, and time since last stake directly on your Discord profile.

[![Tests](https://github.com/nikolaevichsmor/Gridcoin-RPC/actions/workflows/tests.yml/badge.svg)](https://github.com/nikolaevichsmor/Gridcoin-RPC/actions/workflows/tests.yml)
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
|                   Est. Reward: 1,304.02 GRC      |
|                   (cycles: Reward / Diff / RAC)  |
|                   161:51:54 elapsed              |
|                                                  |
|         [ GitHub ]       [ What is this? ]       |
+--------------------------------------------------+
```

- **Staking**: Active staking coin balance with thousands separators.
- **Dynamic 3-Way State**: Automatically alternates every N update cycles between pending reward (`Est. Reward: 1,304.02 GRC`), network difficulty (`Difficulty: 12.34`), and your top BOINC project RAC (`odlk1 RAC: 38,426`). If no active project RAC exists, seamlessly alternates between reward and difficulty.
- **Elapsed Timer**: Live timer counting up from your last confirmed stake transaction.
- **Dual Buttons**: Direct profile links to project source on GitHub and the official Gridcoin website ("What is this?").
- **Auto-Reconnect**: If your wallet is closed or restarted, the status updates to `Wallet Offline` and reconnects as soon as the wallet opens.

---

## Quick Start (Windows Portable)

The easiest way to run the daemon on Windows:

1. Download **`Gridcoin-RPC-v1.1-win64.zip`** from [Releases](https://github.com/nikolaevichsmor/Gridcoin-RPC/releases).
2. Unzip the archive to any folder.
3. Make sure your Gridcoin wallet is open.
4. Launch `Gridcoin-RPC.exe`.

It automatically reads your RPC credentials from `%APPDATA%\GridcoinResearch\gridcoinresearch.conf`, places an icon in your system tray (near the clock), and starts broadcasting to Discord.

### System Tray Controls
Right-click the Gridcoin icon in your tray to:
- **Turn Off / On Presence**: Pause or resume Discord broadcasting without closing the app.
- **Start with Windows**: Toggle automatic startup on Windows boot (safely manages `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- **What is Gridcoin? (Website)**: Open gridcoin.us in your browser.
- **GitHub Repository**: Open this project page in your browser.
- **Quit**: Clear your Discord status and exit.

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
- Logs are written to `daemon.log`.

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
| `SWITCH_CYCLES` | Number of update cycles before alternating between Est. Reward and Difficulty | `2` |

---

## Testing

Run the included test suite:

```bash
python -m unittest discover tests
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

