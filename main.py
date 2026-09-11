from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional, Tuple

from dotenv import load_dotenv
from pypresence import Presence

from rpc_client import GridcoinRPC

# infi.systray dereferences ctypes.windll at import time, so it can only be
# imported on Windows. The tray is Windows-only anyway (see main()).
if sys.platform == "win32":
    from infi.systray import SysTrayIcon

# Set base directory to the script's location
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Writable application directory (for settings.json, daemon.log)
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BASE_DIR
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_FILE = APP_DIR / "daemon.log"

# Configure rotating logging (max 5 MB with 2 backups to prevent disk bloat)
log_handlers = [
    RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
]
if sys.stdout is not None:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=log_handlers,
)
logger = logging.getLogger("GridcoinDiscordRPC")

# Load environment configuration from project directory or app directory
load_dotenv(BASE_DIR / ".env")
if APP_DIR != BASE_DIR and (APP_DIR / ".env").is_file():
    load_dotenv(APP_DIR / ".env")

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1545044211945177139")
RPC_USER = os.getenv("RPC_USER", "")
RPC_PASS = os.getenv("RPC_PASSWORD", "")
RPC_HOST = os.getenv("RPC_HOST", "127.0.0.1")
RPC_PORT = int(os.getenv("RPC_PORT", "15715"))
POLL_INTERVAL = max(int(os.getenv("UPDATE_INTERVAL", "15")), 15)
SWITCH_CYCLES = max(int(os.getenv("SWITCH_CYCLES", "2")), 1)

GITHUB_REPO_URL = "https://github.com/nikolaevichsmor/Gridcoin-RPC"
GITHUB_BUTTON_LABEL = "GitHub"

GRIDCOIN_WEBSITE_URL = "https://gridcoin.us/"
GRIDCOIN_WEBSITE_LABEL = "What is this?"

DISCORD_LARGE_IMAGE = os.getenv("DISCORD_LARGE_IMAGE", "gridcoin")
DISCORD_LARGE_TEXT = os.getenv("DISCORD_LARGE_TEXT", "Gridcoin Network")
DISCORD_SMALL_IMAGE_STAKING = os.getenv("DISCORD_SMALL_IMAGE_STAKING", "staking")
DISCORD_SMALL_IMAGE_OFFLINE = os.getenv("DISCORD_SMALL_IMAGE_OFFLINE", "offline")

DEFAULT_SETTINGS = {
    "presence_enabled": True,
    "hide_balance": True,
    "cycle_show_reward": True,
    "cycle_show_difficulty": False,
    "cycle_show_rac": False,
    "cycle_show_mag": False,
    "cycle_show_block": False,
    "cycle_show_pool_share": False,
    "cycle_show_total_value": False,
    "cycle_show_price": False,
    "cycle_show_peers": False,
}


def load_settings() -> dict:
    """Load user settings from settings.json or return defaults."""
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.is_file():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULT_SETTINGS:
                    if k in data and isinstance(data[k], bool):
                        settings[k] = data[k]
                for k in ("rpc_host", "rpc_port", "rpc_user", "rpc_password"):
                    if k in data and data[k] is not None:
                        settings[k] = data[k]
                active_flags = [
                    settings["cycle_show_reward"],
                    settings["cycle_show_difficulty"],
                    settings["cycle_show_rac"],
                    settings["cycle_show_mag"],
                    settings["cycle_show_block"],
                    settings["cycle_show_pool_share"],
                    settings["cycle_show_total_value"],
                    settings["cycle_show_price"],
                    settings["cycle_show_peers"],
                ]
                if not any(active_flags):
                    settings["cycle_show_reward"] = True
        except Exception as e:
            logger.warning(f"Could not read settings from {SETTINGS_FILE}: {e}")
    return settings


def save_settings() -> bool:
    """Persist current user settings to settings.json."""
    data = {
        "presence_enabled": presence_enabled,
        "hide_balance": hide_balance,
        "cycle_show_reward": cycle_show_reward,
        "cycle_show_difficulty": cycle_show_difficulty,
        "cycle_show_rac": cycle_show_rac,
        "cycle_show_mag": cycle_show_mag,
        "cycle_show_block": cycle_show_block,
        "cycle_show_pool_share": cycle_show_pool_share,
        "cycle_show_total_value": cycle_show_total_value,
        "cycle_show_price": cycle_show_price,
        "cycle_show_peers": cycle_show_peers,
    }
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError as e:
        logger.warning(f"Failed writing settings to {SETTINGS_FILE}: {e}")
        return False


# Global state for tray and single instance
_initial_settings = load_settings()
_lock_socket = None
running = True
presence_enabled = _initial_settings["presence_enabled"]
hide_balance: bool = _initial_settings["hide_balance"]
discord_mgr: Optional["DiscordPresenceManager"] = None
AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_APP_NAME = "Gridcoin-RPC"

# Display state cycling toggles (Line 2 of Rich Presence)
cycle_show_reward: bool = _initial_settings["cycle_show_reward"]
cycle_show_difficulty: bool = _initial_settings["cycle_show_difficulty"]
cycle_show_rac: bool = _initial_settings["cycle_show_rac"]
cycle_show_mag: bool = _initial_settings["cycle_show_mag"]
cycle_show_block: bool = _initial_settings["cycle_show_block"]
cycle_show_pool_share: bool = _initial_settings["cycle_show_pool_share"]
cycle_show_total_value: bool = _initial_settings["cycle_show_total_value"]
cycle_show_price: bool = _initial_settings["cycle_show_price"]
cycle_show_peers: bool = _initial_settings["cycle_show_peers"]
update_event = threading.Event()


