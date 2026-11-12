"""Unit tests for magnetic screen-edge snapping (docking) in TrafficBox."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from src.config import AppConfig
from src.ui.settings_dlg import SettingsDialog
from src.ui.widget import TrafficBox

_app = QApplication.instance() or QApplication(sys.argv)


class TestEdgeSnapping(unittest.TestCase):
    """Test magnetic screen-edge snapping and configuration integration."""

    def setUp(self) -> None:
        self.config = AppConfig()
        self.config.save = MagicMock()  # type: ignore[method-assign]
        self.widget = TrafficBox(self.config)
        self.widget.resize(400, 260)

    def tearDown(self) -> None:
        self.widget._stop_background_tasks(save_state=False)
        self.widget.deleteLater()

    def test_snap_to_all_screen_edges(self) -> None:
        """Verify _snap_position snaps to left, right, top, and bottom edges within threshold."""
        mock_screen = MagicMock()
        mock_screen.availableGeometry.return_value = QRect(0, 0, 1920, 1040)

        with patch("src.ui.widget.QApplication.screenAt", return_value=mock_screen):
            # Near top-left corner -> snaps to (0, 0)
            snapped_tl = self.widget._snap_position(QPoint(10, 12), snap_dist=14)
            self.assertEqual(snapped_tl, QPoint(0, 0))

            # Near bottom-right corner -> snaps to (1920 - 400, 1040 - 260) = (1520, 780)
            snapped_br = self.widget._snap_position(QPoint(1510, 790), snap_dist=14)
            self.assertEqual(snapped_br, QPoint(1520, 780))

            # Outside snap distance -> unchanged
            free_pos = QPoint(500, 300)
            self.assertEqual(self.widget._snap_position(free_pos, snap_dist=14), free_pos)

    def test_snap_to_secondary_monitor_offset(self) -> None:
        """Verify _snap_position respects non-zero screen origin (multi-monitor)."""
        mock_screen = MagicMock()
        mock_screen.availableGeometry.return_value = QRect(1920, 40, 1920, 1000)

        with patch("src.ui.widget.QApplication.screenAt", return_value=mock_screen):
            snapped = self.widget._snap_position(QPoint(1930, 50), snap_dist=14)
            self.assertEqual(snapped, QPoint(1920, 40))

    def test_config_default_and_sanitize(self) -> None:
        """Verify snap_to_edges defaults to True and sanitizes string/int values."""
        cfg = AppConfig()
        self.assertTrue(cfg.snap_to_edges)
        cfg.snap_to_edges = "false"  # type: ignore[assignment]
        cfg.sanitize()
        self.assertFalse(cfg.snap_to_edges)

    def test_settings_dialog_snap_edges_toggle(self) -> None:
        """Verify SettingsDialog loads and persists chk_snap_edges."""
        self.config.snap_to_edges = False
        dlg = SettingsDialog(self.config, lambda: None)
        try:
            self.assertFalse(dlg.chk_snap_edges.isChecked())
            dlg.chk_snap_edges.setChecked(True)
            dlg._apply_changes()
            self.assertTrue(self.config.snap_to_edges)
        finally:
            dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
