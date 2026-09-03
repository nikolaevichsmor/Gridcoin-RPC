import unittest
from unittest.mock import MagicMock, patch
import requests

from main import (
    format_details,
    format_magnitude,
    format_reward,
    get_active_staking_coins,
    get_expected_reward,
    get_last_stake_timestamp,
    get_presence_buttons,
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
        # 1. With pending BOINC reward
        self.assertAlmostEqual(get_expected_reward({"BoincRewardPending": 1287.37}), 1297.37)
        self.assertEqual(format_reward(1297.37), "Est. Reward: 1,297.37 GRC")

        # 2. Investor mode (no pending BOINC reward -> default 10 CBR)
        self.assertEqual(get_expected_reward({"BoincRewardPending": 0.0}), 10.0)
        self.assertEqual(get_expected_reward({}), 10.0)
        self.assertEqual(get_expected_reward(None), 10.0)
        self.assertEqual(format_reward(10.0), "Est. Reward: 10.00 GRC")

    def test_magnitude_formatting(self):
        self.assertEqual(format_magnitude(142.5), "Magnitude: 142.5")
        self.assertEqual(format_magnitude(100), "Magnitude: 100")
        self.assertEqual(format_magnitude(0), "Magnitude: None")
        self.assertEqual(format_magnitude(0.0), "Magnitude: None")
        self.assertEqual(format_magnitude("0"), "Magnitude: None")
        self.assertEqual(format_magnitude(None), "Magnitude: None")

    def test_get_presence_buttons(self):
        with patch("main.GITHUB_REPO_URL", "https://github.com/nikolaevichsmor/Gridcoin-RPC"):
            with patch("main.GITHUB_BUTTON_LABEL", "GitHub"):
                buttons = get_presence_buttons()
                self.assertEqual(
                    buttons,
                    [{"label": "GitHub", "url": "https://github.com/nikolaevichsmor/Gridcoin-RPC"}],
                )

        with patch("main.GITHUB_REPO_URL", ""):
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

    def test_get_last_stake_timestamp_empty(self):
        mock_grc = MagicMock(spec=GridcoinRPC)
        mock_grc.call.return_value = []
        self.assertIsNone(get_last_stake_timestamp(mock_grc))

        mock_grc.call.side_effect = ConnectionError("Node unreachable")
        self.assertIsNone(get_last_stake_timestamp(mock_grc))

    def test_rpc_client_success(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        with patch.object(client.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"result": {"version": 50000}, "error": None}
            mock_resp.raise_for_status.return_value = None
            mock_post.return_value = mock_resp

            res = client.call("getinfo")
            self.assertEqual(res, {"version": 50000})

    def test_rpc_client_error_response(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        with patch.object(client.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"result": None, "error": {"code": -1, "message": "Method not found"}}
            mock_resp.raise_for_status.return_value = None
            mock_post.return_value = mock_resp

            with self.assertRaises(RuntimeError):
                client.call("nonexistent")

    def test_rpc_client_connection_failure(self):
        client = GridcoinRPC("127.0.0.1", 15715, "user", "pass")
        with patch.object(client.session, "post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
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


if __name__ == "__main__":
    unittest.main()