def get_executable_path() -> str:
    """Return quoted path to the executable or script for Windows autostart."""
    # When packaged with PyInstaller, sys.frozen is True and sys.executable points to .exe
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        return f'"{exe_path}"'

    # If running from source, check if compiled .exe is available
    for candidate in (
        BASE_DIR / "dist" / "Gridcoin-RPC" / "Gridcoin-RPC.exe",
        BASE_DIR / "dist" / "Gridcoin-RPC.exe",
        BASE_DIR / "Gridcoin-RPC.exe",
    ):
        if candidate.is_file():
            return f'"{candidate.resolve()}"'

    # Fallback to pythonw.exe or python.exe executing main.py
    python_exe = Path(sys.executable)
    pythonw = python_exe.parent / "pythonw.exe"
    runner = pythonw if pythonw.is_file() else python_exe
    main_script = (BASE_DIR / "main.py").resolve()
    return f'"{runner}" "{main_script}"'


def is_autostart_enabled() -> bool:
    """Check if autostart with Windows is registered in HKCU."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, AUTOSTART_APP_NAME)
            return bool(val)
    except (FileNotFoundError, OSError):
        return False


def set_autostart(enable: bool) -> bool:
    """Enable or disable autostart with Windows in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                exe_path = get_executable_path()
                winreg.SetValueEx(key, AUTOSTART_APP_NAME, 0, winreg.REG_SZ, exe_path)
                logger.info(f"Enabled autostart with Windows: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_APP_NAME)
                    logger.info("Disabled autostart with Windows.")
                except FileNotFoundError:
                    pass
        return True
    except OSError as err:
        logger.warning(f"Failed to update autostart in registry: {err}")
        return False


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
        conf = (
            Path.home()
            / "Library"
            / "Application Support"
            / "GridcoinResearch"
            / "gridcoinresearch.conf"
        )
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
        if RPC_HOST not in ("127.0.0.1", "localhost"):
            logger.info(
                f"Local gridcoinresearch.conf not found. Using remote node at {RPC_HOST}:{RPC_PORT}"
            )
        else:
            logger.info(
                "Local gridcoinresearch.conf not found. Using configured/default RPC settings."
            )
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


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Gridcoin Discord Rich Presence Daemon")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without GUI / system tray (recommended for Linux systemd services)",
    )
    parser.add_argument(
        "--rpc-host",
        dest="rpc_host",
        type=str,
        default=None,
        help="Gridcoin node RPC host/IP (overrides config and auto-detection)",
    )
    parser.add_argument(
        "--rpc-port",
        dest="rpc_port",
        type=int,
        default=None,
        help="Gridcoin node RPC port (overrides config and auto-detection)",
    )
    parser.add_argument(
        "--rpc-user",
        dest="rpc_user",
        type=str,
        default=None,
        help="Gridcoin node RPC username",
    )
    parser.add_argument(
        "--rpc-password",
        dest="rpc_password",
        type=str,
        default=None,
        help="Gridcoin node RPC password",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Gridcoin-RPC v1.2.3",
    )
    parsed = parser.parse_args(argv)
    if parsed.rpc_port is not None and not (1 <= parsed.rpc_port <= 65535):
        parser.error(f"--rpc-port must be between 1 and 65535, got {parsed.rpc_port}")
    return parsed


def apply_rpc_config(args: Optional[argparse.Namespace] = None):
    """Apply RPC configuration cascading: settings.json -> environment (.env) -> auto-detection -> CLI args."""
    global RPC_HOST, RPC_PORT, RPC_USER, RPC_PASS
    settings = load_settings()

    # 1. settings.json
    if "rpc_host" in settings and settings["rpc_host"]:
        RPC_HOST = str(settings["rpc_host"])
    if "rpc_port" in settings and settings["rpc_port"] is not None:
        try:
            RPC_PORT = int(settings["rpc_port"])
        except (ValueError, TypeError):
            pass
    if "rpc_user" in settings and settings["rpc_user"]:
        RPC_USER = str(settings["rpc_user"])
    if "rpc_password" in settings and settings["rpc_password"]:
        RPC_PASS = str(settings["rpc_password"])

    # 2. Environment variables (.env has already been loaded)
    env_host = os.getenv("RPC_HOST") or os.getenv("rpc_host")
    if env_host:
        RPC_HOST = env_host
    env_port = os.getenv("RPC_PORT") or os.getenv("rpc_port")
    if env_port:
        try:
            RPC_PORT = int(env_port)
        except (ValueError, TypeError):
            pass
    env_user = os.getenv("RPC_USER") or os.getenv("rpc_user")
    if env_user:
        RPC_USER = env_user
    env_pass = os.getenv("RPC_PASSWORD") or os.getenv("rpc_password")
    if env_pass:
        RPC_PASS = env_pass

    # 3. Auto-detect from local conf (if user/pass not set)
    auto_detect_rpc_credentials()

    # 4. CLI arguments (highest priority)
    if args:
        if getattr(args, "rpc_host", None):
            RPC_HOST = args.rpc_host
        if getattr(args, "rpc_port", None) is not None:
            RPC_PORT = args.rpc_port
        if getattr(args, "rpc_user", None):
            RPC_USER = args.rpc_user
        if getattr(args, "rpc_password", None):
            RPC_PASS = args.rpc_password


def get_presence_buttons() -> Optional[list]:
    """Return Discord presence buttons (up to 2 buttons: GitHub repo & Gridcoin website)."""
    buttons = []
    if GITHUB_REPO_URL:
        label = GITHUB_BUTTON_LABEL[:32] if GITHUB_BUTTON_LABEL else "GitHub"
        buttons.append({"label": label, "url": GITHUB_REPO_URL})
    if GRIDCOIN_WEBSITE_URL:
        label = GRIDCOIN_WEBSITE_LABEL[:32] if GRIDCOIN_WEBSITE_LABEL else "What is this?"
        buttons.append({"label": label, "url": GRIDCOIN_WEBSITE_URL})
    return buttons if buttons else None


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


def is_wallet_staking(mining_or_staking_info: Any) -> Optional[bool]:
    """Extract boolean staking status from getstakinginfo or getmininginfo response."""
    if isinstance(mining_or_staking_info, dict):
        val = mining_or_staking_info.get("staking")
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, str)):
            return str(val).lower() in ("true", "1")
    return None


