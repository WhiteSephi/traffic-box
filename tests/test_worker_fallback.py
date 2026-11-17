"""Unit tests for PollingWorker local traffic fallback when no Fritz!Box is reachable."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import unittest

from src.api.models import TrafficSample
from src.api.worker import PollingWorker
from src.config import AppConfig


class TestWorkerLocalFallback(unittest.TestCase):
    """Test automatic fallback to local adapter traffic when no Fritz!Box is reachable."""

    def _make_worker(self, enable_fallback: bool = True) -> PollingWorker:
        config = AppConfig(
            enable_local_fallback=enable_fallback,
            enable_ping_graph=False,
            enable_dns_monitor=False,
        )
        worker = PollingWorker(config)
        worker.net_health.tick = MagicMock(return_value=(None, 0.0, "", None))
        return worker

    def test_fallback_activates_when_box_unreachable(self) -> None:
        """When box_reachable=False and fallback enabled, local adapter traffic is used."""
        worker = self._make_worker(enable_fallback=True)
        worker.upnp.fetch_sample = MagicMock(
            return_value=TrafficSample(box_reachable=False, is_connected=False)
        )
        worker.local_traffic.fetch_rates_bps = MagicMock(return_value=(125_000.0, 25_000.0, True))
        worker.local_traffic._session_rx = 500_000
        worker.local_traffic._session_tx = 100_000

        samples: list[TrafficSample] = []
        worker.sample_ready.connect(samples.append)

        with patch("src.api.worker.time.monotonic", return_value=100.0):
            worker.poll_once()

        self.assertEqual(len(samples), 1)
        s = samples[0]
        self.assertFalse(s.box_reachable)
        self.assertTrue(s.is_local_fallback)
        self.assertTrue(s.is_connected)
        self.assertEqual(s.download_bps, 125_000.0)
        self.assertEqual(s.upload_bps, 25_000.0)
        self.assertEqual(s.session_bytes_received, 500_000)
        self.assertEqual(s.session_bytes_sent, 100_000)

    def test_fallback_disabled_keeps_offline(self) -> None:
        """When enable_local_fallback=False, unreachable box stays offline."""
        worker = self._make_worker(enable_fallback=False)
        worker.upnp.fetch_sample = MagicMock(
            return_value=TrafficSample(box_reachable=False, is_connected=False)
        )
        worker.local_traffic.fetch_rates_bps = MagicMock(return_value=(125_000.0, 25_000.0, True))

        samples: list[TrafficSample] = []
        worker.sample_ready.connect(samples.append)

        with patch("src.api.worker.time.monotonic", return_value=100.0):
            worker.poll_once()

        self.assertEqual(len(samples), 1)
        s = samples[0]
        self.assertFalse(s.box_reachable)
        self.assertFalse(s.is_local_fallback)
        self.assertFalse(s.is_connected)
        worker.local_traffic.fetch_rates_bps.assert_not_called()

    def test_upnp_cooldown_and_recovery(self) -> None:
        """UPnP is not re-probed during cooldown, and recovers once box is reachable again."""
        worker = self._make_worker(enable_fallback=True)
        worker.upnp.fetch_sample = MagicMock(
            return_value=TrafficSample(box_reachable=False, is_connected=False)
        )
        worker.local_traffic.fetch_rates_bps = MagicMock(return_value=(1000.0, 500.0, True))

        samples: list[TrafficSample] = []
        worker.sample_ready.connect(samples.append)

        # Tick 1 at t=100s: probes UPnP -> fails -> enters fallback
        with patch("src.api.worker.time.monotonic", return_value=100.0):
            worker.poll_once()
        self.assertEqual(worker.upnp.fetch_sample.call_count, 1)

        # Tick 2 at t=102s (within 10s cooldown): skips UPnP, still uses local fallback
        with patch("src.api.worker.time.monotonic", return_value=102.0):
            worker.poll_once()
        self.assertEqual(worker.upnp.fetch_sample.call_count, 1)
        self.assertTrue(samples[-1].is_local_fallback)

        # Tick 3 at t=111s (cooldown expired): probes UPnP -> box is back!
        worker.upnp.fetch_sample.return_value = TrafficSample(
            box_reachable=True, is_connected=True, download_bps=9999.0, upload_bps=3333.0
        )
        with patch("src.api.worker.time.monotonic", return_value=111.0):
            worker.poll_once()
        self.assertEqual(worker.upnp.fetch_sample.call_count, 2)
        self.assertTrue(samples[-1].box_reachable)
        self.assertFalse(samples[-1].is_local_fallback)
        self.assertEqual(samples[-1].download_bps, 9999.0)

    def test_reset_session_resets_local_counters(self) -> None:
        """reset_session() resets both UPnP and local traffic session counters."""
        worker = self._make_worker(enable_fallback=True)
        worker.upnp.reset_session_counters = MagicMock()
        worker.local_traffic._session_rx = 12345
        worker.local_traffic._session_tx = 6789

        worker.reset_session()

        worker.upnp.reset_session_counters.assert_called_once()
        self.assertEqual(worker.local_traffic.session_bytes_received, 0)
        self.assertEqual(worker.local_traffic.session_bytes_sent, 0)


if __name__ == "__main__":
    unittest.main()
