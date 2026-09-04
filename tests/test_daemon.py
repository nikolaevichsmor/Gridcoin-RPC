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
    get_presence_buttons,
    get_executable_path,
    is_autostart_enabled,
    set_autostart,
    DiscordPresenceManager,
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

        # 2. Investor mode (no pending BOINC reward -> default 10 CBR)
        self.assertEqual(get_expected_reward({"BoincRewardPending": 0.0}), 10.0)
        self.assertEqual(get_expected_reward({}), 10.0)
        self.assertEqual(get_expected_reward(None), 10.0)
        self.assertEqual(format_reward(10.0), "Est. Reward: 10.00 GRC")

    def test_magnitude_formatting(self):
        self.assertEqual(format_magnitude(142.5), "Mag: 142.5")
        self.assertEqual(format_magnitude(100), "Mag: 100")
        self.assertEqual(format_magnitude(0), "Mag: None")
        self.assertEqual(format_magnitude(0.0), "Mag: None")
        self.assertEqual(format_magnitude("0"), "Mag: None")
        self.assertEqual(format_magnitude(None), "Mag: None")

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


if __name__ == "__main__":
    unittest.main()