def get_blockchain_sync_status(blockchain_info: Any) -> Tuple[bool, float]:
    """Detect if Gridcoin node is synchronizing blockchain and return (is_syncing, progress).

    Returns (is_syncing, progress) where progress is float in range [0.0, 1.0].
    """
    if not isinstance(blockchain_info, dict):
        return False, 1.0

    ibd = blockchain_info.get("initialblockdownload")
    if ibd is True:
        prog = blockchain_info.get("verificationprogress", 0.0)
        try:
            return True, max(0.0, min(float(prog), 1.0))
        except (ValueError, TypeError):
            return True, 0.0

    raw_prog = blockchain_info.get("verificationprogress")
    if raw_prog is not None:
        try:
            prog_val = float(raw_prog)
            if 0.0 <= prog_val < 0.9995:
                blocks = blockchain_info.get("blocks")
                headers = blockchain_info.get("headers")
                if isinstance(headers, int) and isinstance(blocks, int) and headers > blocks + 5:
                    return True, prog_val
                elif prog_val < 0.999:
                    return True, prog_val
        except (ValueError, TypeError):
            pass

    blocks = blockchain_info.get("blocks")
    headers = blockchain_info.get("headers")
    if isinstance(blocks, int) and isinstance(headers, int) and headers > 0:
        if headers - blocks > 20:
            prog = blocks / headers
            return True, max(0.0, min(prog, 1.0))

    return False, 1.0


def format_sync_details(sync_progress: float, block_height: Optional[int] = None) -> str:
    """Format Line 1 status during blockchain sync."""
    pct = sync_progress * 100.0
    if 0.0 < pct < 100.0:
        return f"Syncing: {pct:.1f}%"
    if block_height and block_height > 0:
        return f"Syncing: #{block_height:,}"
    return "Syncing Blockchain"


def format_details(
    active_coins: float,
    is_staking: Optional[bool] = None,
    hide_balance: bool = False,
) -> str:
    """Format details string according to staking coin count and active staking status."""
    if hide_balance:
        if is_staking is False:
            if active_coins > 0:
                return "Not Staking ********* GRC"
            return "Staking: Inactive"
        return "Staking ********* GRC"

    if is_staking is False:
        if active_coins > 0:
            return f"Not Staking: {active_coins:,.2f} GRC"
        return "Staking: Inactive"
    if active_coins <= 0:
        return "Staking: 0.00 GRC"
    return f"Staking: {active_coins:,.2f} GRC"


def get_presence_assets(
    is_offline: bool = False,
    is_staking: Optional[bool] = None,
    is_syncing: bool = False,
    sync_progress: float = 1.0,
) -> dict:
    """Return dictionary of Discord presence image assets and hover tooltips."""
    assets = {}
    if DISCORD_LARGE_IMAGE:
        assets["large_image"] = DISCORD_LARGE_IMAGE
        if DISCORD_LARGE_TEXT:
            assets["large_text"] = DISCORD_LARGE_TEXT

    if is_offline:
        if DISCORD_SMALL_IMAGE_OFFLINE:
            assets["small_image"] = DISCORD_SMALL_IMAGE_OFFLINE
            assets["small_text"] = "Wallet Offline"
    elif is_syncing:
        if DISCORD_SMALL_IMAGE_OFFLINE:
            assets["small_image"] = DISCORD_SMALL_IMAGE_OFFLINE
            pct = sync_progress * 100.0
            assets["small_text"] = (
                f"Syncing ({pct:.1f}%)" if 0.0 < pct < 100.0 else "Syncing Blockchain"
            )
    elif is_staking is False:
        if DISCORD_SMALL_IMAGE_OFFLINE:
            assets["small_image"] = DISCORD_SMALL_IMAGE_OFFLINE
            assets["small_text"] = "Staking Inactive / Locked"
    elif is_staking is True or is_staking is None:
        if DISCORD_SMALL_IMAGE_STAKING:
            assets["small_image"] = DISCORD_SMALL_IMAGE_STAKING
            assets["small_text"] = "Staking Active"

    return assets


def get_expected_reward(mining_info: dict) -> float:
    """Extract expected research reward from BoincRewardPending (matches wallet GUI)."""
    if not isinstance(mining_info, dict):
        return 0.0
    pending = mining_info.get("BoincRewardPending")
    if pending is not None:
        try:
            val = float(pending)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    return 0.0


def format_reward(reward: Optional[float]) -> str:
    """Format estimated stake reward string. If reward is 0 or None, display block search status."""
    if reward is None or reward <= 0:
        return "Searching for Blocks"
    return f"Est. Reward: {reward:,.2f} GRC"


def get_difficulty(mining_info: dict) -> float:
    """Extract difficulty from getmininginfo response."""
    if not isinstance(mining_info, dict):
        return 0.0

    raw_diff = mining_info.get("difficulty")
    if isinstance(raw_diff, (int, float)):
        return float(raw_diff)
    elif isinstance(raw_diff, str):
        try:
            return float(raw_diff)
        except (ValueError, TypeError):
            return 0.0
    elif isinstance(raw_diff, dict):
        for key in ("proof-of-stake", "current", "pos", "target"):
            val = raw_diff.get(key)
            if isinstance(val, (int, float, str)):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        for val in raw_diff.values():
            if isinstance(val, (int, float)):
                return float(val)
            elif isinstance(val, str):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass

    return 0.0


def format_difficulty(diff: float) -> str:
    """Format network difficulty string."""
    if diff <= 0:
        return "Difficulty: 0.00"
    if 0 < diff < 0.01:
        return f"Difficulty: {diff:.4f}"
    return f"Difficulty: {diff:,.2f}"


def get_top_project_rac(explain_magnitude_data: Any) -> Optional[str]:
    """Extract top BOINC project and formatted RAC from explainmagnitude RPC response."""
    if not isinstance(explain_magnitude_data, list):
        return None
    valid_projects = []
    for item in explain_magnitude_data:
        if not isinstance(item, dict):
            continue
        proj = item.get("project", "")
        if not proj or proj.lower() == "total":
            continue
        try:
            rac = float(item.get("rac", 0))
            if rac > 0:
                valid_projects.append((proj, rac))
        except (ValueError, TypeError):
            continue
    if not valid_projects:
        return None
    top_proj, top_rac = max(valid_projects, key=lambda x: x[1])
    return f"{top_proj} RAC: {round(top_rac):,}"


