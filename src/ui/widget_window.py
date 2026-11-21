"""Window interaction, edge snapping, size grip, context menu, and lifecycle mixin for TrafficBox."""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QContextMenuEvent,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSizeGrip,
    QSystemTrayIcon,
    QWidget,
)

from src.autostart import sync_kwin_position_rule
from src.ui.health_dialog import InternetHealthDialog
from src.ui.settings_dlg import SettingsDialog


class VisualSizeGrip(QSizeGrip):
    """QSizeGrip with custom diagonal grip dots that remain visible across all desktop themes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("Größe anpassen (Ziehen)")

    def update_scale(self, scale: float) -> None:
        """Adjust physical grip area to match UI scaling factor."""
        sz = max(12, int(round(14.0 * scale)))
        self.setFixedSize(sz, sz)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        pen_shadow = QColor(0, 0, 0, 180)
        pen_fg = QColor(255, 255, 255, 140)
        # Classic 6-dot diagonal resize grip triangle (3 rows: 1, 2, 3 dots)
        scale = max(1.0, w / 14.0)
        base_dots = [
            (3, 3),
            (7, 3), (3, 7),
            (11, 3), (7, 7), (3, 11),
        ]
        dots = [(int(round(x * scale)), int(round(y * scale))) for x, y in base_dots]
        for dx, dy in dots:
            painter.setPen(pen_shadow)
            painter.drawPoint(w - dx + 1, h - dy + 1)
            painter.setPen(pen_fg)
            painter.drawPoint(w - dx, h - dy)
        painter.end()


class TrafficBoxWindowMixin:
    """Mixin providing window chrome painting, dragging, edge snapping, context menu, and shutdown."""

    def paintEvent(self, _event: object) -> None:
        """Draw the rounded translucent background and border of the widget."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg_color = QColor(self.config.background_color)
        alpha = int(max(20, min(100, self.config.opacity)) * 2.55)
        bg_color.setAlpha(alpha)

        border_color = QColor(self.config.border_color)
        border_color.setAlpha(min(255, alpha + 30))

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(bg_color)
        painter.setPen(QPen(border_color, 1.2))
        painter.drawRoundedRect(rect, 8.0, 8.0)

    # --- Mouse Interaction (Drag to move, Double-click for Settings, Right-click Menu) ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.config.locked_pos:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._user_is_moving = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self.config.locked_pos
        ):
            delta = (event.globalPosition().toPoint() - self._drag_start_pos).manhattanLength()
            if delta >= 3:
                self._user_is_moving = True
                app = QApplication.instance()
                if app is not None and app.platformName() == "wayland":
                    handle = self.windowHandle()
                    if handle is not None and hasattr(handle, "startSystemMove"):
                        if handle.startSystemMove():
                            self._drag_offset = None
                            event.accept()
                            return
                new_pos = event.globalPosition().toPoint() - self._drag_offset
                if self.config.snap_to_edges:
                    new_pos = self._snap_position(new_pos)
                self._last_drag_pos = new_pos
                self.move(new_pos)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def _snap_position(self, pos: QPoint, snap_dist: int = 14) -> QPoint:
        """Snap widget position magnetically to the available screen edges."""
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        center = QPoint(x + w // 2, y + h // 2)
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()

        if screen is None:
            return pos

        avail = screen.availableGeometry()
        left_edge = avail.x()
        right_edge = avail.x() + avail.width() - w
        top_edge = avail.y()
        bottom_edge = avail.y() + avail.height() - h

        candidates_x: list[tuple[int, int]] = []
        candidates_y: list[tuple[int, int]] = []

        for edge_x in (left_edge, right_edge):
            d = abs(x - edge_x)
            if d <= snap_dist:
                candidates_x.append((d, edge_x))
        for edge_y in (top_edge, bottom_edge):
            d = abs(y - edge_y)
            if d <= snap_dist:
                candidates_y.append((d, edge_y))

        if candidates_x:
            x = min(candidates_x, key=lambda item: item[0])[1]
        if candidates_y:
            y = min(candidates_y, key=lambda item: item[0])[1]
        return QPoint(x, y)

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        if not self._in_layout_transition and self.isVisible() and self._user_is_moving:
            p = event.pos()
            self.config.pos_x = p.x()
            self.config.pos_y = p.y()
            if hasattr(self, "_save_pos_timer"):
                self._save_pos_timer.start(500)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            if self._user_is_moving:
                pos = self._last_drag_pos if self._last_drag_pos is not None else self.pos()
                self.config.pos_x = pos.x()
                self.config.pos_y = pos.y()
                self._last_drag_pos = None
                if not self.config.compact_mode:
                    self.config.widget_width = self.width()
                    self.config.widget_height = self.height()
                self.config.save()
                if sys.platform == "linux":
                    sync_kwin_position_rule(self.config.pos_x, self.config.pos_y)
                self._user_is_moving = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._apply_x11_skip_taskbar()

    def _apply_x11_skip_taskbar(self) -> None:
        """Ensure _NET_WM_STATE_SKIP_TASKBAR is set on X11 / XWayland surfaces to hide from taskbars."""
        if sys.platform.startswith("linux"):
            wid = self.winId()
            if wid:
                import shutil
                import subprocess

                xprop_bin = shutil.which("xprop")
                if xprop_bin:
                    try:
                        subprocess.run(
                            [
                                xprop_bin,
                                "-id",
                                str(int(wid)),
                                "-f",
                                "_NET_WM_STATE",
                                "32a",
                                "-set",
                                "_NET_WM_STATE",
                                "_NET_WM_STATE_SKIP_TASKBAR, _NET_WM_STATE_SKIP_PAGER",
                            ],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=0.5,
                        )
                    except Exception:
                        pass

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._update_dynamic_scaling()
        if (
            not self.config.compact_mode
            and not self._in_layout_transition
            and self.isVisible()
            and self.height() >= 210
        ):
            self.config.widget_width = self.width()
            self.config.widget_height = self.height()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_settings_dialog()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = self._build_context_menu()
        menu.exec(self.mapToGlobal(event.pos()))

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)

        act_settings = QAction("Einstellungen...", self)
        act_settings.triggered.connect(self.open_settings_dialog)
        menu.addAction(act_settings)

        act_health = QAction("Internet-Diagnose && Details...", self)
        act_health.triggered.connect(self.open_health_dialog)
        menu.addAction(act_health)

        menu.addSeparator()

        # Scaling Submenu
        scale_menu = menu.addMenu("Graph-Skalierung")
        scale_group = QActionGroup(self)
        for label, mode_key in [
            ("Wurzel-Skala (Smart)", "sqrt"),
            ("Dynamisch (Auto-Peak)", "dynamic"),
            ("Fix auf Leitungskapazität", "fixed"),
        ]:
            act = QAction(label, self, checkable=True)
            act.setChecked(self.config.scale_mode == mode_key)
            act.triggered.connect(lambda _chk=False, m=mode_key: self._set_scale_mode(m))
            scale_group.addAction(act)
            scale_menu.addAction(act)

        # Footer Counter Period Submenu
        footer_menu_title = (
            "Footer-Zähler (Zeitraum)"
            if self.config.show_session_totals
            else "Footer-Zähler (Deaktiviert)"
        )
        footer_menu = menu.addMenu(footer_menu_title)
        footer_group = QActionGroup(self)

        act_f_off = QAction("Ausblenden (deaktiviert)", self, checkable=True)
        act_f_off.setChecked(not self.config.show_session_totals)
        act_f_off.triggered.connect(lambda _chk=False: self._toggle_footer_counter(False))
        footer_group.addAction(act_f_off)
        footer_menu.addAction(act_f_off)
        footer_menu.addSeparator()

        for f_label, f_key in [
            ("Heute (Online-Zähler)", "today"),
            ("Gestern (Online-Zähler)", "yesterday"),
            ("Aktuelle Woche (Online-Zähler)", "week"),
            ("Aktueller Monat (Online-Zähler)", "month"),
            ("Vormonat (Online-Zähler)", "last_month"),
            ("Seit Widget-Start (ohne Login)", "session"),
        ]:
            act_f = QAction(f_label, self, checkable=True)
            act_f.setChecked(
                self.config.show_session_totals and self.config.footer_counter_mode == f_key
            )
            act_f.triggered.connect(lambda _chk=False, k=f_key: self._set_footer_mode(k))
            footer_group.addAction(act_f)
            footer_menu.addAction(act_f)

        act_footer = QAction("Footer-Zähler anzeigen", self, checkable=True)
        act_footer.setChecked(self.config.show_session_totals)
        act_footer.triggered.connect(self._toggle_footer_counter)
        menu.addAction(act_footer)

        act_bits = QAction("Als Bit/s anzeigen (Mbit/s)", self, checkable=True)
        act_bits.setChecked(self.config.show_as_bits)
        act_bits.triggered.connect(self._toggle_bits)
        menu.addAction(act_bits)

        act_compact = QAction("Kompakt-Modus (nur Zahlen)", self, checkable=True)
        act_compact.setChecked(self.config.compact_mode)
        act_compact.triggered.connect(self._toggle_compact)
        menu.addAction(act_compact)

        act_graph_only = QAction("Nur-Graph-Modus (Zahlen ausblenden)", self, checkable=True)
        act_graph_only.setChecked(self.config.graph_only_mode)
        act_graph_only.triggered.connect(self._toggle_graph_only)
        menu.addAction(act_graph_only)

        act_top = QAction("Immer im Vordergrund", self, checkable=True)
        act_top.setChecked(self.config.always_on_top)
        act_top.triggered.connect(self._toggle_always_on_top)
        menu.addAction(act_top)

        act_lock = QAction("Position sperren", self, checkable=True)
        act_lock.setChecked(self.config.locked_pos)
        act_lock.triggered.connect(self._toggle_lock_pos)
        menu.addAction(act_lock)

        menu.addSeparator()

        act_reset_session = QAction("Zähler „Seit Widget-Start“ zurücksetzen", self)
        act_reset_session.setEnabled(self.config.show_session_totals)
        act_reset_session.triggered.connect(self._reset_session_counter)
        menu.addAction(act_reset_session)

        act_hide = QAction(
            "Widget ausblenden" if self.isVisible() else "Widget einblenden", self
        )
        act_hide.triggered.connect(self._toggle_visibility)
        menu.addAction(act_hide)

        menu.addSeparator()

        act_about = QAction("Über TrafficBox...", self)
        act_about.triggered.connect(lambda: self.open_settings_dialog(SettingsDialog.TAB_ABOUT))
        menu.addAction(act_about)

        act_quit = QAction("Beenden", self)
        act_quit.triggered.connect(self.quit_application)
        menu.addAction(act_quit)

        return menu

    def _set_scale_mode(self, mode: str) -> None:
        self.config.scale_mode = mode
        self.config.save()
        self._apply_config_visuals()

    def _set_footer_mode(self, mode: str) -> None:
        self.config.footer_counter_mode = mode
        self.config.show_session_totals = True
        self.config.save()
        self._apply_config_visuals()
        if self._last_sample:
            self._on_sample_received(self._last_sample)

    def _toggle_footer_counter(self, checked: bool) -> None:
        self.config.show_session_totals = checked
        self.config.save()
        self._apply_config_visuals()
        if self._last_sample:
            self._on_sample_received(self._last_sample)

    def _toggle_bits(self, checked: bool) -> None:
        self.config.show_as_bits = checked
        self.config.save()
        self._on_sample_received(self._last_sample)

    def _toggle_compact(self, checked: bool) -> None:
        self.config.compact_mode = checked
        if checked:
            self.config.graph_only_mode = False
        self.config.save()
        self._apply_config_visuals()

    def _toggle_graph_only(self, checked: bool) -> None:
        self.config.graph_only_mode = checked
        if checked:
            self.config.compact_mode = False
        self.config.save()
        self._apply_config_visuals()

    def _toggle_always_on_top(self, checked: bool) -> None:
        self.config.always_on_top = checked
        self.config.save()
        self._apply_config_visuals()

    def _toggle_lock_pos(self, checked: bool) -> None:
        self.config.locked_pos = checked
        self.config.save()
        self._apply_config_visuals()

    def _reset_session_counter(self) -> None:
        self.request_reset_session.emit()
        self.request_poll.emit()

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._toggle_visibility()

    def open_settings_dialog(self, initial_tab: int = 0) -> None:
        """Open or focus the Settings dialog, optionally switching to a specific tab."""
        tab_idx = (
            initial_tab
            if isinstance(initial_tab, int) and not isinstance(initial_tab, bool)
            else 0
        )
        if self._settings_dlg is not None and self._settings_dlg.isVisible():
            if 0 <= tab_idx < self._settings_dlg.tabs.count():
                self._settings_dlg.tabs.setCurrentIndex(tab_idx)
            self._settings_dlg.raise_()
            self._settings_dlg.activateWindow()
            return

        self._settings_dlg = SettingsDialog(
            self.config,
            on_apply=self._on_settings_applied,
            parent=None,
            initial_tab=tab_idx,
        )
        self._settings_dlg.show()
        self._settings_dlg.raise_()
        self._settings_dlg.activateWindow()

    def open_health_dialog(self, initial_tab: int = 0) -> None:
        """Open or focus the Internet Health diagnosis & tips dialog."""
        tab_idx = (
            initial_tab
            if isinstance(initial_tab, int) and not isinstance(initial_tab, bool)
            else 0
        )
        down_pct = getattr(self, "_last_down_pct", 0.0)
        up_pct = getattr(self, "_last_up_pct", 0.0)

        if self._health_dlg is not None and self._health_dlg.isVisible():
            if 0 <= tab_idx < self._health_dlg.tabs.count():
                self._health_dlg.tabs.setCurrentIndex(tab_idx)
            self._health_dlg.update_from_sample(self._last_sample, down_pct, up_pct)
            self._health_dlg.raise_()
            self._health_dlg.activateWindow()
            return

        self._health_dlg = InternetHealthDialog(
            self.config,
            on_recheck=self.request_health_probe.emit,
            on_open_settings=lambda: self.open_settings_dialog(SettingsDialog.TAB_NETWORK),
            parent=None,
            initial_tab=tab_idx,
        )
        self._health_dlg.update_from_sample(self._last_sample, down_pct, up_pct)
        self._health_dlg.show()
        self._health_dlg.raise_()
        self._health_dlg.activateWindow()

    def _on_settings_applied(self) -> None:
        self._apply_config_visuals()
        self.request_reload_credentials.emit()
        self.request_poll.emit()

    def _stop_background_tasks(self, save_state: bool = True) -> None:
        """Immediately halt polling timer and worker thread (safe to call multiple times)."""
        if self._is_quitting:
            return
        self._is_quitting = True
        self._save_pos_timer.stop()
        self._poll_timer.stop()
        self._worker.stop()

        for dlg_attr in ("_settings_dlg", "_health_dlg"):
            dlg = getattr(self, dlg_attr, None)
            if dlg is not None:
                try:
                    dlg.close()
                except Exception:
                    pass

        if save_state:
            self.config.pos_x = self.x()
            self.config.pos_y = self.y()
            if not self.config.compact_mode:
                self.config.widget_width = self.width()
                self.config.widget_height = self.height()
            self.config.save()
            if sys.platform == "linux":
                sync_kwin_position_rule(self.config.pos_x, self.config.pos_y)

        if self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(1200)
        self.tray_icon.hide()

    def _on_commit_data_request(self, _manager: object) -> None:
        """Stop background polling immediately when Windows/Linux session shuts down."""
        self._stop_background_tasks(save_state=True)

    def _on_app_about_to_quit(self) -> None:
        """Ensure worker thread is stopped when QApplication exits."""
        self._stop_background_tasks(save_state=True)

    def quit_application(self) -> None:
        """Cleanly stop worker thread, save position, and exit."""
        self._stop_background_tasks(save_state=True)
        QApplication.quit()
