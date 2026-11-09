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
        # Prevent test instances from overwriting the real user config on disk
        self.config.save = lambda *args, **kwargs: None  # type: ignore[method-assign]
        self.widget = TrafficBox(self.config)

    def tearDown(self) -> None:
        self.widget._stop_background_tasks(save_state=False)
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

    def test_position_save_timer(self) -> None:
        """Verify moveEvent ignores unprompted moves but debounces user moves."""
        self.widget.show()
        _app.processEvents()
        # Unprompted move (e.g. compositor mapping) should NOT trigger save timer
        self.widget.move(500, 300)
        _app.processEvents()
        self.assertFalse(self.widget._save_pos_timer.isActive())

        # User-initiated move should trigger save timer
        self.widget._user_is_moving = True
        self.widget.move(600, 400)
        _app.processEvents()
        self.assertTrue(self.widget._save_pos_timer.isActive())

    def test_window_flags_skip_taskbar(self) -> None:
        """Verify window has Tool and Frameless flags to remain hidden from taskbars across OSes."""
        from PySide6.QtCore import Qt

        flags = self.widget.windowFlags()
        self.assertTrue(bool(flags & Qt.WindowType.FramelessWindowHint))
        self.assertTrue(bool(flags & Qt.WindowType.Tool))

    def test_context_menu_footer_counter_states(self) -> None:
        """Verify context menu accurately reflects active vs deactivated footer counter."""
        # 1. Active state
        self.widget.config.show_session_totals = True
        self.widget.config.footer_counter_mode = "today"
        menu_active = self.widget._build_context_menu()
        menu_titles = [a.text() for a in menu_active.actions()]
        self.assertIn("Footer-Zähler (Zeitraum)", menu_titles)
        self.assertIn("Footer-Zähler anzeigen", menu_titles)

        act_footer = next(a for a in menu_active.actions() if a.text() == "Footer-Zähler anzeigen")
        self.assertTrue(act_footer.isChecked())

        # Submenu options
        footer_sub = act_footer.menu() or next(
            a.menu() for a in menu_active.actions() if a.text() == "Footer-Zähler (Zeitraum)"
        )
        sub_actions = {a.text(): a.isChecked() for a in footer_sub.actions() if not a.isSeparator()}
        self.assertFalse(sub_actions["Ausblenden (deaktiviert)"])
        self.assertTrue(sub_actions["Heute (Online-Zähler)"])

        # 2. Deactivated state
        self.widget.config.show_session_totals = False
        menu_deact = self.widget._build_context_menu()
        menu_deact_titles = [a.text() for a in menu_deact.actions()]
        self.assertIn("Footer-Zähler (Deaktiviert)", menu_deact_titles)

        act_footer_deact = next(a for a in menu_deact.actions() if a.text() == "Footer-Zähler anzeigen")
        self.assertFalse(act_footer_deact.isChecked())

        footer_sub_deact = next(
            a.menu() for a in menu_deact.actions() if a.text() == "Footer-Zähler (Deaktiviert)"
        )
        sub_deact_actions = {
            a.text(): a.isChecked() for a in footer_sub_deact.actions() if not a.isSeparator()
        }
        self.assertTrue(sub_deact_actions["Ausblenden (deaktiviert)"])
        self.assertFalse(sub_deact_actions["Heute (Online-Zähler)"])

        # 3. Toggling via _toggle_footer_counter
        self.widget._toggle_footer_counter(True)
        self.assertTrue(self.widget.config.show_session_totals)
        self.assertFalse(self.widget.lbl_footer.isHidden())

        self.widget._toggle_footer_counter(False)
        self.assertFalse(self.widget.config.show_session_totals)
        self.assertTrue(self.widget.lbl_footer.isHidden())

    def test_visual_size_grip_present_and_visible(self) -> None:
        """Verify custom VisualSizeGrip is configured and reacts to locked_pos / compact_mode."""
        from src.ui.widget import VisualSizeGrip

        self.assertIsInstance(self.widget.size_grip, VisualSizeGrip)
        self.widget.config.locked_pos = False
        self.widget.config.compact_mode = False
        self.widget._apply_config_visuals()
        self.assertFalse(self.widget.size_grip.isHidden())

        self.widget.config.locked_pos = True
        self.widget._apply_config_visuals()
        self.assertTrue(self.widget.size_grip.isHidden())


if __name__ == "__main__":
    unittest.main()