def format_magnitude(raw_mag: Any) -> str:
    """Format magnitude string. Null, 0, or missing returns 'Magnitude: None'."""
    if raw_mag is None or raw_mag == 0 or raw_mag == "0":
        return "Magnitude: None"
    try:
        val = float(raw_mag)
        if val <= 0:
            return "Magnitude: None"
        if val.is_integer():
            return f"Magnitude: {int(val)}"
        return f"Magnitude: {val:,.2f}"
    except (ValueError, TypeError):
        return f"Magnitude: {raw_mag}"


def get_total_magnitude(
    explain_magnitude_data: Any = None, mining_info: Any = None
) -> Optional[float]:
    """Extract total BOINC magnitude from explainmagnitude or getmininginfo."""
    if isinstance(explain_magnitude_data, list):
        for item in explain_magnitude_data:
            if isinstance(item, dict) and item.get("project", "").lower() == "total":
                try:
                    return float(item.get("magnitude", 0))
                except (ValueError, TypeError):
                    pass

    if isinstance(mining_info, dict):
        raw_mag = mining_info.get("magnitude")
        if raw_mag is not None:
            try:
                return float(raw_mag)
            except (ValueError, TypeError):
                pass
        stk = mining_info.get("staking")
        if isinstance(stk, dict) and "magnitude" in stk:
            try:
                return float(stk["magnitude"])
            except (ValueError, TypeError):
                pass

    return None


def get_block_height(mining_info: dict) -> Optional[int]:
    """Extract current block height from getmininginfo response."""
    if not isinstance(mining_info, dict):
        return None
    blocks = mining_info.get("blocks")
    if blocks is not None:
        try:
            return int(blocks)
        except (ValueError, TypeError):
            pass
    return None


def format_block_height(blocks: Any) -> str:
    """Format current block height string."""
    try:
        val = int(blocks)
        if val > 0:
            return f"Block: #{val:,}"
    except (ValueError, TypeError):
        pass
    return "Block: Unknown"


def get_network_stake_weight(mining_info: dict) -> float:
    """Extract estimated total network staking GRC weight from RPC response.

    Gridcoin returns 'netstakingGRCvalue' (estimated total GRC currently staking)
    and 'netstakeweight' (raw network weight, which has an internal factor of 80x).
    We prefer 'netstakingGRCvalue' to compare against the user's active coins in GRC.
    If only 'netstakeweight' is available, we divide by 80.0 to convert to GRC coins.
    """
    if not isinstance(mining_info, dict):
        return 0.0

    # 1. Prefer direct netstakingGRCvalue (actual GRC coins staking across the network)
    for key in ("netstakingGRCvalue", "netstakinggrcvalue", "net_staking_grc_value"):
        val = mining_info.get(key)
        if val is not None:
            try:
                f_val = float(val)
                if f_val > 0:
                    return f_val
            except (ValueError, TypeError):
                pass

    # 2. Fallback to netstakeweight / 80.0
    net_weight = mining_info.get("netstakeweight")
    if net_weight is not None:
        try:
            f_weight = float(net_weight)
            if f_weight > 0:
                return f_weight / 80.0
        except (ValueError, TypeError):
            pass

    return 0.0


def format_pool_share(active_coins: float, net_weight: float) -> str:
    """Format active staking pool share percentage."""
    if net_weight <= 0 or active_coins <= 0:
        return "Pool Share: 0.00%"
    share = (active_coins / net_weight) * 100.0
    if share > 100.0:
        share = 100.0
    if share < 0.01:
        return f"Pool Share: {share:.4f}%"
    return f"Pool Share: {share:.2f}%"


_cached_price: Optional[float] = None
_last_price_fetch: float = 0.0
PRICE_CACHE_TTL = 300.0  # 5 minutes in-memory cache


