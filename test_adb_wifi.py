import unittest
from unittest.mock import Mock, patch

from adb_wifi import (
    ADBListener,
    BrowserPairingSession,
    TYPE_CONNECT,
    is_duplicate_mdns_instance,
    parse_adb_mdns_connect_target,
)


class FakeInfo:
    server = "phone.local."
    addresses = [bytes([192, 168, 1, 108])]

    def __init__(self, port):
        self.port = port


class AdbWifiTest(unittest.TestCase):
    def test_submit_port_replaces_stale_port(self):
        session = BrowserPairingSession("qr")

        session.submit_port("33125", "192.168.1.108")
        session.submit_port("43210", "192.168.1.108")

        self.assertEqual(
            ("192.168.1.108", "43210"),
            session.wait_for_connect_target(),
        )

    def test_wait_refreshes_until_port_arrives(self):
        session = BrowserPairingSession("qr")

        def refresh():
            session.submit_port("44401", "192.168.1.108")

        self.assertEqual(
            ("192.168.1.108", "44401"),
            session.wait_for_connect_target(
                fallback_delay_seconds=1,
                refresh=refresh,
            ),
        )

    def test_ignores_pre_pair_connect_port_then_uses_post_pair_update(self):
        session = BrowserPairingSession("qr")
        zeroconf = Mock()
        zeroconf.get_service_info.side_effect = [FakeInfo(33125), FakeInfo(43210)]
        listener = ADBListener(mode="pair-connect", browser_session=session)

        listener.add_service(zeroconf, TYPE_CONNECT, "adb")
        self.assertTrue(session.connect_target_queue.empty())

        listener.paired = True
        listener.update_service(zeroconf, TYPE_CONNECT, "adb")

        self.assertEqual(
            ("192.168.1.108", "43210"),
            session.wait_for_connect_target(),
        )

    def test_ignores_duplicate_mdns_instance(self):
        session = BrowserPairingSession("qr")
        zeroconf = Mock()
        zeroconf.get_service_info.return_value = FakeInfo(33125)
        listener = ADBListener(mode="pair-connect", browser_session=session)
        listener.paired = True

        listener.add_service(zeroconf, TYPE_CONNECT, "adb-serial (2)._adb-tls-connect._tcp.local.")

        self.assertTrue(session.connect_target_queue.empty())

    def test_parse_adb_mdns_prefers_non_duplicate_instance(self):
        output = """List of discovered mdns services
adb-10AF9Y26XS002M3-s7MtH6 (2)\t_adb-tls-connect._tcp\t192.168.1.108:33125
adb-10AF9Y26XS002M3-s7MtH6\t_adb-tls-connect._tcp\t192.168.1.108:44401
"""
        self.assertEqual(
            ("192.168.1.108", "44401"),
            parse_adb_mdns_connect_target(output, "192.168.1.108"),
        )

    def test_parse_adb_mdns_ignores_duplicate_only_output(self):
        output = "adb-serial (2)\t_adb-tls-connect._tcp\t192.168.1.108:33125\n"

        self.assertIsNone(parse_adb_mdns_connect_target(output, "192.168.1.108"))

    def test_refreshes_connect_target_from_adb_mdns(self):
        session = BrowserPairingSession("qr")
        listener = ADBListener(mode="pair-connect", browser_session=session)
        listener.paired = True
        output = "adb-serial\t_adb-tls-connect._tcp\t192.168.1.108:44401\n"

        with patch("adb_wifi.subprocess.run") as run:
            run.return_value = Mock(stdout=output, stderr="")
            listener.refresh_adb_mdns_connect_target("192.168.1.108")

        self.assertEqual(
            ("192.168.1.108", "44401"),
            session.wait_for_connect_target(),
        )

    def test_duplicate_mdns_instance_detection(self):
        self.assertTrue(is_duplicate_mdns_instance("adb-serial (2)._adb-tls-connect._tcp.local."))
        self.assertFalse(is_duplicate_mdns_instance("adb-serial._adb-tls-connect._tcp.local."))


if __name__ == "__main__":
    unittest.main()
