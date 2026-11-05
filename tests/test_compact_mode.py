"""Unit tests for TrafficBox compact mode and layout sizing."""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.api.models import TrafficSample
from src.config import AppConfig
from src.ui.widget import TrafficBox

_app = QApplication.instance() or QApplication(sys.argv)


class TestCompactMode(unittest.TestCase):
    """Test compact mode geometry, element hierarchy and overlap prevention."""

    def setUp(self) -> None:
        self.config = AppConfig()
        self.config.compact_mode = False
        self.config.show_wan_status_pill = True
        self.config.enable_dns_monitor = True
        self.widget = TrafficBox(self.config)

    def tearDown(self) -> None:
        if hasattr(self.widget, "_worker_thread") and self.widget._worker_thread.isRunning():
            self.widget._worker_thread.quit()
            self.widget._worker_thread.wait(500)
        self.widget.deleteLater()

    def test_compact_mode_height_calculation(self) -> None:
        """Verify _get_compact_height accommodates minimum size hints without truncation."""
        self.widget._toggle_compact(True)
        base_h = self.widget._get_compact_height()
        self.assertGreaterEqual(base_h, 120)

        # Enabling local traffic header increases height
        self.config.enable_local_traffic_monitor = True
        self.config.show_local_traffic_in_header = True
        pc_h = self.widget._get_compact_height()
        self.assertGreater(pc_h, base_h)

    def test_compact_mode_toggle_prevents_overlap(self) -> None:
        """Verify no vertical overlap between header, rate labels, progress bars, and footer."""
        sample = TrafficSample(
            is_connected=True,
            wan_connected=True,
            download_bps=910000,
            upload_bps=1530000,
            max_download_bps=100000000,
            max_upload_bps=40000000,
            dns_ms=5.1,
            active_dns_ip="192.168.178.1",
        )
        self.widget._on_sample_received(sample)
        self.widget.show()
        _app.processEvents()

        # Switch to compact mode
        self.widget._toggle_compact(True)
        _app.processEvents()

        self.assertTrue(self.widget.config.compact_mode)
        self.assertFalse(self.widget.center_stack.isVisible())

        # Check vertical coordinates
        hdr_bottom = self.widget.lbl_down_header.mapTo(
            self.widget, self.widget.lbl_down_header.rect().bottomLeft()
        ).y()
        rate_top = self.widget.lbl_down_rate.mapTo(
            self.widget, self.widget.lbl_down_rate.rect().topLeft()
        ).y()
        rate_bottom = self.widget.lbl_down_rate.mapTo(
            self.widget, self.widget.lbl_down_rate.rect().bottomLeft()
        ).y()
        bar_top = self.widget.bar_down_util.mapTo(
            self.widget, self.widget.bar_down_util.rect().topLeft()
        ).y()
        bar_bottom = self.widget.bar_down_util.mapTo(
            self.widget, self.widget.bar_down_util.rect().bottomLeft()
        ).y()
        meta_top = self.widget.lbl_down_meta.mapTo(
            self.widget, self.widget.lbl_down_meta.rect().topLeft()
        ).y()
        meta_bottom = self.widget.lbl_down_meta.mapTo(
            self.widget, self.widget.lbl_down_meta.rect().bottomLeft()
        ).y()
        pill_top = self.widget.lbl_wan_pill.mapTo(
            self.widget, self.widget.lbl_wan_pill.rect().topLeft()
        ).y()

        self.assertLessEqual(hdr_bottom, rate_top)
        self.assertLessEqual(rate_bottom, bar_top)
        self.assertLessEqual(bar_bottom, meta_top)
        self.assertLessEqual(meta_bottom, pill_top)

    def test_graph_only_mode_toggle(self) -> None:
        """Verify graph-only mode hides rates container while keeping center graph visible."""
        self.widget.show()
        _app.processEvents()

        # Initially both are visible
        self.assertTrue(self.widget.rates_container.isVisible())
        self.assertTrue(self.widget.center_stack.isVisible())

        # Enable graph-only mode
        self.widget._toggle_graph_only(True)
        _app.processEvents()

        self.assertTrue(self.widget.config.graph_only_mode)
        self.assertFalse(self.widget.config.compact_mode)
        self.assertFalse(self.widget.rates_container.isVisible())
        self.assertTrue(self.widget.center_stack.isVisible())

        # Toggling compact mode turns off graph_only mode
        self.widget._toggle_compact(True)
        _app.processEvents()
        self.assertTrue(self.widget.config.compact_mode)
        self.assertFalse(self.widget.config.graph_only_mode)
        self.assertTrue(self.widget.rates_container.isVisible())
        self.assertFalse(self.widget.center_stack.isVisible())

        # Toggling graph_only turns off compact mode
        self.widget._toggle_graph_only(True)
        _app.processEvents()
        self.assertTrue(self.widget.config.graph_only_mode)
        self.assertFalse(self.widget.config.compact_mode)
        self.assertFalse(self.widget.rates_container.isVisible())
        self.assertTrue(self.widget.center_stack.isVisible())


if __name__ == "__main__":
    unittest.main()
