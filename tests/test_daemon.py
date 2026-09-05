"""Unit test suite for Gridcoin Discord RPC daemon."""

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
import json

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (
    format_details,
    format_magnitude,
    format_reward,
    format_difficulty,
    get_difficulty,
    get_top_project_rac,
    get_alternating_state,
    get_active_staking_coins,
    get_expected_reward,
    get_last_stake_timestamp,
    get_newest_txid,
    scan_new_stakes,
    get_presence_buttons,
    get_executable_path,
    is_autostart_enabled,
    set_autostart,
    DiscordPresenceManager,
    toggle_stat,
    trigger_presence_update,
    _get_menu_id_map,
    update_tray_menu_checks,
    is_wallet_staking,
    get_presence_assets,
    load_settings,
    save_settings,
    get_total_magnitude,
    get_block_height,
    format_block_height,
    get_network_stake_weight,
    format_pool_share,
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
        self.assertEqual(get_alternating_state(0, 1, reward, diff, rac_str), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(1, 1, reward, diff, rac_str), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(2, 1, reward, diff, rac_str), "odlk1 RAC: 38,426")
        self.assertEqual(get_alternating_state(3, 1, reward, diff, rac_str), "Est. Reward: 25.50 GRC")

        # 3-way rotation for switch_cycles = 2:
        self.assertEqual(get_alternating_state(0, 2, reward, diff, rac_str), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(1, 2, reward, diff, rac_str), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(2, 2, reward, diff, rac_str), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(3, 2, reward, diff, rac_str), "Difficulty: 12.34")
        self.assertEqual(get_alternating_state(4, 2, reward, diff, rac_str), "odlk1 RAC: 38,426")
        self.assertEqual(get_alternating_state(5, 2, reward, diff, rac_str), "odlk1 RAC: 38,426")
        self.assertEqual(get_alternating_state(6, 2, reward, diff, rac_str), "Est. Reward: 25.50 GRC")

        # When project_rac is None, fallback to 2-way:
        self.assertEqual(get_alternating_state(0, 2, reward, diff, None), "Est. Reward: 25.50 GRC")
        self.assertEqual(get_alternating_state(2, 2, reward, diff, None), "Difficulty: 12.34")

    def test_get_presence_buttons(self):
        with patch("main.GITHUB_REPO_URL", "https://github.com/nikolaevichsmor/Gridcoin-RPC"), \
             patch("main.GITHUB_BUTTON_LABEL", "GitHub"), \
             patch("main.GRIDCOIN_WEBSITE_URL", "https://gridcoin.us/"), \
             patch("main.GRIDCOIN_WEBSITE_LABEL", "What is this?"):
            buttons = get_presence_buttons()
            self.assertEqual(
                buttons,
                [
                    {"label": "GitHub", "url": "https://github.com/nikolaevichsmor/Gridcoin-RPC"},
                    {"label": "What is this?", "url": "https://gridcoin.us/"},
                ],
            )

        with patch("main.GITHUB_REPO_URL", "https://github.com/nikolaevichsmor/Gridcoin-RPC"), \
             patch("main.GRIDCOIN_WEBSITE_URL", ""):
            buttons = get_presence_buttons()
            self.assertEqual(
                buttons,
                [{"label": "GitHub", "url": "https://github.com/nikolaevichsmor/Gridcoin-RPC"}],
            )

        with patch("main.GITHUB_REPO_URL", ""), \
             patch("main.GRIDCOIN_WEBSITE_URL", ""):
            buttons = get_presence_buttons()
            self.assertIsNone(buttons)

    def test_get_last_stake_timestamp(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.return_value = [
            {"category": "receive", "amount": 100, "time": 1700000000, "blocktime": 1700000000},
            {"category": "stake", "amount": 10, "time": 1700000500, "blocktime": 1700000500},
            {"category": "immature", "amount": 10, "time": 1700000800, "blocktime": 1700000800},
            {"category": "generate", "amount": 10, "time": 1700001000, "blocktime": 1700001000},
            {"category": "send", "amount": -50, "time": 1700002000, "blocktime": 1700002000},
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
            {"category": "generate", "amount": 10, "time": 1700000500, "confirmations": 10},
            {"category": "generate", "amount": 10, "time": 1700001000, "confirmations": -1},
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
            [{"category": "stake", "amount": 10, "time": 1700000999, "confirmations": 5}],
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
                            from main import auto_detect_rpc_credentials
                            import main
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

        with patch("main.running", True), patch("main.presence_enabled", True), \
             patch("main.time.time", side_effect=lambda: clock["now"]), \
             patch("main.time.sleep"):
            main.polling_worker(mock_grc, mock_discord)

        return starts, lt_params

    def test_polling_worker_periodic_check_is_incremental(self):
        # Steady state: a dozen non-stake entries arrived since the initial
        # scan, pushing the last stake out of the 10 newest. The periodic check
        # must read one page and stop at the marker, not fall back to a
        # 500-entry query.
        old_stake = {"category": "generate", "txid": "A", "time": 1000, "confirmations": 50}
        newer = [
            {"category": "receive", "txid": f"n{i}", "time": 1100 + i, "confirmations": 1}
            for i in range(12)
        ]
        starts, lt_params = self._run_worker_two_iterations([old_stake], [old_stake] + newer)
        self.assertEqual(starts, [1000, 1000])
        self.assertEqual(lt_params, [["*", 50, 0]])

    def test_polling_worker_periodic_check_finds_stake_beyond_500_entries(self):
        # A flood of entries (more than the 500-entry fallback window) lands
        # between two checks. The new stake behind them must still be found.
        old_stake = {"category": "generate", "txid": "A", "time": 1000, "confirmations": 50}
        new_stake = {"category": "generate", "txid": "S", "time": 2000, "confirmations": 3}
        flood = [
            {"category": "receive", "txid": f"n{i}", "time": 2100 + i, "confirmations": 1}
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
        mock_resp.read.return_value = json.dumps({"result": {"version": 50000}, "error": None}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = client.call("getinfo")
            self.assertEqual(res, {"version": 50000})

    def test_rpc_client_error_response(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": None, "error": {"code": -1, "message": "Method not found"}}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with self.assertRaises(RuntimeError):
                client.call("nonexistent")

    def test_rpc_client_connection_failure(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
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
                with patch("main.get_executable_path", return_value=r'"C:\app\Gridcoin-RPC.exe"'):
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

        try:
            main.cycle_show_reward = True
            main.cycle_show_difficulty = True
            main.cycle_show_rac = True
            main.cycle_show_mag = False
            main.cycle_show_block = False
            main.cycle_show_pool_share = False

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

            # Disable difficulty, mag, block -> pool share is last remaining
            self.assertTrue(toggle_stat("difficulty"))
            self.assertTrue(toggle_stat("magnitude"))
            self.assertTrue(toggle_stat("block"))
            self.assertFalse(toggle_stat("pool_share"))
            self.assertTrue(main.cycle_show_pool_share)

            # 8. Invalid stat name returns False
            self.assertFalse(toggle_stat("unknown_stat"))
        finally:
            main.cycle_show_reward = orig_reward
            main.cycle_show_difficulty = orig_diff
            main.cycle_show_rac = orig_rac
            main.cycle_show_mag = orig_mag
            main.cycle_show_block = orig_block
            main.cycle_show_pool_share = orig_pool_share

    def test_get_alternating_state_custom_selections(self):
        reward = 50.00
        diff = 15.00
        rac_str = "Rosetta RAC: 4,500"

        # 1. Only Reward active
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, rac_str, show_reward=True, show_difficulty=False, show_rac=False),
            "Est. Reward: 50.00 GRC",
        )
        self.assertEqual(
            get_alternating_state(1, 1, reward, diff, rac_str, show_reward=True, show_difficulty=False, show_rac=False),
            "Est. Reward: 50.00 GRC",
        )

        # 2. Only Difficulty active
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, rac_str, show_reward=False, show_difficulty=True, show_rac=False),
            "Difficulty: 15.00",
        )

        # 3. Only RAC active
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, rac_str, show_reward=False, show_difficulty=False, show_rac=True),
            "Rosetta RAC: 4,500",
        )

        # 4. Only RAC active, but project_rac is None -> returns "RAC: None"
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, None, show_reward=False, show_difficulty=False, show_rac=True),
            "RAC: None",
        )

        # 5. Reward + RAC active (Difficulty disabled)
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, rac_str, show_reward=True, show_difficulty=False, show_rac=True),
            "Est. Reward: 50.00 GRC",
        )
        self.assertEqual(
            get_alternating_state(1, 1, reward, diff, rac_str, show_reward=True, show_difficulty=False, show_rac=True),
            "Rosetta RAC: 4,500",
        )
        self.assertEqual(
            get_alternating_state(2, 1, reward, diff, rac_str, show_reward=True, show_difficulty=False, show_rac=True),
            "Est. Reward: 50.00 GRC",
        )

        # 6. Difficulty + RAC active (Reward disabled)
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, rac_str, show_reward=False, show_difficulty=True, show_rac=True),
            "Difficulty: 15.00",
        )
        self.assertEqual(
            get_alternating_state(1, 1, reward, diff, rac_str, show_reward=False, show_difficulty=True, show_rac=True),
            "Rosetta RAC: 4,500",
        )

        # 7. Fallback when all show_* are False -> returns Reward safely without error
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, rac_str, show_reward=False, show_difficulty=False, show_rac=False),
            "Est. Reward: 50.00 GRC",
        )

        # 8. Magnitude active
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, total_mag=142.5, show_reward=False, show_difficulty=False, show_rac=False, show_mag=True),
            "Magnitude: 142.50",
        )

        # 9. Block active
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, block_height=3201400, show_reward=False, show_difficulty=False, show_rac=False, show_block=True),
            "Block: #3,201,400",
        )

        # 10. Pool Share active
        self.assertEqual(
            get_alternating_state(0, 1, reward, diff, pool_share_str="Pool Share: 0.05%", show_reward=False, show_difficulty=False, show_rac=False, show_pool_share=True),
            "Pool Share: 0.05%",
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
                ],
                1030,
            ),
            ("Start with Windows", None, lambda s: None, 1031),
        ]

        id_map = _get_menu_id_map(sample_options)
        self.assertEqual(id_map.get("Estimated Reward"), 1024)
        self.assertEqual(id_map.get("Difficulty"), 1025)
        self.assertEqual(id_map.get("Top Project RAC"), 1026)
        self.assertEqual(id_map.get("Total Magnitude"), 1027)
        self.assertEqual(id_map.get("Block Height"), 1028)
        self.assertEqual(id_map.get("Pool Share"), 1029)
        self.assertEqual(id_map.get("Start with Windows"), 1031)

        # Test update_tray_menu_checks (Windows)
        mock_systray = MagicMock()
        mock_systray._menu = 9999
        mock_systray._menu_options = sample_options

        import ctypes
        mock_u32 = MagicMock()
        mock_windll = MagicMock(user32=mock_u32)
        with patch("sys.platform", "win32"), \
             patch("main.is_autostart_enabled", return_value=True), \
             patch.object(ctypes, "windll", mock_windll, create=True):
            update_tray_menu_checks(mock_systray)
            # Should have called CheckMenuItem for Start with Windows and all 6 stats
            self.assertEqual(mock_u32.CheckMenuItem.call_count, 7)

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
        with patch("main.DISCORD_LARGE_IMAGE", "gridcoin"), \
             patch("main.DISCORD_LARGE_TEXT", "Gridcoin Network"), \
             patch("main.DISCORD_SMALL_IMAGE_STAKING", "staking"), \
             patch("main.DISCORD_SMALL_IMAGE_OFFLINE", "offline"):
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
        with patch("main.DISCORD_LARGE_IMAGE", ""), \
             patch("main.DISCORD_SMALL_IMAGE_STAKING", ""), \
             patch("main.DISCORD_SMALL_IMAGE_OFFLINE", ""):
            self.assertEqual(get_presence_assets(is_offline=False, is_staking=True), {})

    def test_settings_persistence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_settings = Path(tmpdir) / "settings.json"
            with patch("main.SETTINGS_FILE", tmp_settings):
                # Save settings
                with patch("main.presence_enabled", False), \
                     patch("main.cycle_show_reward", False), \
                     patch("main.cycle_show_difficulty", True), \
                     patch("main.cycle_show_rac", True):
                    saved = save_settings()
                    self.assertTrue(saved)
                    self.assertTrue(tmp_settings.is_file())

                # Load settings
                loaded = load_settings()
                self.assertFalse(loaded["presence_enabled"])
                self.assertFalse(loaded["cycle_show_reward"])
                self.assertTrue(loaded["cycle_show_difficulty"])
                self.assertTrue(loaded["cycle_show_rac"])

                # First-run when settings.json does not exist (only Estimated Reward enabled)
                if tmp_settings.is_file():
                    tmp_settings.unlink()
                first_run = load_settings()
                self.assertTrue(first_run["presence_enabled"])
                self.assertTrue(first_run["cycle_show_reward"])
                self.assertFalse(first_run["cycle_show_difficulty"])
                self.assertFalse(first_run["cycle_show_rac"])
                self.assertFalse(first_run["cycle_show_mag"])
                self.assertFalse(first_run["cycle_show_block"])
                self.assertFalse(first_run["cycle_show_pool_share"])

                # Corrupted file returns defaults
                with open(tmp_settings, "w", encoding="utf-8") as f:
                    f.write("invalid json")
                defaults = load_settings()
                self.assertTrue(defaults["presence_enabled"])
                self.assertTrue(defaults["cycle_show_reward"])
                self.assertFalse(defaults["cycle_show_difficulty"])
                self.assertFalse(defaults["cycle_show_rac"])
                self.assertFalse(defaults["cycle_show_mag"])
                self.assertFalse(defaults["cycle_show_block"])
                self.assertFalse(defaults["cycle_show_pool_share"])

                # File with all 6 stats False enforces at least one True (defaults reward to True)
                with open(tmp_settings, "w", encoding="utf-8") as f:
                    json.dump({
                        "cycle_show_reward": False,
                        "cycle_show_difficulty": False,
                        "cycle_show_rac": False,
                        "cycle_show_mag": False,
                        "cycle_show_block": False,
                        "cycle_show_pool_share": False,
                    }, f)
                enforced = load_settings()
                self.assertTrue(enforced["cycle_show_reward"])

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
            get_network_stake_weight({"netstakeweight": 10400000000.0, "netstakingGRCvalue": 130000000.0}),
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
        self.assertTrue(example_path.is_file(), ".env.example template file must exist in repository root")
        content = example_path.read_text(encoding="utf-8")
        self.assertIn("DISCORD_CLIENT_ID", content)
        self.assertIn("RPC_USER", content)
        self.assertIn("UPDATE_INTERVAL", content)


if __name__ == "__main__":
    unittest.main()
