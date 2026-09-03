import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Any, Optional

from dotenv import load_dotenv
from pypresence import Presence
from pypresence.exceptions import DiscordError, DiscordNotFound, PipeClosed

import webbrowser
from infi.systray import SysTrayIcon
from rpc_client import GridcoinRPC

# Set base directory to the script's location
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Configure logging (supports both console and hidden pythonw execution)
log_handlers = [logging.FileHandler(BASE_DIR / "daemon.log", encoding="utf-8")]
if sys.stdout is not None:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=log_handlers,
)
logger = logging.getLogger("GridcoinDiscordRPC")

# Load environment configuration from project directory
load_dotenv(BASE_DIR / ".env")

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1545044211945177139")
RPC_USER = os.getenv("RPC_USER", "")
RPC_PASS = os.getenv("RPC_PASSWORD", "")
RPC_HOST = os.getenv("RPC_HOST", "127.0.0.1")
RPC_PORT = int(os.getenv("RPC_PORT", "15715"))
POLL_INTERVAL = max(int(os.getenv("UPDATE_INTERVAL", "15")), 15)

GITHUB_REPO_URL = "https://github.com/nikolaevichsmor/Gridcoin-RPC"
GITHUB_BUTTON_LABEL = "GitHub"

# Global state for tray and single instance
_lock_socket = None
running = True
presence_enabled = True
discord_mgr: Optional["DiscordPresenceManager"] = None


def acquire_single_instance_lock(port: int = 45715) -> bool:
    """Ensure only one instance of the application runs at a time via loopback socket."""
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def find_gridcoin_conf() -> Optional[Path]:
    """Find default gridcoinresearch.conf location across OSes."""
    custom_conf = os.getenv("GRIDCOIN_CONF")
    if custom_conf:
        p = Path(custom_conf)
        if p.is_file():
            return p

    local_conf = BASE_DIR / "gridcoinresearch.conf"
    if local_conf.is_file():
        return local_conf

    if sys.platform == "win32":
        appdata = os.getenv("APPDATA")
        if appdata:
            conf = Path(appdata) / "GridcoinResearch" / "gridcoinresearch.conf"
            if conf.is_file():
                return conf
    elif sys.platform == "darwin":
        conf = Path.home() / "Library" / "Application Support" / "GridcoinResearch" / "gridcoinresearch.conf"
        if conf.is_file():
            return conf
    else:
        conf = Path.home() / ".GridcoinResearch" / "gridcoinresearch.conf"
        if conf.is_file():
            return conf
    return None


def auto_detect_rpc_credentials():
    """Auto-detect RPC credentials from gridcoinresearch.conf if not set in .env."""
    global RPC_USER, RPC_PASS, RPC_PORT
    if RPC_USER and RPC_PASS:
        return
    conf_path = find_gridcoin_conf()
    if not conf_path:
        return
    try:
        with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                for comment_char in ("#", ";"):
                    if comment_char in line:
                        line = line.split(comment_char, 1)[0].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().lower()
                v = v.strip().strip('"').strip("'")
                if k == "rpcuser" and not RPC_USER:
                    RPC_USER = v
                elif k == "rpcpassword" and not RPC_PASS:
                    RPC_PASS = v
                elif k == "rpcport" and RPC_PORT == 15715:
                    try:
                        RPC_PORT = int(v)
                    except ValueError:
                        pass
        logger.info(f"Auto-detected RPC credentials from {conf_path}")
    except Exception as e:
        logger.warning(f"Failed reading {conf_path}: {e}")


def get_presence_buttons() -> Optional[list]:
    """Return Discord presence button configuration if URL is set."""
    if GITHUB_REPO_URL:
        label = GITHUB_BUTTON_LABEL[:32] if GITHUB_BUTTON_LABEL else "GitHub"
        return [{"label": label, "url": GITHUB_REPO_URL}]
    return None


def get_active_staking_coins(mining_info: dict) -> float:
    """Extract active staking coin weight from getmininginfo response."""
    if not isinstance(mining_info, dict):
        return 0.0

    stakeweight = mining_info.get("stakeweight")
    if isinstance(stakeweight, dict):
        raw_val = (
            stakeweight.get("valuesum")
            or stakeweight.get("value")
            or stakeweight.get("legacy")
            or 0.0
        )
        try:
            return float(raw_val)
        except (ValueError, TypeError):
            return 0.0
    elif isinstance(stakeweight, (int, float)):
        return float(stakeweight)

    return 0.0


