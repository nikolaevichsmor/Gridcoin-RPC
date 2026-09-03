import logging
import os
import sys
import time
from typing import Any, Optional

from dotenv import load_dotenv
from pypresence import Presence
from pypresence.exceptions import DiscordError, DiscordNotFound, PipeClosed

from rpc_client import GridcoinRPC

from pathlib import Path

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

GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "https://github.com/nikolaevichsmor/Gridcoin-RPC").strip()
GITHUB_BUTTON_LABEL = os.getenv("GITHUB_BUTTON_LABEL", "GitHub").strip()


def get_presence_buttons() -> Optional[list]:
    """Return Discord presence button configuration if URL is set."""
    if GITHUB_REPO_URL:
        label = GITHUB_BUTTON_LABEL[:32] if GITHUB_BUTTON_LABEL else "GitHub"
        return [{"label": label, "url": GITHUB_REPO_URL}]
    return None


def get_active_staking_coins(mining_info: dict) -> float:
    """Extract active staking coin weight from getmininginfo response.

    Checks 'stakeweight' -> 'valuesum', 'value', 'legacy', or direct float.
    """
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
    """Extract expected research reward from BoincRewardPending (matches wallet GUI).

    Falls back to 10.0 GRC CBR for investors without pending BOINC rewards.
    """
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
    """Retrieve timestamp of the latest stake transaction from listtransactions."""
    try:
        txs = grc.call("listtransactions", ["*", count])
        if not isinstance(txs, list):
            return None

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


def main():
    logger.info("Starting Gridcoin Discord Rich Presence daemon...")
    logger.info(f"Target node: {RPC_HOST}:{RPC_PORT}, update interval: {POLL_INTERVAL}s")

    grc = GridcoinRPC(RPC_HOST, RPC_PORT, RPC_USER, RPC_PASS)
    discord = DiscordPresenceManager(CLIENT_ID)
    discord.connect()

    last_stake_time: Optional[int] = None
    last_tx_check = 0.0

    while True:
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
                # If not found in the last 100 txs and no stake cached yet, look deeper (up to 1000)
                if not fetched_time and last_stake_time is None:
                    fetched_time = get_last_stake_timestamp(grc, count=1000)
                if fetched_time:
                    last_stake_time = fetched_time
                last_tx_check = current_time

            # 4. Update Rich Presence
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
            logger.error(f"Unexpected error in main loop: {err}", exc_info=True)
            time.sleep(5)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user.")
        sys.exit(0)