def get_grc_usd_price(timeout: int = 5) -> Optional[float]:
    """Fetch current GRC/USD price with in-memory caching.

    Primary: CoinGecko API.
    Fallback: CoinPaprika API.
    """
    global _cached_price, _last_price_fetch
    now = time.time()
    if _cached_price is not None and (now - _last_price_fetch < PRICE_CACHE_TTL):
        return _cached_price

    # 1. Primary: CoinGecko
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=gridcoin-research&vs_currencies=usd",
            headers={"User-Agent": "Gridcoin-Discord-RPC/1.2.3"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            price = data.get("gridcoin-research", {}).get("usd")
            if price is not None and float(price) > 0:
                _cached_price = float(price)
                _last_price_fetch = now
                return _cached_price
    except Exception as err:
        logger.debug(f"CoinGecko price lookup failed: {err}")

    # 2. Fallback: CoinPaprika
    try:
        req = urllib.request.Request(
            "https://api.coinpaprika.com/v1/tickers/grc-gridcoin",
            headers={"User-Agent": "Gridcoin-Discord-RPC/1.2.3"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            price = data.get("quotes", {}).get("USD", {}).get("price")
            if price is not None and float(price) > 0:
                _cached_price = float(price)
                _last_price_fetch = now
                return _cached_price
    except Exception as err:
        logger.debug(f"CoinPaprika price lookup failed: {err}")

    return _cached_price


def get_total_balance(grc: GridcoinRPC, active_coins: float = 0.0) -> float:
    """Fetch total coin balance from Gridcoin node via getwalletinfo or getbalance."""
    try:
        info = grc.call("getwalletinfo")
        if isinstance(info, dict) and "balance" in info:
            balance = float(info["balance"])
            immature = float(info.get("immature_balance", 0.0))
            return max(balance + immature, 0.0)
    except Exception:
        pass

    try:
        bal = grc.call("getbalance")
        if isinstance(bal, (int, float)):
            return max(float(bal), 0.0)
    except Exception:
        pass

    return max(active_coins, 0.0)


def format_total_value_usd(total_coins: float, price_usd: Optional[float]) -> str:
    """Format total holding value in USD."""
    if price_usd is None or price_usd <= 0 or total_coins <= 0:
        return "Total Value: $0.00"
    val = total_coins * price_usd
    if val >= 1000:
        return f"Total Value: ${val:,.2f}"
    if val >= 1:
        return f"Total Value: ${val:.2f}"
    return f"Total Value: ${val:.4f}"


def format_grc_price(price_usd: Optional[float]) -> str:
    """Format current GRC market price in USD."""
    if price_usd is None or price_usd <= 0:
        return "GRC Price: N/A"
    return f"GRC Price: ${price_usd:.5f}"


def get_peer_count(grc: GridcoinRPC, network_info: Optional[dict] = None) -> Optional[int]:
    """Fetch number of connected network peers from getnetworkinfo or getinfo."""
    if isinstance(network_info, dict) and "connections" in network_info:
        try:
            return int(network_info["connections"])
        except (ValueError, TypeError):
            pass

    try:
        net = grc.call("getnetworkinfo")
        if isinstance(net, dict) and "connections" in net:
            return int(net["connections"])
    except Exception:
        pass

    try:
        info = grc.call("getinfo")
        if isinstance(info, dict) and "connections" in info:
            return int(info["connections"])
    except Exception:
        pass

    return None


def format_peers(peer_count: Optional[int]) -> str:
    """Format network peer count string."""
    if peer_count is None:
        return "Peers: 0"
    return f"Peers: {peer_count}"


def get_alternating_state(
    cycle: int,
    switch_cycles: int,
    reward: float,
    difficulty: float,
    project_rac: Optional[str] = None,
    total_mag: Optional[float] = None,
    block_height: Optional[int] = None,
    pool_share_str: Optional[str] = None,
    total_value_str: Optional[str] = None,
    price_str: Optional[str] = None,
    peers_str: Optional[str] = None,
    show_reward: bool = True,
    show_difficulty: bool = True,
    show_rac: bool = True,
    show_mag: bool = False,
    show_block: bool = False,
    show_pool_share: bool = False,
    show_total_value: bool = False,
    show_price: bool = False,
    show_peers: bool = False,
) -> str:
    """Alternate between active display metrics every switch_cycles update cycles."""
    candidates = []
    if show_reward:
        candidates.append(format_reward(reward))
    if show_difficulty:
        candidates.append(format_difficulty(difficulty))
    if show_rac and project_rac:
        candidates.append(project_rac)
    if show_mag and total_mag is not None:
        candidates.append(format_magnitude(total_mag))
    if show_block and block_height is not None:
        candidates.append(format_block_height(block_height))
    if show_pool_share and pool_share_str:
        candidates.append(pool_share_str)
    if show_total_value:
        candidates.append(total_value_str if total_value_str is not None else "Total Value: $0.00")
    if show_price:
        candidates.append(price_str if price_str is not None else "GRC Price: N/A")
    if show_peers:
        candidates.append(peers_str if peers_str is not None else "Peers: 0")

    if not candidates:
        if show_rac:
            candidates.append("RAC: None")
        elif show_block:
            candidates.append("Block: Unknown")
        elif show_pool_share:
            candidates.append("Pool Share: 0.00%")
        elif show_total_value:
            candidates.append("Total Value: $0.00")
        elif show_price:
            candidates.append("GRC Price: N/A")
        elif show_peers:
            candidates.append("Peers: 0")
        elif show_mag:
            candidates.append("Magnitude: None")
        elif show_difficulty:
            candidates.append(format_difficulty(difficulty))
        else:
            candidates.append(format_reward(reward))

    effective_switch = max(int(switch_cycles), 1)
    step = cycle // effective_switch
    return candidates[step % len(candidates)]


def trigger_presence_update() -> None:
    """Signal background worker to perform an immediate presence refresh."""
    update_event.set()


def handle_exit_signal(signum, frame=None):
    """Handle graceful termination on SIGINT or SIGTERM."""
    global running, discord_mgr
    sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    logger.info(f"Received exit signal {sig_name}. Shutting down gracefully...")
    running = False
    trigger_presence_update()
    if discord_mgr:
        discord_mgr.close()
    sys.exit(0)


try:
    signal.signal(signal.SIGINT, handle_exit_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_exit_signal)
except (ValueError, OSError):
    pass


def toggle_stat(stat_name: str) -> bool:
    """Toggle a display stat in line 2, ensuring at least one remains enabled.

    Returns True if state changed, False if blocked by the constraint.
    """
    global cycle_show_reward, cycle_show_difficulty, cycle_show_rac
    global cycle_show_mag, cycle_show_block, cycle_show_pool_share
    global cycle_show_total_value, cycle_show_price, cycle_show_peers

    active_count = sum(
        [
            cycle_show_reward,
            cycle_show_difficulty,
            cycle_show_rac,
            cycle_show_mag,
            cycle_show_block,
            cycle_show_pool_share,
            cycle_show_total_value,
            cycle_show_price,
            cycle_show_peers,
        ]
    )
    toggled = False

    if stat_name in ("reward", "Estimated Reward"):
        if cycle_show_reward and active_count <= 1:
            logger.info(
                "Cannot disable Estimated Reward: at least one display stat must remain active."
            )
            return False
        cycle_show_reward = not cycle_show_reward
        logger.info(f"Toggled Estimated Reward: {cycle_show_reward}")
        toggled = True
    elif stat_name in ("difficulty", "Difficulty"):
        if cycle_show_difficulty and active_count <= 1:
            logger.info("Cannot disable Difficulty: at least one display stat must remain active.")
            return False
        cycle_show_difficulty = not cycle_show_difficulty
        logger.info(f"Toggled Difficulty: {cycle_show_difficulty}")
        toggled = True
    elif stat_name in ("rac", "Top Project RAC"):
        if cycle_show_rac and active_count <= 1:
            logger.info(
                "Cannot disable Top Project RAC: at least one display stat must remain active."
            )
            return False
        cycle_show_rac = not cycle_show_rac
        logger.info(f"Toggled Top Project RAC: {cycle_show_rac}")
        toggled = True
    elif stat_name in ("mag", "magnitude", "Total Magnitude", "Magnitude"):
        if cycle_show_mag and active_count <= 1:
            logger.info(
                "Cannot disable Total Magnitude: at least one display stat must remain active."
            )
            return False
        cycle_show_mag = not cycle_show_mag
        logger.info(f"Toggled Total Magnitude: {cycle_show_mag}")
        toggled = True
    elif stat_name in ("block", "Block Height", "Block Number"):
        if cycle_show_block and active_count <= 1:
            logger.info(
                "Cannot disable Block Height: at least one display stat must remain active."
            )
            return False
        cycle_show_block = not cycle_show_block
        logger.info(f"Toggled Block Height: {cycle_show_block}")
        toggled = True
    elif stat_name in ("pool_share", "share", "Pool Share"):
        if cycle_show_pool_share and active_count <= 1:
            logger.info("Cannot disable Pool Share: at least one display stat must remain active.")
            return False
        cycle_show_pool_share = not cycle_show_pool_share
        logger.info(f"Toggled Pool Share: {cycle_show_pool_share}")
        toggled = True
    elif stat_name in (
        "total_value",
        "value",
        "Total Value ($)",
        "Total Value (USD)",
        "Total Value",
    ):
        if cycle_show_total_value and active_count <= 1:
            logger.info("Cannot disable Total Value: at least one display stat must remain active.")
            return False
        cycle_show_total_value = not cycle_show_total_value
        logger.info(f"Toggled Total Value: {cycle_show_total_value}")
        toggled = True
    elif stat_name in ("price", "grc_price", "GRC Price ($)", "GRC Price (USD)", "GRC Price"):
        if cycle_show_price and active_count <= 1:
            logger.info("Cannot disable GRC Price: at least one display stat must remain active.")
            return False
        cycle_show_price = not cycle_show_price
        logger.info(f"Toggled GRC Price: {cycle_show_price}")
        toggled = True
    elif stat_name in ("peers", "connections", "Network Peers", "Peers"):
        if cycle_show_peers and active_count <= 1:
            logger.info(
                "Cannot disable Network Peers: at least one display stat must remain active."
            )
            return False
        cycle_show_peers = not cycle_show_peers
        logger.info(f"Toggled Network Peers: {cycle_show_peers}")
        toggled = True

    if toggled:
        save_settings()
        return True

    return False


def _get_menu_id_map(menu_options) -> dict:
    """Recursively map menu item titles to their Windows menu option IDs."""
    id_map = {}

    def _recurse(opts):
        for item in opts:
            if not isinstance(item, (list, tuple)) or len(item) < 4:
                continue
            text = item[0]
            action = item[2]
            opt_id = item[3]
            id_map[text] = opt_id
            if isinstance(action, (list, tuple)):
                _recurse(action)

    _recurse(menu_options)
    return id_map


def update_tray_menu_checks(systray) -> None:
    """Update checkmark states for all toggleable menu items in the tray."""
    if sys.platform != "win32":
        return
    menu = getattr(systray, "_menu", None)
    if not menu:
        return
    u32 = ctypes.windll.user32
    id_map = _get_menu_id_map(getattr(systray, "_menu_options", []))

    # 1. Start with Windows
    if "Start with Windows" in id_map:
        flag = 0x00000008 if is_autostart_enabled() else 0x00000000
        try:
            u32.CheckMenuItem(menu, id_map["Start with Windows"], flag)
        except Exception:
            pass

    # 2. Hide Balance
    if "Hide Balance" in id_map:
        flag = 0x00000008 if hide_balance else 0x00000000
        try:
            u32.CheckMenuItem(menu, id_map["Hide Balance"], flag)
        except Exception:
            pass

    # 3. Cycle Stats (Line 2) subitems
    stat_flags = {
        "Estimated Reward": cycle_show_reward,
        "Difficulty": cycle_show_difficulty,
        "Top Project RAC": cycle_show_rac,
        "Total Magnitude": cycle_show_mag,
        "Block Height": cycle_show_block,
        "Pool Share": cycle_show_pool_share,
        "Total Value ($)": cycle_show_total_value,
        "GRC Price ($)": cycle_show_price,
        "Network Peers": cycle_show_peers,
    }
    for name, is_active in stat_flags.items():
        if name in id_map:
            flag = 0x00000008 if is_active else 0x00000000
            try:
                u32.CheckMenuItem(menu, id_map[name], flag)
            except Exception:
                pass


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


def _is_stake_tx(tx: Any) -> bool:
    return (
        isinstance(tx, dict)
        and tx.get("category") in ("generate", "immature", "stake")
        and tx.get("confirmations", 0) >= 0
    )


def get_newest_txid(grc: GridcoinRPC) -> Optional[str]:
    """Return the txid of the newest listtransactions entry, used as a scan marker."""
    try:
        txs = grc.call("listtransactions", ["*", 1])
        if isinstance(txs, list) and txs and isinstance(txs[-1], dict):
            txid = txs[-1].get("txid")
            return str(txid) if txid else None
    except Exception as err:
        logger.warning(f"Failed to fetch newest transaction: {err}")
    return None


def scan_new_stakes(
    grc: GridcoinRPC,
    marker_txid: Optional[str],
    page_size: int = 50,
    max_entries: int = 10000,
) -> Tuple[Optional[int], Optional[str]]:
    """Page back through listtransactions (newest first) until marker_txid is seen.

    Returns (timestamp of the newest stake among the entries newer than the
    marker, or None; txid of the newest entry seen, or None). Cost is one page
    when nothing new has happened, and proportional to the number of new
    entries otherwise, so no window of entries is ever skipped.
    """
    best_ts: Optional[int] = None
    new_marker: Optional[str] = None
    skip = 0
    while skip < max_entries:
        try:
            txs = grc.call("listtransactions", ["*", page_size, skip])
        except Exception as err:
            logger.warning(f"Failed to scan for new stakes: {err}")
            break
        if not isinstance(txs, list) or not txs:
            break
        for tx in reversed(txs):  # listtransactions is oldest-first; walk newest-first
            if not isinstance(tx, dict):
                continue
            txid = tx.get("txid")
            if new_marker is None and txid:
                new_marker = str(txid)
            if marker_txid is not None and txid == marker_txid:
                return best_ts, new_marker
            if _is_stake_tx(tx):
                ts = tx.get("blocktime") or tx.get("time")
                if ts is not None and (best_ts is None or int(ts) > best_ts):
                    best_ts = int(ts)
        if len(txs) < page_size:
            break
        skip += page_size
    else:
        logger.warning(
            f"Stake scan hit the {max_entries}-entry cap without finding marker {marker_txid}"
        )
    return best_ts, new_marker


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
        except Exception as err:
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
        except Exception as err:
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
    global running, presence_enabled, hide_balance
    global cycle_show_reward, cycle_show_difficulty, cycle_show_rac
    global cycle_show_mag, cycle_show_block, cycle_show_pool_share
    global cycle_show_total_value, cycle_show_price, cycle_show_peers

    last_stake_time: Optional[int] = None
    last_tx_check = 0.0
    last_rac_check = 0.0
    stake_marker: Optional[str] = None
    top_project_rac: Optional[str] = None
    total_mag: Optional[float] = None
    initial_scan_done = False
    cycle_count = 0

    while running:
        if not presence_enabled:
            for _ in range(10):
                if not running or presence_enabled or update_event.is_set():
                    break
                time.sleep(0.1)
            update_event.clear()
            continue

        try:
            # 1. Fetch mining information
            mining_info = grc.call("getmininginfo")
            active_coins = get_active_staking_coins(mining_info)
            expected_reward = get_expected_reward(mining_info)
            difficulty = get_difficulty(mining_info)
            net_weight = get_network_stake_weight(mining_info)
            block_height = get_block_height(mining_info)

            # Check if wallet is actively staking (e.g. unlocked for staking)
            is_staking = is_wallet_staking(mining_info)
            staking_info = None
            if is_staking is None or net_weight <= 0:
                try:
                    staking_info = grc.call("getstakinginfo")
                    if is_staking is None:
                        is_staking = is_wallet_staking(staking_info)
                    if net_weight <= 0 and isinstance(staking_info, dict):
                        net_weight = get_network_stake_weight(staking_info)
                except Exception:
                    pass

            pool_share_str = format_pool_share(active_coins, net_weight)

            # Check blockchain sync status
            is_syncing = False
            sync_progress = 1.0
            try:
                blockchain_info = grc.call("getblockchaininfo")
                is_syncing, sync_progress = get_blockchain_sync_status(blockchain_info)
                if block_height is None and isinstance(blockchain_info, dict):
                    block_height = get_block_height(blockchain_info)
            except Exception as err:
                logger.debug(f"Failed to fetch getblockchaininfo: {err}")

            if is_syncing:
                details_str = format_sync_details(sync_progress, block_height)
            else:
                details_str = format_details(
                    active_coins, is_staking=is_staking, hide_balance=hide_balance
                )

            # Check for top BOINC project RAC and total magnitude periodically
            current_time = time.time()
            if current_time - last_rac_check > 60 or top_project_rac is None:
                try:
                    explain_data = grc.call("explainmagnitude")
                    top_project_rac = get_top_project_rac(explain_data)
                    total_mag = get_total_magnitude(explain_data, mining_info)
                except Exception as err:
                    logger.debug(f"Failed to fetch explainmagnitude: {err}")
                last_rac_check = current_time

            if total_mag is None:
                total_mag = get_total_magnitude(None, mining_info)

            total_value_str = None
            price_str = None
            if cycle_show_total_value or cycle_show_price:
                price_usd = get_grc_usd_price()
                if cycle_show_price:
                    price_str = format_grc_price(price_usd)
                if cycle_show_total_value:
                    total_balance = get_total_balance(grc, active_coins)
                    total_value_str = format_total_value_usd(total_balance, price_usd)

            peers_str = None
            if cycle_show_peers:
                peer_count = get_peer_count(grc)
                peers_str = format_peers(peer_count)

            # 2. Alternating State (cycles between all active metrics)
            state_str = get_alternating_state(
                cycle_count,
                SWITCH_CYCLES,
                expected_reward,
                difficulty,
                project_rac=top_project_rac,
                total_mag=total_mag,
                block_height=block_height,
                pool_share_str=pool_share_str,
                total_value_str=total_value_str,
                price_str=price_str,
                peers_str=peers_str,
                show_reward=cycle_show_reward,
                show_difficulty=cycle_show_difficulty,
                show_rac=cycle_show_rac,
                show_mag=cycle_show_mag,
                show_block=cycle_show_block,
                show_pool_share=cycle_show_pool_share,
                show_total_value=cycle_show_total_value,
                show_price=cycle_show_price,
                show_peers=cycle_show_peers,
            )
            cycle_count += 1

            # 3. Check for stake timestamp: 100/500 initial scan, then every 60 s
            #    read only the entries newer than the last seen txid.
            current_time = time.time()
            if not initial_scan_done:
                # get_last_stake_timestamp already widens 100 -> 500 itself.
                fetched_time = get_last_stake_timestamp(grc, count=100)
                if fetched_time:
                    last_stake_time = fetched_time
                stake_marker = get_newest_txid(grc)
                initial_scan_done = True
                last_tx_check = current_time
            elif current_time - last_tx_check > 60:
                fetched_time, new_marker = scan_new_stakes(grc, stake_marker)
                if fetched_time and (last_stake_time is None or fetched_time > last_stake_time):
                    last_stake_time = fetched_time
                if new_marker:
                    stake_marker = new_marker
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

                assets = get_presence_assets(
                    is_offline=False,
                    is_staking=is_staking,
                    is_syncing=is_syncing,
                    sync_progress=sync_progress,
                )
                if assets:
                    update_payload.update(assets)

                discord.update(**update_payload)
                logger.info(
                    f"Presence updated: [{details_str}] | [{state_str}] | "
                    f"Last Stake: {last_stake_time}"
                )

        except PermissionError as auth_err:
            if presence_enabled:
                logger.error(
                    f"RPC authentication failed: {auth_err}. Please verify rpc_user and rpc_password."
                )
                offline_payload = {
                    "details": "RPC Auth Failed",
                    "state": "Check Credentials",
                }
                buttons = get_presence_buttons()
                if buttons:
                    offline_payload["buttons"] = buttons
                assets = get_presence_assets(is_offline=True)
                if assets:
                    offline_payload.update(assets)
                discord.update(**offline_payload)
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
                assets = get_presence_assets(is_offline=True)
                if assets:
                    offline_payload.update(assets)
                discord.update(**offline_payload)
        except Exception as err:
            logger.error(f"Unexpected error in polling loop: {err}", exc_info=True)
            time.sleep(5)

        # Responsive sleep loop
        for _ in range(POLL_INTERVAL * 10):
            if not running or not presence_enabled or update_event.is_set():
                break
            time.sleep(0.1)
        update_event.clear()


def main(argv: Optional[list] = None):
    global discord_mgr, presence_enabled, running
    args = parse_args(argv)

    if not acquire_single_instance_lock():
        logger.warning("Another instance of Gridcoin-RPC is already running. Exiting.")
        sys.exit(0)

    def handle_shutdown_signal(signum, frame):
        global running
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info(f"Received signal {sig_name}, shutting down...")
        running = False
        trigger_presence_update()

    try:
        signal.signal(signal.SIGINT, handle_shutdown_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handle_shutdown_signal)
    except (ValueError, OSError) as e:
        logger.debug(f"Could not register signal handlers: {e}")

    mode_str = " (headless)" if args.headless else ""
    logger.info(f"Starting Gridcoin Discord Rich Presence daemon{mode_str}...")
    apply_rpc_config(args)
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
        save_settings()
        state_msg = "enabled" if presence_enabled else "paused"
        logger.info(f"Presence {state_msg} via system tray.")
        if not presence_enabled and discord_mgr:
            discord_mgr.clear()
        trigger_presence_update()

    def on_tray_toggle_hide_balance(systray):
        global hide_balance
        hide_balance = not hide_balance
        save_settings()
        logger.info(f"Toggled Hide Balance: {hide_balance}")
        trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_reward(systray):
        if toggle_stat("reward"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_difficulty(systray):
        if toggle_stat("difficulty"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_rac(systray):
        if toggle_stat("rac"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_mag(systray):
        if toggle_stat("magnitude"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_block(systray):
        if toggle_stat("block"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_pool_share(systray):
        if toggle_stat("pool_share"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_total_value(systray):
        if toggle_stat("total_value"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_price(systray):
        if toggle_stat("price"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_toggle_peers(systray):
        if toggle_stat("peers"):
            trigger_presence_update()
        update_tray_menu_checks(systray)

    def on_tray_autostart(systray):
        new_state = not is_autostart_enabled()
        if set_autostart(new_state):
            update_tray_menu_checks(systray)

    def on_tray_github(systray):
        if GITHUB_REPO_URL:
            webbrowser.open(GITHUB_REPO_URL)

    def on_tray_website(systray):
        if GRIDCOIN_WEBSITE_URL:
            webbrowser.open(GRIDCOIN_WEBSITE_URL)

    def on_tray_quit(systray):
        global running, discord_mgr
        logger.info("Exiting application via system tray.")
        running = False
        trigger_presence_update()
        if discord_mgr:
            discord_mgr.close()

    tray = None
    if not args.headless and sys.platform == "win32":
        icon_path = get_icon_file_path()
        if icon_path:
            cycle_suboptions = (
                ("Estimated Reward", None, on_toggle_reward),
                ("Difficulty", None, on_toggle_difficulty),
                ("Top Project RAC", None, on_toggle_rac),
                ("Total Magnitude", None, on_toggle_mag),
                ("Block Height", None, on_toggle_block),
                ("Pool Share", None, on_toggle_pool_share),
                ("Total Value ($)", None, on_toggle_total_value),
                ("GRC Price ($)", None, on_toggle_price),
                ("Network Peers", None, on_toggle_peers),
            )
            menu_options = (
                ("Turn Off / On Presence", None, on_tray_toggle),
                ("Hide Balance", None, on_tray_toggle_hide_balance),
                ("Cycle Stats (Line 2)", None, cycle_suboptions),
                ("Start with Windows", None, on_tray_autostart),
                ("What is Gridcoin? (Website)", None, on_tray_website),
                ("GitHub Repository", None, on_tray_github),
            )
            try:
                tray = SysTrayIcon(
                    icon_path, "Gridcoin Discord RPC", menu_options, on_quit=on_tray_quit
                )

                original_create_menu = tray._create_menu

                def patched_create_menu(menu, menu_opts):
                    original_create_menu(menu, menu_opts)
                    if menu == tray._menu:
                        update_tray_menu_checks(tray)

                tray._create_menu = patched_create_menu

                original_show_menu = tray._show_menu

                def patched_show_menu():
                    if tray._menu is None:
                        from infi.systray.win32_adapter import CreatePopupMenu

                        tray._menu = CreatePopupMenu()
                        tray._create_menu(tray._menu, tray._menu_options)
                    update_tray_menu_checks(tray)
                    original_show_menu()

                tray._show_menu = patched_show_menu

                tray.start()
            except Exception as err:
                logger.warning(f"Could not start system tray: {err}")

    try:
        while running:
            time.sleep(1)
    finally:
        if discord_mgr:
            discord_mgr.close()
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