def format_details(active_coins: float) -> str:
    """Format details string according to staking coin count."""
    if active_coins <= 0:
        return "Staking: 0.00 GRC"
    return f"Staking: {active_coins:,.2f} GRC"


def get_expected_reward(mining_info: dict) -> float:
    """Extract expected research reward from BoincRewardPending (matches wallet GUI)."""
    if not isinstance(mining_info, dict):
        return 10.0
    pending = mining_info.get("BoincRewardPending")
    if pending is not None:
        try:
            val = float(pending)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    return 10.0


def format_reward(reward: float) -> str:
    """Format estimated stake reward string."""
    return f"Est. Reward: {reward:,.2f} GRC"


def format_magnitude(raw_mag: Any) -> str:
    """Format magnitude string. Null, 0, or missing strictly returns 'Mag: None'."""
    if raw_mag is None or raw_mag == 0 or raw_mag == "0":
        return "Mag: None"
    return f"Mag: {raw_mag}"


def get_last_stake_timestamp(grc: GridcoinRPC, count: int = 100) -> Optional[int]:
    """Retrieve timestamp of the latest confirmed stake transaction from listtransactions."""
    for query_count in (count, 500) if count < 500 else (count,):
        try:
            txs = grc.call("listtransactions", ["*", query_count])
            if not isinstance(txs, list):
                continue

            stake_txs = [
                tx
                for tx in txs
                if isinstance(tx, dict)
                and tx.get("category") in ("generate", "immature", "stake")
                and tx.get("confirmations", 0) >= 0
            ]
            if stake_txs:
                latest_tx = max(
                    stake_txs,
                    key=lambda x: x.get("blocktime") or x.get("time") or 0,
                )
                timestamp = latest_tx.get("blocktime") or latest_tx.get("time")
                if timestamp is not None:
                    return int(timestamp)
        except Exception as err:
            logger.warning(f"Failed to fetch last stake transaction: {err}")
            break

    return None


class DiscordPresenceManager:
    """Manages connection and presence updates to Discord IPC with auto-reconnect."""

    def __init__(self, client_id: str):
        self.client_id = client_id
        self.rpc: Optional[Presence] = None
        self.connected = False

    def connect(self) -> bool:
        if self.connected and self.rpc:
            return True
        try:
            self.rpc = Presence(self.client_id)
            self.rpc.connect()
            self.connected = True
            logger.info("Successfully connected to Discord IPC.")
            return True
        except (DiscordNotFound, DiscordError, ConnectionRefusedError, FileNotFoundError, Exception) as err:
            self.connected = False
            self.rpc = None
            logger.warning(f"Discord IPC unavailable: {err}. Retrying in background...")
            return False

    def update(self, **kwargs) -> bool:
        if not self.connected:
            if not self.connect():
                return False
        try:
            self.rpc.update(**kwargs)
            return True
        except (PipeClosed, DiscordError, BrokenPipeError, ConnectionResetError, Exception) as err:
            logger.warning(f"Discord IPC disconnected during update: {err}. Resetting connection.")
            self.connected = False
            try:
                if self.rpc:
                    self.rpc.close()
            except Exception:
                pass
            self.rpc = None
            return False

    def clear(self) -> bool:
        if self.connected and self.rpc:
            try:
                self.rpc.clear()
                return True
            except Exception as err:
                logger.warning(f"Error clearing presence: {err}")
        return False

    def close(self):
        if self.rpc:
            try:
                self.rpc.clear()
            except Exception:
                pass
            try:
                self.rpc.close()
            except Exception:
                pass
            self.connected = False
            self.rpc = None


