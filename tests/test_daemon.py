"""Unit test suite for Gridcoin Discord RPC daemon."""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (
    DiscordPresenceManager,
    _get_menu_id_map,
    apply_rpc_config,
    format_block_height,
    format_details,
    format_difficulty,
    format_grc_price,
    format_magnitude,
    format_peers,
    format_pool_share,
    format_reward,
    format_sync_details,
    format_total_value_usd,
    get_active_staking_coins,
    get_alternating_state,
    get_block_height,
    get_blockchain_sync_status,
    get_difficulty,
    get_executable_path,
    get_expected_reward,
    get_grc_usd_price,
    get_last_stake_timestamp,
    get_network_stake_weight,
    get_newest_txid,
    get_peer_count,
    get_presence_assets,
    get_presence_buttons,
    get_top_project_rac,
    get_total_balance,
    get_total_magnitude,
    is_autostart_enabled,
    is_wallet_staking,
    load_settings,
    parse_args,
    save_settings,
    scan_new_stakes,
    set_autostart,
    toggle_stat,
    trigger_presence_update,
    update_tray_menu_checks,
)
from rpc_client import GridcoinRPC


class TestGridcoinDaemon(unittest.TestCase):
    def test_active_staking_coins_parsing(self):
        # 1. stakeweight dict with valuesum
        info1 = {"stakeweight": {"valuesum": 12450.50, "value": 10000.0, "legacy": 5000.0}}
        self.assertAlmostEqual(get_active_staking_coins(info1), 12450.50)

        # 2. stakeweight dict with fallback to value
        info2 = {"stakeweight": {"valuesum": None, "value": 8500.25}}
        self.assertAlmostEqual(get_active_staking_coins(info2), 8500.25)

        # 3. stakeweight dict with fallback to legacy
        info3 = {"stakeweight": {"legacy": 3200.75}}
        self.assertAlmostEqual(get_active_staking_coins(info3), 3200.75)

        # 4. direct numeric stakeweight
        info4 = {"stakeweight": 450.12}
        self.assertAlmostEqual(get_active_staking_coins(info4), 450.12)
        info4_int = {"stakeweight": 500}
        self.assertAlmostEqual(get_active_staking_coins(info4_int), 500.0)

        # 5. Missing / zero / invalid
        self.assertEqual(get_active_staking_coins({}), 0.0)
        self.assertEqual(get_active_staking_coins({"stakeweight": 0}), 0.0)
        self.assertEqual(get_active_staking_coins({"stakeweight": {}}), 0.0)
        self.assertEqual(get_active_staking_coins(None), 0.0)

    def test_details_formatting(self):
        self.assertEqual(format_details(12450.50), "Staking: 12,450.50 GRC")
        self.assertEqual(format_details(1000000.00), "Staking: 1,000,000.00 GRC")
        self.assertEqual(format_details(0.0), "Staking: 0.00 GRC")
        self.assertEqual(format_details(-10.0), "Staking: 0.00 GRC")

    def test_expected_reward(self):
        # 1. With pending BOINC reward (matches wallet GUI)
        self.assertAlmostEqual(get_expected_reward({"BoincRewardPending": 1289.53}), 1289.53)
        self.assertEqual(format_reward(1289.53), "Est. Reward: 1,289.53 GRC")

        # 2. Investor mode (no pending BOINC reward -> returns 0.0, formats as 'Searching for Blocks')
        self.assertEqual(get_expected_reward({"BoincRewardPending": 0.0}), 0.0)
        self.assertEqual(get_expected_reward({}), 0.0)
        self.assertEqual(get_expected_reward(None), 0.0)
        self.assertEqual(format_reward(0.0), "Searching for Blocks")
        self.assertEqual(format_reward(None), "Searching for Blocks")
        self.assertEqual(format_reward(-5.0), "Searching for Blocks")

    def test_magnitude_formatting(self):
        self.assertEqual(format_magnitude(142.5), "Magnitude: 142.50")
        self.assertEqual(format_magnitude(100), "Magnitude: 100")
        self.assertEqual(format_magnitude(0), "Magnitude: None")
        self.assertEqual(format_magnitude(0.0), "Magnitude: None")
        self.assertEqual(format_magnitude("0"), "Magnitude: None")
        self.assertEqual(format_magnitude(-5), "Magnitude: None")
        self.assertEqual(format_magnitude(None), "Magnitude: None")

    def test_difficulty_extraction(self):
        # 1. Direct float difficulty
        self.assertAlmostEqual(get_difficulty({"difficulty": 12.345}), 12.345)
        # 2. String difficulty
        self.assertAlmostEqual(get_difficulty({"difficulty": "8.5"}), 8.5)
        # 3. Dict difficulty with proof-of-stake
        self.assertAlmostEqual(get_difficulty({"difficulty": {"proof-of-stake": 6.78}}), 6.78)
        # 4. Dict difficulty with current
        self.assertAlmostEqual(get_difficulty({"difficulty": {"current": 4.32}}), 4.32)
        # 5. Dict fallback to values
        self.assertAlmostEqual(get_difficulty({"difficulty": {"other": 1.23}}), 1.23)
        # 6. Missing or invalid
        self.assertEqual(get_difficulty({}), 0.0)
        self.assertEqual(get_difficulty(None), 0.0)
        self.assertEqual(get_difficulty({"difficulty": "invalid"}), 0.0)

    def test_difficulty_formatting(self):
        self.assertEqual(format_difficulty(12.345), "Difficulty: 12.35")
        self.assertEqual(format_difficulty(1234.56), "Difficulty: 1,234.56")
        self.assertEqual(format_difficulty(0.005), "Difficulty: 0.0050")
        self.assertEqual(format_difficulty(0), "Difficulty: 0.00")
        self.assertEqual(format_difficulty(-1.0), "Difficulty: 0.00")

    def test_get_alternating_state(self):
        reward = 25.50
        diff = 12.34
        # For switch_cycles = 2:
        # cycle 0 -> Est. Reward
        # cycle 1 -> Est. Reward
        # cycle 2 -> Difficulty
        # cycle 3 -> Difficulty
        # cycle 4 -> Est. Reward
        self.assertEqual(get_alternating_state(0, 2, reward, diff), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(1, 2, reward, diff), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(2, 2, reward, diff), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(3, 2, reward, diff), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(4, 2, reward, diff), "Est. Reward: 25.50 GRC")

        # For switch_cycles = 1 (every cycle):
        self.assertEqual(get_alternating_state(0, 1, reward, diff), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(1, 1, reward, diff), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(2, 1, reward, diff), "Est. Reward: 25.50 GRC")

    def test_get_top_project_rac(self):
        # 1. Multiple projects with total row
        data = [
            {"project": "SRBase", "rac": 0.091792, "magnitude": 0},
            {"project": "asteroids@home", "rac": 1.719628, "magnitude": 0.01},
            {"project": "odlk1", "rac": 38426.01582, "magnitude": 183.7},
            {"project": "total", "rac": 38428.112389, "magnitude": 183.71},
        ]
        self.assertEqual(get_top_project_rac(data), "odlk1 RAC: 38,426")

        # 2. String rac values
        data_str = [{"project": "worldcommunitygrid", "rac": "12500.4"}]
        self.assertEqual(get_top_project_rac(data_str), "worldcommunitygrid RAC: 12,500")

        # 3. Only total row or all 0 -> returns None
        self.assertIsNone(get_top_project_rac([{"project": "total", "rac": 5000}]))
        self.assertIsNone(get_top_project_rac([{"project": "test", "rac": 0}]))
        self.assertIsNone(get_top_project_rac([]))
        self.assertIsNone(get_top_project_rac(None))
        self.assertIsNone(get_top_project_rac("invalid"))

    def test_get_alternating_state_with_project_rac(self):
        reward = 25.50
        diff = 12.34
        rac_str = "odlk1 RAC: 38,426"

        # 3-way rotation for switch_cycles = 1:
        # cycle 0 -> Reward
        # cycle 1 -> Difficulty
        # cycle 2 -> Project RAC
        # cycle 3 -> Reward
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, rac_str), "Est. Reward: 25.50 GRC"
        )
        self.assertEqual(get_alternating_state(1, 1, reward, diff, rac_str), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(2, 1, reward, diff, rac_str), "odlk1 RAC: 38,426")
        self.assertEqual(
            get_alternating_state(3, 1, reward, diff, rac_str), "Est. Reward: 25.50 GRC"
        )

        # 3-way rotation for switch_cycles = 2:
        self.assertEqual(
            get_alternating_state(0, 2, reward, diff, rac_str), "Est. Reward: 25.50 GRC"
        )
        self.assertEqual(
            get_alternating_state(1, 2, reward, diff, rac_str), "Est. Reward: 25.50 GRC"
        )
        self.assertEqual(get_alternating_state(2, 2, reward, diff, rac_str), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(3, 2, reward, diff, rac_str), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(4, 2, reward, diff, rac_str), "odlk1 RAC: 38,426")
        self.assertEqual(get_alternating_state(5, 2, reward, diff, rac_str), "odlk1 RAC: 38,426")
        self.assertEqual(
            get_alternating_state(6, 2, reward, diff, rac_str), "Est. Reward: 25.50 GRC"
        )

        # When project_rac is None, fallback to 2-way:
        self.assertEqual(get_alternating_state(0, 2, reward, diff, None), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(2, 2, reward, diff, None), "Difficulty: 12.34")

    def test_get_presence_buttons(self):
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "main.GITHUB_REPO_URL",
                    "https://github.com/nikolaevichsmor/Gridcoin-RPC",
                )
            )
            stack.enter_context(patch("main.GITHUB_BUTTON_LABEL", "GitHub"))
            stack.enter_context(patch("main.GRIDCOIN_WEBSITE_URL", "https://gridcoin.us/"))
            stack.enter_context(patch("main.GRIDCOIN_WEBSITE_LABEL", "What is this?"))
            buttons = get_presence_buttons()
            self.assertEqual(
                buttons,
                [
                    {
                        "label": "GitHub",
                        "url": "https://github.com/nikolaevichsmor/Gridcoin-RPC",
                    },
                    {"label": "What is this?", "url": "https://gridcoin.us/"},
                ],
            )

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "main.GITHUB_REPO_URL",
                    "https://github.com/nikolaevichsmor/Gridcoin-RPC",
                )
            )
            stack.enter_context(patch("main.GRIDCOIN_WEBSITE_URL", ""))
            buttons = get_presence_buttons()
            self.assertEqual(
                buttons,
                [
                    {
                        "label": "GitHub",
                        "url": "https://github.com/nikolaevichsmor/Gridcoin-RPC",
                    }
                ],
            )

        with patch("main.GITHUB_REPO_URL", ""), patch("main.GRIDCOIN_WEBSITE_URL", ""):
            buttons = get_presence_buttons()
            self.assertIsNone(buttons)

    def test_get_last_stake_timestamp(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.return_value = [
            {
                "category": "receive",
                "amount": 100,
                "time": 1700000000,
                "blocktime": 1700000000,
            },
            {
                "category": "stake",
                "amount": 10,
                "time": 1700000500,
                "blocktime": 1700000500,
            },
            {
                "category": "immature",
                "amount": 10,
                "time": 1700000800,
                "blocktime": 1700000800,
            },
            {
                "category": "generate",
                "amount": 10,
                "time": 1700001000,
                "blocktime": 1700001000,
            },
            {
                "category": "send",
                "amount": -50,
                "time": 1700002000,
                "blocktime": 1700002000,
            },
        ]

        ts = get_last_stake_timestamp(mock_grc)
        # Should pick the highest timestamp among stake, immature, generate (1700001000), ignoring send (1700002000)
        self.assertEqual(ts, 1700001000)

    def test_get_last_stake_timestamp_fallback_to_time(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.return_value = [
            {"category": "stake", "amount": 10, "time": 1700000600},
        ]
        ts = get_last_stake_timestamp(mock_grc)
        self.assertEqual(ts, 1700000600)

    def test_get_last_stake_timestamp_ignores_orphaned_blocks(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.return_value = [
            {
                "category": "generate",
                "amount": 10,
                "time": 1700000500,
                "confirmations": 10,
            },
            {
                "category": "generate",
                "amount": 10,
                "time": 1700001000,
                "confirmations": -1,
            },
        ]
        ts = get_last_stake_timestamp(mock_grc)
        self.assertEqual(ts, 1700000500)

    def test_get_last_stake_timestamp_empty(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.return_value = []
        self.assertIsNone(get_last_stake_timestamp(mock_grc))

    def test_get_last_stake_timestamp_fallback_500(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.side_effect = [
            [{"category": "receive", "amount": 10, "time": 1700000100}],
            [
                {
                    "category": "stake",
                    "amount": 10,
                    "time": 1700000999,
                    "confirmations": 5,
                }
            ],
        ]
        ts = get_last_stake_timestamp(mock_grc, count=100)
        self.assertEqual(ts, 1700000999)
        self.assertEqual(mock_grc.call.call_count, 2)

    def test_auto_detect_rpc_credentials_with_comments(self):
        conf_content = """
        # Global settings
        ; Semicolon comment
        rpcuser = test_user # inline comment
        rpcpassword = test_pass ; inline semicolon comment
        rpcport = 15716 # custom port
        """
        import tempfile

        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            f.write(conf_content)
            temp_path = Path(f.name)

        try:
            with patch("main.find_gridcoin_conf", return_value=temp_path):
                with patch("main.RPC_USER", ""):
                    with patch("main.RPC_PASS", ""):
                        with patch("main.RPC_PORT", 15715):
                            import main
                            from main import auto_detect_rpc_credentials

                            auto_detect_rpc_credentials()
                            self.assertEqual(main.RPC_USER, "test_user")
                            self.assertEqual(main.RPC_PASS, "test_pass")
                            self.assertEqual(main.RPC_PORT, 15716)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_polling_worker_initial_scan_queries_500_once(self):
        # On a wallet with no stake, the first iteration must issue the
        # 100-then-500 scan exactly once (no second fallback in the worker),
        # then a single-entry query to seed the scan marker.
        import main

        def rpc_call(method, params=None):
            if method == "getmininginfo":
                return {}
            if method == "explainmagnitude":
                return []
            if method == "listtransactions":
                return []
            raise AssertionError(f"unexpected RPC {method}")

        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.side_effect = rpc_call

        mock_discord = MagicMock(spec=DiscordPresenceManager)

        def stop_after_update(**kwargs):
            main.running = False
            return True

        mock_discord.update.side_effect = stop_after_update

        with patch("main.running", True), patch("main.presence_enabled", True):
            main.polling_worker(mock_grc, mock_discord)

        lt_params = [
            c.args[1] for c in mock_grc.call.call_args_list if c.args[0] == "listtransactions"
        ]
        # Third call seeds the marker for the incremental periodic scan.
        self.assertEqual(lt_params, [["*", 100], ["*", 500], ["*", 1]])
        mock_discord.update.assert_called_once()

    @staticmethod
    def _listtransactions_like(all_txs):
        """Mimic listtransactions "*" count [from]: oldest-first slice, `from` skips newest."""

        def _impl(params):
            count = params[1]
            skip = params[2] if len(params) > 2 else 0
            end = max(len(all_txs) - skip, 0)
            start = max(end - count, 0)
            return all_txs[start:end]

        return _impl

    def _run_worker_two_iterations(self, first_wallet, second_wallet):
        """Run polling_worker for an initial scan plus one periodic check.

        Returns (list of `start` values passed to Discord, listtransactions
        params issued during the periodic check).
        """
        import main

        wallet = {"txs": first_wallet}
        lt_params = []
        phase = {"periodic": False}

        def rpc_call(method, params=None):
            if method == "getmininginfo":
                return {}
            if method == "explainmagnitude":
                return []
            if method == "listtransactions":
                if phase["periodic"]:
                    lt_params.append(list(params))
                return self._listtransactions_like(wallet["txs"])(params)
            raise AssertionError(f"unexpected RPC {method}")

        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.side_effect = rpc_call

        clock = {"now": 0.0}
        starts = []
        mock_discord = MagicMock(spec=DiscordPresenceManager)

        def on_update(**kwargs):
            starts.append(kwargs.get("start"))
            if len(starts) == 1:
                wallet["txs"] = second_wallet
                phase["periodic"] = True
                clock["now"] += 61  # next iteration crosses the 60 s periodic threshold
            else:
                main.running = False
            return True

        mock_discord.update.side_effect = on_update

        with ExitStack() as stack:
            stack.enter_context(patch("main.running", True))
            stack.enter_context(patch("main.presence_enabled", True))
            stack.enter_context(patch("main.time.time", side_effect=lambda: clock["now"]))
            stack.enter_context(patch("main.time.sleep"))
            main.polling_worker(mock_grc, mock_discord)

        return starts, lt_params

    def test_polling_worker_periodic_check_is_incremental(self):
        # Steady state: a dozen non-stake entries arrived since the initial
        # scan, pushing the last stake out of the 10 newest. The periodic check
        # must read one page and stop at the marker, not fall back to a
        # 500-entry query.
        old_stake = {
            "category": "generate",
            "txid": "A",
            "time": 1000,
            "confirmations": 50,
        }
        newer = [
            {
                "category": "receive",
                "txid": f"n{i}",
                "time": 1100 + i,
                "confirmations": 1,
            }
            for i in range(12)
        ]
        starts, lt_params = self._run_worker_two_iterations([old_stake], [old_stake] + newer)
        self.assertEqual(starts, [1000, 1000])
        self.assertEqual(lt_params, [["*", 50, 0]])

    def test_polling_worker_periodic_check_finds_stake_beyond_500_entries(self):
        # A flood of entries (more than the 500-entry fallback window) lands
        # between two checks. The new stake behind them must still be found.
        old_stake = {
            "category": "generate",
            "txid": "A",
            "time": 1000,
            "confirmations": 50,
        }
        new_stake = {
            "category": "generate",
            "txid": "S",
            "time": 2000,
            "confirmations": 3,
        }
        flood = [
            {
                "category": "receive",
                "txid": f"n{i}",
                "time": 2100 + i,
                "confirmations": 1,
            }
            for i in range(510)
        ]
        starts, lt_params = self._run_worker_two_iterations(
            [old_stake], [old_stake, new_stake] + flood
        )
        self.assertEqual(starts, [1000, 2000])
        # Paged back 50 at a time until the marker was reached.
        self.assertEqual(lt_params[0], ["*", 50, 0])
        self.assertEqual(lt_params[-1], ["*", 50, 500])
        self.assertEqual(len(lt_params), 11)

    def test_scan_new_stakes_stops_at_marker(self):
        txs = [
            {"category": "generate", "txid": "old", "time": 100, "confirmations": 9},
            {"category": "receive", "txid": "M", "time": 200, "confirmations": 5},
            {"category": "immature", "txid": "S", "time": 300, "confirmations": 2},
            {"category": "send", "txid": "N", "time": 400, "confirmations": 1},
        ]
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.side_effect = lambda m, p=None: self._listtransactions_like(txs)(p)
        ts, marker = scan_new_stakes(mock_grc, "M", page_size=2)
        # Stake "old" is behind the marker and must be ignored; the marker is
        # on the second 2-entry page, so exactly two pages are read.
        self.assertEqual((ts, marker), (300, "N"))
        self.assertEqual(mock_grc.call.call_count, 2)

    def test_scan_new_stakes_ignores_orphans_and_handles_no_marker(self):
        txs = [
            {"category": "generate", "txid": "S", "time": 300, "confirmations": 2},
            {"category": "generate", "txid": "O", "time": 400, "confirmations": -1},
        ]
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.side_effect = lambda m, p=None: self._listtransactions_like(txs)(p)
        self.assertEqual(scan_new_stakes(mock_grc, None), (300, "O"))
        self.assertEqual(scan_new_stakes(mock_grc, "zzz"), (300, "O"))

    def test_scan_new_stakes_rpc_error(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.side_effect = ConnectionError("Node unreachable")
        self.assertEqual(scan_new_stakes(mock_grc, "M"), (None, None))

    def test_scan_new_stakes_retries_unread_pages_after_failure(self):
        txs = [
            {"txid": "old", "category": "receive"},
            {"txid": "stake", "category": "generate", "time": 200, "confirmations": 1},
            {"txid": "new", "category": "receive"},
        ]
        for failure in (ConnectionError("page 2 failed"), {"invalid": "response"}):
            with self.subTest(failure=failure):
                grc = MagicMock(spec=GridcoinRPC)
                grc.call.side_effect = [[txs[-1]], failure]
                timestamp, marker = scan_new_stakes(grc, "old", page_size=1)
                self.assertIsNone(timestamp)
                self.assertIsNone(marker)
                grc.call.side_effect = lambda m, p: self._listtransactions_like(txs)(p)
                self.assertEqual(
                    scan_new_stakes(grc, marker or "old", page_size=1), (200, "new")
                )

    def test_scan_new_stakes_does_not_advance_marker_at_cap(self):
        grc = MagicMock(spec=GridcoinRPC)
        grc.call.return_value = [
            {"txid": "new", "category": "generate", "time": 200, "confirmations": 1}
        ]
        self.assertEqual(scan_new_stakes(grc, "old", page_size=1, max_entries=1), (200, None))

    def test_worker_owns_discord_during_pause_resume_and_shutdown(self):
        import main

        updating = threading.Event()
        release_update = threading.Event()
        paused = threading.Event()
        resumed = threading.Event()
        release_shutdown = threading.Event()
        calls = []

        def record(name):
            calls.append((name, threading.get_ident()))

        instance = MagicMock()
        instance.connect.side_effect = lambda: record("connect")
        instance.clear.side_effect = lambda: record("clear")

        def close():
            record("close")
            paused.set()

        def update(**kwargs):
            record("update")
            if not updating.is_set():
                updating.set()
                if not release_update.wait(5):
                    raise RuntimeError("test timed out waiting to pause")
            else:
                resumed.set()
                if not release_shutdown.wait(5):
                    raise RuntimeError("test timed out waiting to stop")

        instance.close.side_effect = close
        instance.update.side_effect = update

        def create_presence(client_id):
            record("create")
            return instance

        grc = MagicMock(spec=GridcoinRPC)
        grc.call.side_effect = lambda method, params=None: [] if method == "listtransactions" else {}
        manager = DiscordPresenceManager("test")
        with ExitStack() as stack:
            stack.enter_context(patch("main.Presence", side_effect=create_presence))
            stack.enter_context(patch("main.running", True))
            stack.enter_context(patch("main.presence_enabled", True))
            stack.enter_context(patch("main.cycle_show_total_value", False))
            stack.enter_context(patch("main.cycle_show_price", False))
            stack.enter_context(patch("main.update_event", threading.Event()))
            worker = threading.Thread(target=main.polling_worker, args=(grc, manager))
            worker.start()
            try:
                self.assertTrue(updating.wait(5))
                main.presence_enabled = False
                main.trigger_presence_update()
                release_update.set()
                self.assertTrue(paused.wait(5))
                main.presence_enabled = True
                main.trigger_presence_update()
                self.assertTrue(resumed.wait(5))
            finally:
                main.running = False
                main.trigger_presence_update()
                release_update.set()
                release_shutdown.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual({ident for _, ident in calls}, {worker.ident})
        self.assertEqual(
            [name for name, _ in calls],
            ["create", "connect", "update", "clear", "close"] * 2,
        )

    def test_worker_closes_discord_on_unexpected_exit(self):
        import main

        discord = MagicMock(spec=DiscordPresenceManager)
        with patch("main._polling_loop", side_effect=RuntimeError("unexpected exit")):
            with self.assertRaises(RuntimeError):
                main.polling_worker(MagicMock(), discord)
        discord.close.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "Windows process selection")
    def test_stop_script_targets_only_this_project(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        self.assertIsNotNone(shell)
        with tempfile.TemporaryDirectory(prefix="grc review [test] ") as tmpdir:
            # Use one canonical spelling in fixtures and the PowerShell script path.
            # Hosted Windows runners can supply TEMP using an 8.3 user-directory alias.
            root = Path(tmpdir).resolve()
            scripts = root / "scripts"
            scripts.mkdir()
            script = scripts / "stop_background.ps1"
            shutil.copyfile(PROJECT_ROOT / "scripts" / script.name, script)
            main_path = str(root / "main.py")
            binary = str(root / "Gridcoin-RPC.exe")
            processes = [
                (1, "pythonw.exe", f'pythonw.exe "{main_path}"', None),
                (2, "python.exe", 'python.exe "C:\\other\\main.py"', None),
                (3, "powershell.exe", f'powershell -Command "{main_path}"', None),
                (4, "Gridcoin-RPC.exe", None, binary),
                (5, "Gridcoin-RPC.exe", None, "C:\\other\\Gridcoin-RPC.exe"),
                (6, "python.exe", f'python.exe "{main_path}.bak"', None),
                (7, "python.exe", f'python.exe other.py "{main_path}"', None),
                (8, "python.exe", 'python.exe main.py', None),
                (9, "pythonw.exe", f'"C:\\Python Dir\\pythonw.exe" "{scripts / "main.pyw"}"', None),
                (10, "python.exe", f'python.exe "{main_path}" --headless', None),
            ]
            fixtures = root / "processes.json"
            fixtures.write_text(json.dumps([
                dict(ProcessId=pid, Name=name, CommandLine=cmd, ExecutablePath=exe)
                for pid, name, cmd, exe in processes
            ]), encoding="utf-8")

            def quote(path):
                return "'" + str(path).replace("'", "''") + "'"

            command = (
                "$ErrorActionPreference = 'Stop'\n"
                f"function Get-CimInstance {{ $items = Get-Content -LiteralPath {quote(fixtures)} -Raw | ConvertFrom-Json; $items }}\n"
                "function Stop-Process { [CmdletBinding()] param([int]$Id, [switch]$Force) Write-Output ('STOPPED=' + $Id) }\n"
                f". {quote(script)}\n"
                "Write-Output ('PROJECT_ROOT=' + $ProjectRoot)\n"
            )
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stopped = [line for line in result.stdout.splitlines() if line.startswith("STOPPED=")]
            self.assertEqual(
                stopped, ["STOPPED=1", "STOPPED=4", "STOPPED=9", "STOPPED=10"],
                f"Fixture root: {root}\n{result.stdout}\n{result.stderr}",
            )

    def test_get_newest_txid(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.return_value = [{"txid": "a"}, {"txid": "b"}]
        self.assertEqual(get_newest_txid(mock_grc), "b")
        mock_grc.call.assert_called_once_with("listtransactions", ["*", 1])
        mock_grc.call.return_value = []
        self.assertIsNone(get_newest_txid(mock_grc))
        mock_grc.call.side_effect = ConnectionError("down")
        self.assertIsNone(get_newest_txid(mock_grc))

    def test_get_last_stake_timestamp_error(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.side_effect = ConnectionError("Node unreachable")
        self.assertIsNone(get_last_stake_timestamp(mock_grc))

    def test_rpc_client_success(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"result": {"version": 50000}, "error": None}
        ).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = client.call("getinfo")
            self.assertEqual(res, {"version": 50000})

    def test_rpc_client_error_response(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"result": None, "error": {"code": -1, "message": "Method not found"}}
        ).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with self.assertRaises(RuntimeError):
                client.call("nonexistent")

    def test_rpc_client_connection_failure(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with self.assertRaises(ConnectionError):
                client.call("getinfo")

    def test_discord_manager_handles_connection_drop(self):
        mgr = DiscordPresenceManager("1545044211945177139")
        with patch("main.Presence") as mock_presence_cls:
            mock_instance = MagicMock()
            mock_presence_cls.return_value = mock_instance

            # Initial connect
            connected = mgr.connect()
            self.assertTrue(connected)
            self.assertTrue(mgr.connected)

            # Update succeeds
            success = mgr.update(details="Staking: 100.00 GRC")
            self.assertTrue(success)
            mock_instance.update.assert_called_once_with(details="Staking: 100.00 GRC")

            # Update fails due to pipe closed
            mock_instance.update.side_effect = Exception("IPC Pipe closed")
            success_fail = mgr.update(details="Staking: 100.00 GRC")
            self.assertFalse(success_fail)
            self.assertFalse(mgr.connected)

    def test_get_executable_path_frozen(self):
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", r"C:\app\Gridcoin-RPC.exe"):
                path = get_executable_path()
                self.assertIn("Gridcoin-RPC.exe", path)
                self.assertTrue(path.startswith('"') and path.endswith('"'))

    def test_is_autostart_enabled(self):
        with patch("sys.platform", "win32"):
            mock_winreg = MagicMock()
            mock_key = MagicMock()
            mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
            mock_winreg.QueryValueEx.return_value = (r'"C:\app\Gridcoin-RPC.exe"', 1)
            mock_winreg.KEY_READ = 1

            with patch.dict("sys.modules", {"winreg": mock_winreg}):
                self.assertTrue(is_autostart_enabled())
                mock_winreg.QueryValueEx.assert_called_once_with(mock_key, "Gridcoin-RPC")

            mock_winreg.QueryValueEx.side_effect = FileNotFoundError()
            with patch.dict("sys.modules", {"winreg": mock_winreg}):
                self.assertFalse(is_autostart_enabled())

    def test_set_autostart(self):
        with patch("sys.platform", "win32"):
            mock_winreg = MagicMock()
            mock_key = MagicMock()
            mock_winreg.CreateKeyEx.return_value.__enter__.return_value = mock_key
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.REG_SZ = 1

            with patch.dict("sys.modules", {"winreg": mock_winreg}):
                with patch(
                    "main.get_executable_path",
                    return_value=r'"C:\app\Gridcoin-RPC.exe"',
                ):
                    # Enable autostart
                    res = set_autostart(True)
                    self.assertTrue(res)
                    mock_winreg.SetValueEx.assert_called_once_with(
                        mock_key, "Gridcoin-RPC", 0, 1, r'"C:\app\Gridcoin-RPC.exe"'
                    )

                    # Disable autostart
                    res = set_autostart(False)
                    self.assertTrue(res)
                    mock_winreg.DeleteValue.assert_called_once_with(mock_key, "Gridcoin-RPC")

    def test_toggle_stat_constraint(self):
        import main

        orig_reward = main.cycle_show_reward
        orig_diff = main.cycle_show_difficulty
        orig_rac = main.cycle_show_rac
        orig_mag = main.cycle_show_mag
        orig_block = main.cycle_show_block
        orig_pool_share = main.cycle_show_pool_share
        orig_total_value = main.cycle_show_total_value
        orig_price = main.cycle_show_price
        orig_peers = main.cycle_show_peers

        try:
            main.cycle_show_reward = True
            main.cycle_show_difficulty = True
            main.cycle_show_rac = True
            main.cycle_show_mag = False
            main.cycle_show_block = False
            main.cycle_show_pool_share = False
            main.cycle_show_total_value = False
            main.cycle_show_price = False
            main.cycle_show_peers = False

            # 1. Toggle reward off -> succeeds
            self.assertTrue(toggle_stat("reward"))
            self.assertFalse(main.cycle_show_reward)
            self.assertTrue(main.cycle_show_difficulty)
            self.assertTrue(main.cycle_show_rac)

            # 2. Toggle difficulty off -> succeeds
            self.assertTrue(toggle_stat("Difficulty"))
            self.assertFalse(main.cycle_show_difficulty)
            self.assertTrue(main.cycle_show_rac)

            # 3. Attempt to toggle rac off (last remaining active stat) -> MUST FAIL and stay True!
            self.assertFalse(toggle_stat("rac"))
            self.assertTrue(main.cycle_show_rac)

            # 4. Re-enable difficulty -> succeeds
            self.assertTrue(toggle_stat("difficulty"))
            self.assertTrue(main.cycle_show_difficulty)

            # 5. Now rac can be toggled off -> succeeds
            self.assertTrue(toggle_stat("Top Project RAC"))
            self.assertFalse(main.cycle_show_rac)

            # 6. Attempt to toggle difficulty off (now the last active) -> MUST FAIL!
            self.assertFalse(toggle_stat("difficulty"))
            self.assertTrue(main.cycle_show_difficulty)

            # 7. Enable new metrics and test toggling them
            self.assertTrue(toggle_stat("Total Magnitude"))
            self.assertTrue(main.cycle_show_mag)
            self.assertTrue(toggle_stat("Block Height"))
            self.assertTrue(main.cycle_show_block)
            self.assertTrue(toggle_stat("Pool Share"))
            self.assertTrue(main.cycle_show_pool_share)
            self.assertTrue(toggle_stat("Total Value ($)"))
            self.assertTrue(main.cycle_show_total_value)
            self.assertTrue(toggle_stat("GRC Price ($)"))
            self.assertTrue(main.cycle_show_price)
            self.assertTrue(toggle_stat("Network Peers"))
            self.assertTrue(main.cycle_show_peers)

            # Disable difficulty, mag, block, pool_share, total_value, price -> peers is last remaining
            self.assertTrue(toggle_stat("difficulty"))
            self.assertTrue(toggle_stat("magnitude"))
            self.assertTrue(toggle_stat("block"))
            self.assertTrue(toggle_stat("pool_share"))
            self.assertTrue(toggle_stat("total_value"))
            self.assertTrue(toggle_stat("price"))
            self.assertFalse(toggle_stat("peers"))
            self.assertTrue(main.cycle_show_peers)

            # 8. Invalid stat name returns False
            self.assertFalse(toggle_stat("unknown_stat"))
        finally:
            main.cycle_show_reward = orig_reward
            main.cycle_show_difficulty = orig_diff
            main.cycle_show_rac = orig_rac
            main.cycle_show_mag = orig_mag
            main.cycle_show_block = orig_block
            main.cycle_show_pool_share = orig_pool_share
            main.cycle_show_total_value = orig_total_value
            main.cycle_show_price = orig_price
            main.cycle_show_peers = orig_peers

    def test_get_alternating_state_custom_selections(self):
        reward = 50.00
        diff = 15.00
        rac_str = "Rosetta RAC: 4,500"

        # 1. Only Reward active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                rac_str,
                show_reward=True,
                show_difficulty=False,
                show_rac=False,
            ),
            "Est. Reward: 50.00 GRC",
        )
        self.assertEqual(
            get_alternating_state(
                1,
                1,
                reward,
                diff,
                rac_str,
                show_reward=True,
                show_difficulty=False,
                show_rac=False,
            ),
            "Est. Reward: 50.00 GRC",
        )

        # 2. Only Difficulty active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                rac_str,
                show_reward=False,
                show_difficulty=True,
                show_rac=False,
            ),
            "Difficulty: 15.00",
        )

        # 3. Only RAC active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                rac_str,
                show_reward=False,
                show_difficulty=False,
                show_rac=True,
            ),
            "Rosetta RAC: 4,500",
        )

        # 4. Only RAC active, but project_rac is None -> returns "RAC: None"
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                None,
                show_reward=False,
                show_difficulty=False,
                show_rac=True,
            ),
            "RAC: None",
        )

        # 5. Reward + RAC active (Difficulty disabled)
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                rac_str,
                show_reward=True,
                show_difficulty=False,
                show_rac=True,
            ),
            "Est. Reward: 50.00 GRC",
        )
        self.assertEqual(
            get_alternating_state(
                1,
                1,
                reward,
                diff,
                rac_str,
                show_reward=True,
                show_difficulty=False,
                show_rac=True,
            ),
            "Rosetta RAC: 4,500",
        )
        self.assertEqual(
            get_alternating_state(
                2,
                1,
                reward,
                diff,
                rac_str,
                show_reward=True,
                show_difficulty=False,
                show_rac=True,
            ),
            "Est. Reward: 50.00 GRC",
        )

        # 6. Difficulty + RAC active (Reward disabled)
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                rac_str,
                show_reward=False,
                show_difficulty=True,
                show_rac=True,
            ),
            "Difficulty: 15.00",
        )
        self.assertEqual(
            get_alternating_state(
                1,
                1,
                reward,
                diff,
                rac_str,
                show_reward=False,
                show_difficulty=True,
                show_rac=True,
            ),
            "Rosetta RAC: 4,500",
        )

        # 7. Fallback when all show_* are False -> returns Reward safely without error
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                rac_str,
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
            ),
            "Est. Reward: 50.00 GRC",
        )

        # 8. Magnitude active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                total_mag=142.5,
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_mag=True,
            ),
            "Magnitude: 142.50",
        )

        # 9. Block active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                block_height=3201400,
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_block=True,
            ),
            "Block: #3,201,400",
        )

        # 10. Pool Share active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                pool_share_str="Pool Share: 0.05%",
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_pool_share=True,
            ),
            "Pool Share: 0.05%",
        )

        # 11. Total Value active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                total_value_str="Total Value: $125.50",
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_total_value=True,
            ),
            "Total Value: $125.50",
        )
        # Total Value fallback when total_value_str is None
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_total_value=True,
            ),
            "Total Value: $0.00",
        )

        # 12. GRC Price active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                price_str="GRC Price: $0.00870",
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_price=True,
            ),
            "GRC Price: $0.00870",
        )
        # GRC Price fallback when price_str is None
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_price=True,
            ),
            "GRC Price: N/A",
        )

        # 13. Network Peers active
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                peers_str="Peers: 18",
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_peers=True,
            ),
            "Peers: 18",
        )
        # Peers fallback when peers_str is None
        self.assertEqual(
            get_alternating_state(
                0,
                1,
                reward,
                diff,
                show_reward=False,
                show_difficulty=False,
                show_rac=False,
                show_peers=True,
            ),
            "Peers: 0",
        )

    def test_trigger_presence_update(self):
        import main

        main.update_event.clear()
        self.assertFalse(main.update_event.is_set())
        trigger_presence_update()
        self.assertTrue(main.update_event.is_set())
        main.update_event.clear()

    def test_get_menu_id_map_and_checks(self):
        sample_options = [
            ("Turn Off / On Presence", None, lambda s: None, 1023),
            ("Hide Balance", None, lambda s: None, 1032),
            (
                "Cycle Stats (Line 2)",
                None,
                [
                    ("Estimated Reward", None, lambda s: None, 1024),
                    ("Difficulty", None, lambda s: None, 1025),
                    ("Top Project RAC", None, lambda s: None, 1026),
                    ("Total Magnitude", None, lambda s: None, 1027),
                    ("Block Height", None, lambda s: None, 1028),
                    ("Pool Share", None, lambda s: None, 1029),
                    ("Total Value ($)", None, lambda s: None, 1033),
                    ("GRC Price ($)", None, lambda s: None, 1034),
                    ("Network Peers", None, lambda s: None, 1035),
                ],
                1030,
            ),
            ("Start with Windows", None, lambda s: None, 1031),
        ]

        id_map = _get_menu_id_map(sample_options)
        self.assertEqual(id_map.get("Hide Balance"), 1032)
        self.assertEqual(id_map.get("Estimated Reward"), 1024)
        self.assertEqual(id_map.get("Difficulty"), 1025)
        self.assertEqual(id_map.get("Top Project RAC"), 1026)
        self.assertEqual(id_map.get("Total Magnitude"), 1027)
        self.assertEqual(id_map.get("Block Height"), 1028)
        self.assertEqual(id_map.get("Pool Share"), 1029)
        self.assertEqual(id_map.get("Total Value ($)"), 1033)
        self.assertEqual(id_map.get("GRC Price ($)"), 1034)
        self.assertEqual(id_map.get("Network Peers"), 1035)
        self.assertEqual(id_map.get("Start with Windows"), 1031)

        # Test update_tray_menu_checks (Windows)
        mock_systray = MagicMock()
        mock_systray._menu = 9999
        mock_systray._menu_options = sample_options

        import ctypes

        mock_u32 = MagicMock()
        mock_windll = MagicMock(user32=mock_u32)
        with ExitStack() as stack:
            stack.enter_context(patch("sys.platform", "win32"))
            stack.enter_context(patch("main.is_autostart_enabled", return_value=True))
            stack.enter_context(patch.object(ctypes, "windll", mock_windll, create=True))
            update_tray_menu_checks(mock_systray)
            # Should have called CheckMenuItem for Start with Windows, Hide Balance and all 9 stats
            self.assertEqual(mock_u32.CheckMenuItem.call_count, 11)

        # Test update_tray_menu_checks on non-Windows (should return immediately)
        with patch("sys.platform", "linux"):
            update_tray_menu_checks(mock_systray)

    def test_format_details_with_staking_status(self):
        # 1. Staking active
        self.assertEqual(format_details(12450.50, is_staking=True), "Staking: 12,450.50 GRC")
        self.assertEqual(format_details(0.0, is_staking=True), "Staking: 0.00 GRC")

        # 2. Wallet locked or staking disabled (is_staking is False)
        self.assertEqual(format_details(12450.50, is_staking=False), "Not Staking: 12,450.50 GRC")
        self.assertEqual(format_details(0.0, is_staking=False), "Staking: Inactive")

        # 3. None (status unavailable -> backward compatible fallback)
        self.assertEqual(format_details(12450.50, is_staking=None), "Staking: 12,450.50 GRC")

        # 4. Hide balance enabled (privacy mode)
        self.assertEqual(
            format_details(12450.50, is_staking=True, hide_balance=True),
            "Staking ********* GRC",
        )
        self.assertEqual(
            format_details(0.0, is_staking=True, hide_balance=True),
            "Staking ********* GRC",
        )
        self.assertEqual(
            format_details(12450.50, is_staking=False, hide_balance=True),
            "Not Staking ********* GRC",
        )
        self.assertEqual(
            format_details(0.0, is_staking=False, hide_balance=True),
            "Staking: Inactive",
        )
        self.assertEqual(
            format_details(12450.50, is_staking=None, hide_balance=True),
            "Staking ********* GRC",
        )

    def test_is_wallet_staking(self):
        # Boolean values
        self.assertTrue(is_wallet_staking({"staking": True}))
        self.assertFalse(is_wallet_staking({"staking": False}))

        # Int / string representations
        self.assertTrue(is_wallet_staking({"staking": 1}))
        self.assertTrue(is_wallet_staking({"staking": "true"}))
        self.assertFalse(is_wallet_staking({"staking": 0}))
        self.assertFalse(is_wallet_staking({"staking": "false"}))

        # Missing or invalid
        self.assertIsNone(is_wallet_staking({}))
        self.assertIsNone(is_wallet_staking(None))
        self.assertIsNone(is_wallet_staking("invalid"))

    def test_get_presence_assets(self):
        # 1. Staking active
        with ExitStack() as stack:
            stack.enter_context(patch("main.DISCORD_LARGE_IMAGE", "gridcoin"))
            stack.enter_context(patch("main.DISCORD_LARGE_TEXT", "Gridcoin Network"))
            stack.enter_context(patch("main.DISCORD_SMALL_IMAGE_STAKING", "staking"))
            stack.enter_context(patch("main.DISCORD_SMALL_IMAGE_OFFLINE", "offline"))
            assets = get_presence_assets(is_offline=False, is_staking=True)
            self.assertEqual(assets["large_image"], "gridcoin")
            self.assertEqual(assets["large_text"], "Gridcoin Network")
            self.assertEqual(assets["small_image"], "staking")
            self.assertEqual(assets["small_text"], "Staking Active")

            # 2. Staking inactive / locked
            assets_locked = get_presence_assets(is_offline=False, is_staking=False)
            self.assertEqual(assets_locked["small_image"], "offline")
            self.assertEqual(assets_locked["small_text"], "Staking Inactive / Locked")

            # 3. Wallet offline
            assets_offline = get_presence_assets(is_offline=True)
            self.assertEqual(assets_offline["small_image"], "offline")
            self.assertEqual(assets_offline["small_text"], "Wallet Offline")

        # 4. When image configs are empty string
        with ExitStack() as stack:
            stack.enter_context(patch("main.DISCORD_LARGE_IMAGE", ""))
            stack.enter_context(patch("main.DISCORD_SMALL_IMAGE_STAKING", ""))
            stack.enter_context(patch("main.DISCORD_SMALL_IMAGE_OFFLINE", ""))
            self.assertEqual(get_presence_assets(is_offline=False, is_staking=True), {})

    def test_settings_persistence(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_settings = Path(tmpdir) / "settings.json"
            with patch("main.SETTINGS_FILE", tmp_settings):
                # Save settings
                with ExitStack() as stack:
                    stack.enter_context(patch("main.presence_enabled", False))
                    stack.enter_context(patch("main.hide_balance", False))
                    stack.enter_context(patch("main.cycle_show_reward", False))
                    stack.enter_context(patch("main.cycle_show_difficulty", True))
                    stack.enter_context(patch("main.cycle_show_rac", True))
                    saved = save_settings()
                    self.assertTrue(saved)
                    self.assertTrue(tmp_settings.is_file())

                # Load settings
                loaded = load_settings()
                self.assertFalse(loaded["presence_enabled"])
                self.assertFalse(loaded["hide_balance"])
                self.assertFalse(loaded["cycle_show_reward"])
                self.assertTrue(loaded["cycle_show_difficulty"])
                self.assertTrue(loaded["cycle_show_rac"])

                # First-run when settings.json does not exist (Estimated Reward and hide_balance enabled)
                if tmp_settings.is_file():
                    tmp_settings.unlink()
                first_run = load_settings()
                self.assertTrue(first_run["presence_enabled"])
                self.assertTrue(first_run["hide_balance"])
                self.assertTrue(first_run["cycle_show_reward"])
                self.assertFalse(first_run["cycle_show_difficulty"])
                self.assertFalse(first_run["cycle_show_rac"])
                self.assertFalse(first_run["cycle_show_mag"])
                self.assertFalse(first_run["cycle_show_block"])
                self.assertFalse(first_run["cycle_show_pool_share"])
                self.assertFalse(first_run["cycle_show_total_value"])
                self.assertFalse(first_run["cycle_show_price"])
                self.assertFalse(first_run["cycle_show_peers"])

                # Corrupted file returns defaults
                with open(tmp_settings, "w", encoding="utf-8") as f:
                    f.write("invalid json")
                defaults = load_settings()
                self.assertTrue(defaults["presence_enabled"])
                self.assertTrue(defaults["hide_balance"])
                self.assertTrue(defaults["cycle_show_reward"])
                self.assertFalse(defaults["cycle_show_difficulty"])
                self.assertFalse(defaults["cycle_show_rac"])
                self.assertFalse(defaults["cycle_show_mag"])
                self.assertFalse(defaults["cycle_show_block"])
                self.assertFalse(defaults["cycle_show_pool_share"])
                self.assertFalse(defaults["cycle_show_total_value"])
                self.assertFalse(defaults["cycle_show_price"])
                self.assertFalse(defaults["cycle_show_peers"])

                # File with all 9 stats False enforces at least one True (defaults reward to True)
                with open(tmp_settings, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "cycle_show_reward": False,
                            "cycle_show_difficulty": False,
                            "cycle_show_rac": False,
                            "cycle_show_mag": False,
                            "cycle_show_block": False,
                            "cycle_show_pool_share": False,
                            "cycle_show_total_value": False,
                            "cycle_show_price": False,
                            "cycle_show_peers": False,
                        },
                        f,
                    )
                enforced = load_settings()
                self.assertTrue(enforced["cycle_show_reward"])

    def test_save_settings_preserves_remote_rpc_config(self):
        rpc_settings = {
            "rpc_host": "nas.local", "rpc_port": 15717,
            "rpc_user": "test", "rpc_password": "test-password",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text(json.dumps(rpc_settings), encoding="utf-8")
            with patch("main.SETTINGS_FILE", settings_path), patch("main.hide_balance", False):
                self.assertTrue(save_settings())
                loaded = load_settings()
            self.assertEqual({key: loaded[key] for key in rpc_settings}, rpc_settings)
            self.assertFalse(loaded["hide_balance"])

    def test_total_magnitude_extraction(self):
        # 1. From explainmagnitude list with Total project
        explain_data = [
            {"project": "rosetta@home", "rac": 500, "magnitude": 12.5},
            {"project": "Total", "rac": 500, "magnitude": 142.5},
        ]
        self.assertEqual(get_total_magnitude(explain_data), 142.5)

        # 2. From mining_info root magnitude
        self.assertEqual(get_total_magnitude(mining_info={"magnitude": 150.0}), 150.0)

        # 3. From mining_info nested staking magnitude
        self.assertEqual(get_total_magnitude(mining_info={"staking": {"magnitude": "88.2"}}), 88.2)

        # 4. None / missing
        self.assertIsNone(get_total_magnitude(None, {}))
        self.assertIsNone(get_total_magnitude([], None))

    def test_block_height_extraction_and_formatting(self):
        # Extraction
        self.assertEqual(get_block_height({"blocks": 3201400}), 3201400)
        self.assertEqual(get_block_height({"blocks": "3201400"}), 3201400)
        self.assertIsNone(get_block_height({"blocks": "invalid"}))
        self.assertIsNone(get_block_height({}))
        self.assertIsNone(get_block_height(None))

        # Formatting
        self.assertEqual(format_block_height(3201400), "Block: #3,201,400")
        self.assertEqual(format_block_height("3201400"), "Block: #3,201,400")
        self.assertEqual(format_block_height(0), "Block: Unknown")
        self.assertEqual(format_block_height(-1), "Block: Unknown")
        self.assertEqual(format_block_height(None), "Block: Unknown")

    def test_network_stake_weight_and_pool_share(self):
        # 1. Direct netstakingGRCvalue (actual GRC coins in staking pool)
        self.assertEqual(get_network_stake_weight({"netstakingGRCvalue": 130000000.0}), 130000000.0)
        self.assertEqual(get_network_stake_weight({"netstakingGRCvalue": "25000000"}), 25000000.0)

        # 2. Raw netstakeweight (with 80.0x factor: 10,400,000,000 / 80 = 130,000,000)
        self.assertEqual(get_network_stake_weight({"netstakeweight": 10400000000.0}), 130000000.0)
        self.assertEqual(get_network_stake_weight({"netstakeweight": "80000000"}), 1000000.0)

        # 3. Preference for netstakingGRCvalue when both are present
        self.assertEqual(
            get_network_stake_weight(
                {"netstakeweight": 10400000000.0, "netstakingGRCvalue": 130000000.0}
            ),
            130000000.0,
        )

        # 4. Zero or missing
        self.assertEqual(get_network_stake_weight({}), 0.0)
        self.assertEqual(get_network_stake_weight(None), 0.0)

        # Pool share formatting
        # 60,000 / 130,000,000 = 0.04615% -> 0.05%
        self.assertEqual(format_pool_share(60000.0, 130000000.0), "Pool Share: 0.05%")
        # 12,500 / 25,000,000 = 0.0005 = 0.05%
        self.assertEqual(format_pool_share(12500.0, 25000000.0), "Pool Share: 0.05%")
        # Sub-0.01% with 4 decimals
        # 100 / 25,000,000 = 0.000004 = 0.0004%
        self.assertEqual(format_pool_share(100.0, 25000000.0), "Pool Share: 0.0004%")
        # Zero cases
        self.assertEqual(format_pool_share(0.0, 25000000.0), "Pool Share: 0.00%")
        self.assertEqual(format_pool_share(1000.0, 0.0), "Pool Share: 0.00%")
        self.assertEqual(format_pool_share(-100.0, 25000000.0), "Pool Share: 0.00%")
        # Cap at 100%
        self.assertEqual(format_pool_share(200.0, 100.0), "Pool Share: 100.00%")

    def test_env_example_file_exists(self):
        example_path = PROJECT_ROOT / ".env.example"
        self.assertTrue(
            example_path.is_file(),
            ".env.example template file must exist in repository root",
        )
        content = example_path.read_text(encoding="utf-8")
        self.assertIn("DISCORD_CLIENT_ID", content)
        self.assertIn("RPC_USER", content)
        self.assertIn("UPDATE_INTERVAL", content)

    def test_parse_args(self):
        # Default args
        args_default = parse_args([])
        self.assertFalse(args_default.headless)
        self.assertIsNone(args_default.rpc_host)
        self.assertIsNone(args_default.rpc_port)
        self.assertIsNone(args_default.rpc_user)
        self.assertIsNone(args_default.rpc_password)

        # Custom args
        custom_args = [
            "--headless",
            "--rpc-host",
            "192.168.1.100",
            "--rpc-port",
            "15716",
            "--rpc-user",
            "custom_user",
            "--rpc-password",
            "custom_pass",
        ]
        args = parse_args(custom_args)
        self.assertTrue(args.headless)
        self.assertEqual(args.rpc_host, "192.168.1.100")
        self.assertEqual(args.rpc_port, 15716)
        self.assertEqual(args.rpc_user, "custom_user")
        self.assertEqual(args.rpc_password, "custom_pass")

    def test_load_settings_remote_node(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "rpc_host": "nas.local",
                        "rpc_port": 15717,
                        "rpc_user": "nas_user",
                        "rpc_password": "nas_password",
                    }
                ),
                encoding="utf-8",
            )
            with patch("main.SETTINGS_FILE", settings_path):
                s = load_settings()
                self.assertEqual(s.get("rpc_host"), "nas.local")
                self.assertEqual(s.get("rpc_port"), 15717)
                self.assertEqual(s.get("rpc_user"), "nas_user")
                self.assertEqual(s.get("rpc_password"), "nas_password")

    def test_apply_rpc_config_priority(self):
        import main

        # 1. settings.json populated, no env or CLI
        mock_settings = {
            "rpc_host": "nas.lan",
            "rpc_port": 15718,
            "rpc_user": "user_s",
            "rpc_password": "pass_s",
        }
        with patch("main.load_settings", return_value=mock_settings):
            with patch.dict("os.environ", {}, clear=True):
                with patch("main.find_gridcoin_conf", return_value=None):
                    apply_rpc_config(parse_args([]))
                    self.assertEqual(main.RPC_HOST, "nas.lan")
                    self.assertEqual(main.RPC_PORT, 15718)
                    self.assertEqual(main.RPC_USER, "user_s")
                    self.assertEqual(main.RPC_PASS, "pass_s")

        # 2. Environment variables override settings.json
        env_vars = {
            "RPC_HOST": "10.0.0.50",
            "RPC_PORT": "15719",
            "RPC_USER": "env_user",
            "RPC_PASSWORD": "env_password",
        }
        with patch("main.load_settings", return_value=mock_settings):
            with patch.dict("os.environ", env_vars):
                with patch("main.find_gridcoin_conf", return_value=None):
                    apply_rpc_config(parse_args([]))
                    self.assertEqual(main.RPC_HOST, "10.0.0.50")
                    self.assertEqual(main.RPC_PORT, 15719)
                    self.assertEqual(main.RPC_USER, "env_user")
                    self.assertEqual(main.RPC_PASS, "env_password")

        # 3. CLI arguments override environment variables
        cli_args = parse_args(["--rpc-host", "server.gridcoin", "--rpc-port", "15720"])
        with patch("main.load_settings", return_value=mock_settings):
            with patch.dict("os.environ", env_vars):
                with patch("main.find_gridcoin_conf", return_value=None):
                    apply_rpc_config(cli_args)
                    self.assertEqual(main.RPC_HOST, "server.gridcoin")
                    self.assertEqual(main.RPC_PORT, 15720)
                    self.assertEqual(main.RPC_USER, "env_user")
                    self.assertEqual(main.RPC_PASS, "env_password")

    def test_remote_node_appdata_empty(self):
        import main

        # When %AppData% / find_gridcoin_conf is None, remote config works smoothly
        with patch("main.find_gridcoin_conf", return_value=None):
            with patch("main.RPC_USER", "remote_user"):
                with patch("main.RPC_PASS", "remote_pass"):
                    with patch("main.RPC_HOST", "192.168.1.5"):
                        with patch("main.RPC_PORT", 15715):
                            main.auto_detect_rpc_credentials()
                            self.assertEqual(main.RPC_HOST, "192.168.1.5")
                            self.assertEqual(main.RPC_USER, "remote_user")
                            self.assertEqual(main.RPC_PASS, "remote_pass")

    def test_rpc_client_ipv6_formatting(self):
        # IPv6 without brackets
        c1 = GridcoinRPC("::1", 15715, "u", "p")
        self.assertEqual(c1.url, "http://[::1]:15715")

        # IPv6 with brackets
        c2 = GridcoinRPC("[fe80::1]", 15715, "u", "p")
        self.assertEqual(c2.url, "http://[fe80::1]:15715")

        # IPv4
        c3 = GridcoinRPC("127.0.0.1", 15715, "u", "p")
        self.assertEqual(c3.url, "http://127.0.0.1:15715")

    def test_rpc_client_http_401_permission_error(self):
        client = GridcoinRPC("127.0.0.1", 15715, "testuser", "badpass")
        import urllib.error

        http_401 = urllib.error.HTTPError("http://127.0.0.1:15715", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=http_401):
            with self.assertRaises(PermissionError) as ctx:
                client.call("getinfo")
            self.assertIn("401 Unauthorized", str(ctx.exception))
            self.assertIn("testuser", str(ctx.exception))

    def test_parse_args_port_validation(self):
        # Valid ports
        args_valid = parse_args(["--rpc-port", "15715"])
        self.assertEqual(args_valid.rpc_port, 15715)

        # Invalid port: out of range
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                parse_args(["--rpc-port", "0"])
            with self.assertRaises(SystemExit):
                parse_args(["--rpc-port", "70000"])

    def test_format_grc_price(self):
        self.assertEqual(format_grc_price(None), "GRC Price: N/A")
        self.assertEqual(format_grc_price(0.0), "GRC Price: N/A")
        self.assertEqual(format_grc_price(-0.05), "GRC Price: N/A")
        self.assertEqual(format_grc_price(0.0087123), "GRC Price: $0.00871")
        self.assertEqual(format_grc_price(1.234567), "GRC Price: $1.23457")

    def test_format_total_value_usd(self):
        self.assertEqual(format_total_value_usd(0, 0.008), "Total Value: $0.00")
        self.assertEqual(format_total_value_usd(1000, 0), "Total Value: $0.00")
        self.assertEqual(format_total_value_usd(1000, None), "Total Value: $0.00")
        self.assertEqual(format_total_value_usd(-50, 0.008), "Total Value: $0.00")
        self.assertEqual(format_total_value_usd(50, 0.00871), "Total Value: $0.4355")
        self.assertEqual(format_total_value_usd(1000, 0.00871), "Total Value: $8.71")
        self.assertEqual(format_total_value_usd(1000000, 0.00871), "Total Value: $8,710.00")

    def test_get_grc_usd_price_coingecko_and_fallback(self):
        import main

        main._cached_price = None
        main._last_price_fetch = 0.0

        # 1. CoinGecko success
        mock_cg_resp = io.BytesIO(b'{"gridcoin-research": {"usd": 0.00855}}')
        with patch("urllib.request.urlopen", return_value=mock_cg_resp):
            price = get_grc_usd_price(timeout=2)
            self.assertEqual(price, 0.00855)

        # 2. Caching: immediate next call does not touch urlopen
        with patch("urllib.request.urlopen", side_effect=AssertionError("Should use cache")):
            self.assertEqual(get_grc_usd_price(), 0.00855)

        # 3. Expire cache: CoinGecko fails, fallback to CoinPaprika
        main._last_price_fetch = 0.0
        import urllib.error

        cg_err = urllib.error.URLError("CoinGecko unreachable")
        mock_cp_resp = io.BytesIO(b'{"quotes": {"USD": {"price": 0.00862}}}')

        def mock_urlopen(req, timeout=5):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "coingecko" in url:
                raise cg_err
            return mock_cp_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            price = get_grc_usd_price(timeout=2)
            self.assertEqual(price, 0.00862)

        # 4. Both fail, returns cached price if available, or None if no cache
        main._last_price_fetch = 0.0
        main._cached_price = None
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network down")):
            price = get_grc_usd_price(timeout=2)
            self.assertIsNone(price)

    def test_get_total_balance(self):
        mock_grc = MagicMock()

        # 1. getwalletinfo returns balance + immature_balance
        mock_grc.call.side_effect = lambda cmd: (
            {"balance": 15000.5, "immature_balance": 500.0} if cmd == "getwalletinfo" else None
        )
        self.assertEqual(get_total_balance(mock_grc, active_coins=1000.0), 15500.5)

        # 2. getwalletinfo fails, getbalance succeeds
        def rpc_side_effect_2(cmd):
            if cmd == "getwalletinfo":
                raise RuntimeError("method not found")
            if cmd == "getbalance":
                return 12345.67
            return None

        mock_grc.call.side_effect = rpc_side_effect_2
        self.assertEqual(get_total_balance(mock_grc, active_coins=1000.0), 12345.67)

        # 3. Both fail, fallback to active_coins
        mock_grc.call.side_effect = RuntimeError("RPC error")
        self.assertEqual(get_total_balance(mock_grc, active_coins=7777.0), 7777.0)

    def test_get_blockchain_sync_status(self):
        # 1. Initial block download active
        syncing, prog = get_blockchain_sync_status(
            {
                "initialblockdownload": True,
                "verificationprogress": 0.456,
            }
        )
        self.assertTrue(syncing)
        self.assertAlmostEqual(prog, 0.456)

        # 2. Behind network (verificationprogress < 0.9995 and headers > blocks + 5)
        syncing, prog = get_blockchain_sync_status(
            {
                "initialblockdownload": False,
                "verificationprogress": 0.985,
                "blocks": 3200000,
                "headers": 3201400,
            }
        )
        self.assertTrue(syncing)
        self.assertAlmostEqual(prog, 0.985)

        # 3. Fully synced
        syncing, prog = get_blockchain_sync_status(
            {
                "initialblockdownload": False,
                "verificationprogress": 0.99999,
                "blocks": 3201400,
                "headers": 3201400,
            }
        )
        self.assertFalse(syncing)
        self.assertAlmostEqual(prog, 1.0)

        # 4. Fallback headers vs blocks when verificationprogress is missing
        syncing, prog = get_blockchain_sync_status(
            {
                "blocks": 1000,
                "headers": 2000,
            }
        )
        self.assertTrue(syncing)
        self.assertAlmostEqual(prog, 0.5)

        # 5. Invalid or empty input
        self.assertEqual(get_blockchain_sync_status({}), (False, 1.0))
        self.assertEqual(get_blockchain_sync_status(None), (False, 1.0))

    def test_format_sync_details(self):
        self.assertEqual(format_sync_details(0.9845), "Syncing: 98.5%")
        self.assertEqual(format_sync_details(0.005), "Syncing: 0.5%")
        self.assertEqual(format_sync_details(0.0, block_height=3201400), "Syncing: #3,201,400")
        self.assertEqual(format_sync_details(0.0, None), "Syncing Blockchain")

    def test_get_presence_assets_syncing(self):
        with ExitStack() as stack:
            stack.enter_context(patch("main.DISCORD_LARGE_IMAGE", "gridcoin"))
            stack.enter_context(patch("main.DISCORD_LARGE_TEXT", "Gridcoin Network"))
            stack.enter_context(patch("main.DISCORD_SMALL_IMAGE_OFFLINE", "offline"))
            assets = get_presence_assets(
                is_offline=False,
                is_staking=False,
                is_syncing=True,
                sync_progress=0.984,
            )
            self.assertEqual(assets["small_image"], "offline")
            self.assertEqual(assets["small_text"], "Syncing (98.4%)")

    def test_get_peer_count_and_format_peers(self):
        mock_grc = MagicMock()

        # 1. From network_info dict argument
        self.assertEqual(get_peer_count(mock_grc, {"connections": 18}), 18)

        # 2. From getnetworkinfo RPC call
        mock_grc.call.side_effect = lambda cmd: (
            {"connections": 14} if cmd == "getnetworkinfo" else None
        )
        self.assertEqual(get_peer_count(mock_grc), 14)

        # 3. getnetworkinfo fails, fallback to getinfo
        def rpc_side_effect(cmd):
            if cmd == "getnetworkinfo":
                raise RuntimeError("Not found")
            if cmd == "getinfo":
                return {"connections": 9}
            return None

        mock_grc.call.side_effect = rpc_side_effect
        self.assertEqual(get_peer_count(mock_grc), 9)

        # 4. Both fail
        mock_grc.call.side_effect = RuntimeError("RPC error")
        self.assertIsNone(get_peer_count(mock_grc))

        # 5. Format peers
        self.assertEqual(format_peers(18), "Peers: 18")
        self.assertEqual(format_peers(0), "Peers: 0")
        self.assertEqual(format_peers(None), "Peers: 0")


if __name__ == "__main__":
    unittest.main()
