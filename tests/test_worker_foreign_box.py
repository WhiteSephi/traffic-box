"""Unit tests for PollingWorker foreign box protection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import unittest

from src.api.models import TrafficSample
from src.api.worker import PollingWorker
from src.config import AppConfig


class TestWorkerForeignBox(unittest.TestCase):
    """Test protection against login attempts on foreign Fritz!Boxes."""

    def test_foreign_box_skips_login(self) -> None:
        """When current box UDN != bound_box_udn, login must be skipped."""
        config = AppConfig(
            fritz_password="secret_password",
            enable_guest_monitor=True,
            bound_box_udn="uuid:home-box-1234",
            bound_box_name="Home Fritz!Box",
        )
        worker = PollingWorker(config)

        # Mock sample returned from UPnP showing a DIFFERENT box (foreign office/friend box)
        mock_sample = TrafficSample(
            is_connected=True,
            box_udn="uuid:foreign-box-9999",
            box_name="Office Fritz!Box",
        )
        worker.upnp.fetch_sample = MagicMock(return_value=mock_sample)
        worker.guest_client.fetch_guest_rates_bps = MagicMock()
        worker.guest_client.fetch_online_counters = MagicMock()

        received_samples: list[TrafficSample] = []
        worker.sample_ready.connect(received_samples.append)

        worker.poll_once()

        self.assertEqual(len(received_samples), 1)
        sample = received_samples[0]
        # Must flag as foreign box
        self.assertTrue(sample.is_foreign_box)
        # guest_client must NEVER be called with the home password on foreign box
        worker.guest_client.fetch_guest_rates_bps.assert_not_called()
        worker.guest_client.fetch_online_counters.assert_not_called()

    def test_matching_box_allows_login(self) -> None:
        """When current box UDN == bound_box_udn, login proceeds normally."""
        config = AppConfig(
            fritz_password="secret_password",
            enable_guest_monitor=True,
            bound_box_udn="uuid:home-box-1234",
            bound_box_name="Home Fritz!Box",
        )
        worker = PollingWorker(config)

        mock_sample = TrafficSample(
            is_connected=True,
            box_udn="uuid:home-box-1234",
            box_name="Home Fritz!Box",
        )
        worker.upnp.fetch_sample = MagicMock(return_value=mock_sample)
        worker.guest_client.fetch_guest_rates_bps = MagicMock(return_value=(1000.0, 500.0, True))
        worker.guest_client.fetch_online_counters = MagicMock(return_value=MagicMock(is_available=True))

        received_samples: list[TrafficSample] = []
        worker.sample_ready.connect(received_samples.append)

        worker.poll_once()

        self.assertEqual(len(received_samples), 1)
        sample = received_samples[0]
        self.assertFalse(sample.is_foreign_box)
        # guest_client was called
        worker.guest_client.fetch_guest_rates_bps.assert_called_once()


if __name__ == "__main__":
    unittest.main()