def polling_worker(grc: GridcoinRPC, discord: DiscordPresenceManager):
    """Background thread worker that polls Gridcoin RPC and updates Discord."""
    global running, presence_enabled
    last_stake_time: Optional[int] = None
    last_tx_check = 0.0

    while running:
        if not presence_enabled:
            time.sleep(1)
            continue

        try:
            # 1. Fetch mining information
            mining_info = grc.call("getmininginfo")
            active_coins = get_active_staking_coins(mining_info)
            expected_reward = get_expected_reward(mining_info)
            details_str = format_details(active_coins)

            # 2. Estimated Reward as State
            state_str = format_reward(expected_reward)

            # 3. Check for last stake timestamp every 60 seconds
            current_time = time.time()
            if current_time - last_tx_check > 60 or last_stake_time is None:
                fetched_time = get_last_stake_timestamp(grc, count=100)
                if not fetched_time and last_stake_time is None:
                    fetched_time = get_last_stake_timestamp(grc, count=1000)
                if fetched_time:
                    last_stake_time = fetched_time
                last_tx_check = current_time

            # 4. Update Rich Presence
            if presence_enabled:
                update_payload = {
                    "details": details_str,
                    "state": state_str,
                }
                if last_stake_time:
                    update_payload["start"] = int(last_stake_time)

                buttons = get_presence_buttons()
                if buttons:
                    update_payload["buttons"] = buttons

                discord.update(**update_payload)
                logger.info(
                    f"Presence updated: [{details_str}] | [{state_str}] | "
                    f"Last Stake: {last_stake_time}"
                )

        except ConnectionError as rpc_err:
            if presence_enabled:
                logger.warning(f"Gridcoin wallet unreachable ({rpc_err}). Setting offline status.")
                offline_payload = {
                    "details": "Wallet Offline",
                    "state": "Reconnecting...",
                }
                buttons = get_presence_buttons()
                if buttons:
                    offline_payload["buttons"] = buttons
                discord.update(**offline_payload)
        except Exception as err:
            logger.error(f"Unexpected error in polling loop: {err}", exc_info=True)
            time.sleep(5)

        # Responsive sleep loop
        for _ in range(POLL_INTERVAL):
            if not running or not presence_enabled:
                break
            time.sleep(1)


def main():
    global discord_mgr, presence_enabled, running

    if not acquire_single_instance_lock():
        logger.warning("Another instance of Gridcoin-RPC is already running. Exiting.")
        sys.exit(0)

    logger.info("Starting Gridcoin Discord Rich Presence daemon...")
    auto_detect_rpc_credentials()
    logger.info(f"Target node: {RPC_HOST}:{RPC_PORT}, update interval: {POLL_INTERVAL}s")

    grc = GridcoinRPC(RPC_HOST, RPC_PORT, RPC_USER, RPC_PASS)
    discord_mgr = DiscordPresenceManager(CLIENT_ID)
    discord_mgr.connect()

    # Start background polling thread
    worker_thread = threading.Thread(target=polling_worker, args=(grc, discord_mgr), daemon=True)
    worker_thread.start()

    def get_icon_file_path() -> Optional[str]:
        for rel_path in (
            "assets/tray_icon.ico",
            "tray_icon.ico",
            "assets/app_icon.ico",
            "app_icon.ico",
        ):
            if hasattr(sys, "_MEIPASS"):
                p = Path(sys._MEIPASS) / rel_path
                if p.is_file():
                    return str(p)
            p = BASE_DIR / rel_path
            if p.is_file():
                return str(p)
        return None

    # System tray callbacks
    def on_tray_toggle(systray):
        global presence_enabled, discord_mgr
        presence_enabled = not presence_enabled
        state_msg = "enabled" if presence_enabled else "paused"
        logger.info(f"Presence {state_msg} via system tray.")
        if not presence_enabled and discord_mgr:
            discord_mgr.clear()

    def on_tray_github(systray):
        if GITHUB_REPO_URL:
            webbrowser.open(GITHUB_REPO_URL)

    def on_tray_quit(systray):
        global running, discord_mgr
        logger.info("Exiting application via system tray.")
        running = False
        if discord_mgr:
            discord_mgr.close()

    tray = None
    if sys.platform == "win32":
        icon_path = get_icon_file_path()
        if icon_path:
            menu_options = (
                ("Turn Off / On Presence", None, on_tray_toggle),
                ("GitHub Repository", None, on_tray_github),
            )
            try:
                tray = SysTrayIcon(icon_path, "Gridcoin Discord RPC", menu_options, on_quit=on_tray_quit)
                tray.start()
            except Exception as err:
                logger.warning(f"Could not start system tray: {err}")

    try:
        while running:
            time.sleep(1)
    finally:
        if tray:
            try:
                tray.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user.")
        if discord_mgr:
            discord_mgr.close()
        sys.exit(0)
