# Gridcoin Discord Rich Presence Daemon

A lightweight Python daemon that displays Gridcoin staking statistics and magnitude on your Discord profile via Discord Rich Presence (IPC).

## Features

- **Discord Rich Presence Integration**:
  - **App Name / Header**: `Gridcoin` (via Discord Application ID).
  - **Details**: Displays current active staking coins with thousands separators and 2 decimal places (e.g. `Staking: 12,450.50 GRC` or `Staking: 0.00 GRC`).
  - **State**: Displays magnitude (e.g. `Magnitude: 142.5`). Strictly displays `Magnitude: None` if magnitude is 0, null, or missing.
  - **Elapsed Timer**: Passes the Unix timestamp of the last stake transaction into Discord IPC (`start`), so Discord automatically counts elapsed time (e.g. `04:12:35 elapsed` or `2 days elapsed`).
  - **Clean Profile**: No mandatory custom image assets.
- **Resilient Polling & Reconnection**:
  - Polls every 15 seconds (respects Discord IPC rate limit).
  - Caches and periodically checks for the latest stake transaction (`category` in `generate`, `immature`, `stake`).
  - Graceful fallback: If the Gridcoin node is unreachable, the presence automatically switches to `Wallet Offline` / `Reconnecting...` without crashing.
  - Automatically reconnects if Discord is launched after the daemon or restarted.

## Requirements

- Python 3.8+
- Gridcoin Research core wallet with RPC enabled (`gridcoinresearchd` or GUI wallet with server enabled)
- Discord desktop client

## Installation

1. Clone or copy this repository:
   ```bash
   git clone https://github.com/nikolaevichsmor/Gridcoin-RPC.git
	cd Gridcoin-RPC
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to match your `gridcoinresearch.conf` settings:
   ```ini
   DISCORD_CLIENT_ID=1545044211945177139
   RPC_USER=your_rpc_username
   RPC_PASSWORD=your_rpc_password
   RPC_HOST=127.0.0.1
   RPC_PORT=15715
   UPDATE_INTERVAL=15
   ```

## Usage

Run the daemon:
```bash
python main.py
```

Run tests:
```bash
python -m unittest test_daemon.py
```
