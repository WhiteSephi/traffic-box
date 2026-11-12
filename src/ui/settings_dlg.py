"""Settings dialog for configuring the TrafficBox Widget."""

from __future__ import annotations

import platform
import sys
from typing import Callable
import urllib.request

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, qVersion
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QHideEvent,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src import __version__
from src.api.fritz_monitor import FritzGuestMonitorClient
from src.api.upnp_client import FritzUpnpClient
from src.autostart import is_autostart_enabled, set_autostart
from src.config import AppConfig, get_config_dir
from src.ui.tray import create_router_icon


def make_swatch_icon(hex_color: str, size: int = 16) -> QIcon:
    """Generate a clean rounded color chip icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(hex_color))
    painter.setPen(QColor("#FFFFFF" if QColor(hex_color).lightness() < 60 else "#222222"))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 4, 4)
    painter.end()
    return QIcon(pix)


class ModernColorPickerPopup(QDialog):
    """Modern dark-themed color picker popup with curated palette and hex input."""

    PALETTE = [
        ["#00E5FF", "#00E676", "#FFEA00", "#FF9100", "#FF1744", "#FF007F"],
        ["#3D5AFE", "#7C4DFF", "#00B0FF", "#1DE9B6", "#76FF03", "#FFD600"],
        ["#80D8FF", "#A7FFEB", "#CCFF90", "#FFE57F", "#FF8A80", "#EA80FC"],
        ["#FFFFFF", "#CFD8DC", "#78909C", "#455A64", "#263238", "#121212"],
    ]

    def __init__(
        self,
        current_hex: str,
        on_chosen: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.on_chosen = on_chosen

        self.setStyleSheet("""
            QDialog {
                background-color: #1A1E24;
                border: 1px solid #3E4652;
                border-radius: 8px;
            }
            QLabel {
                color: #E0E4E8;
                font-size: 8.5pt;
            }
            QLineEdit {
                background-color: #262C36;
                color: #FFFFFF;
                border: 1px solid #444D5A;
                border-radius: 4px;
                padding: 4px 6px;
                font-family: monospace;
                font-weight: bold;
                font-size: 8.5pt;
            }
            QLineEdit:focus {
                border-color: #00E5FF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        lbl_title = QLabel("Farbe wählen")
        lbl_title.setStyleSheet("font-weight: bold; font-size: 9pt; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        # Palette Grid
        grid = QGridLayout()
        grid.setSpacing(5)
        for r, row in enumerate(self.PALETTE):
            for c, hex_code in enumerate(row):
                btn = QPushButton()
                btn.setFixedSize(26, 26)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setToolTip(hex_code)
                is_curr = hex_code.lower() == current_hex.lower()
                border = "2px solid #FFFFFF" if is_curr else "1px solid rgba(255,255,255,0.2)"
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {hex_code};
                        border: {border};
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        border: 2px solid #00E5FF;
                    }}
                """)
                btn.clicked.connect(lambda _, h=hex_code: self._select_and_close(h))
                grid.addWidget(btn, r, c)
        layout.addLayout(grid)

        # Hex Input Row with live preview swatch
        hex_row = QHBoxLayout()
        hex_row.setSpacing(6)
        lbl_hex = QLabel("Hex:")
        self.txt_hex = QLineEdit(current_hex)
        self.txt_hex.setMaxLength(9)

        self.lbl_swatch_preview = QLabel()
        self.lbl_swatch_preview.setFixedSize(22, 22)
        self._update_preview_swatch(current_hex)

        self.txt_hex.textChanged.connect(self._on_hex_text_changed)
        self.txt_hex.returnPressed.connect(lambda: self._select_and_close(self.txt_hex.text()))

        btn_ok = QPushButton("✓")
        btn_ok.setFixedSize(26, 26)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #2D3748;
                color: #00E5FF;
                border: 1px solid #4A5568;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3A475C;
                border-color: #00E5FF;
            }
        """)
        btn_ok.clicked.connect(lambda: self._select_and_close(self.txt_hex.text()))

        hex_row.addWidget(lbl_hex)
        hex_row.addWidget(self.lbl_swatch_preview)
        hex_row.addWidget(self.txt_hex, 1)
        hex_row.addWidget(btn_ok)
        layout.addLayout(hex_row)

        # System Color Dialog fallback
        btn_sys = QPushButton("🎨 Erweiterte Farbauswahl…")
        btn_sys.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_sys.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #8E9297;
                font-size: 8pt;
                text-decoration: underline;
                padding-top: 2px;
            }
            QPushButton:hover {
                color: #00E5FF;
            }
        """)
        btn_sys.clicked.connect(self._open_system_picker)
        layout.addWidget(btn_sys)

    def _update_preview_swatch(self, hex_code: str) -> None:
        if not hex_code.startswith("#"):
            hex_code = "#" + hex_code
        col = QColor(hex_code)
        if col.isValid():
            self.lbl_swatch_preview.setStyleSheet(
                f"background-color: {col.name()}; border: 1px solid #666; border-radius: 3px;"
            )

    def _on_hex_text_changed(self, text: str) -> None:
        self._update_preview_swatch(text.strip())

    def _select_and_close(self, hex_val: str) -> None:
        hex_val = hex_val.strip()
        if not hex_val.startswith("#"):
            hex_val = "#" + hex_val
        col = QColor(hex_val)
        if col.isValid():
            self.on_chosen(col.name().upper())
            self.close()

    def _open_system_picker(self) -> None:
        init_col = QColor(self.txt_hex.text().strip())
        if not init_col.isValid():
            init_col = QColor("#FFEA00")
        chosen = QColorDialog.getColor(init_col, self, "Erweiterte Farbe wählen")
        if chosen.isValid():
            self.on_chosen(chosen.name().upper())
            self.close()


class ColorButton(QPushButton):
    """Button that displays a modern color swatch and opens the dark popover."""

    def __init__(self, hex_color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = hex_color.upper() if hex_color.startswith("#") else f"#{hex_color.upper()}"
        self.setFixedHeight(28)
        self.setMinimumWidth(110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self.clicked.connect(self._open_picker)

    @property
    def hex_color(self) -> str:
        return self._color

    @hex_color.setter
    def hex_color(self, value: str) -> None:
        if not value.startswith("#"):
            value = "#" + value
        if QColor(value).isValid():
            self._color = value.upper()
            self._update_style()

    def _update_style(self) -> None:
        self.setIcon(make_swatch_icon(self._color, 16))
        self.setText(f" {self._color}")
        self.setStyleSheet("""
            QPushButton {
                background-color: #20262E;
                color: #E0E4E8;
                border: 1px solid #3E4652;
                border-radius: 5px;
                padding-left: 8px;
                padding-right: 8px;
                font-family: monospace;
                font-weight: bold;
                font-size: 8.5pt;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #272E38;
                border-color: #00E5FF;
            }
        """)

    def _open_picker(self) -> None:
        popup = ModernColorPickerPopup(self._color, self._set_color, parent=self)
        pos = self.mapToGlobal(QPoint(0, self.height() + 2))
        popup.move(pos)
        popup.show()

    def _set_color(self, new_color: str) -> None:
        self.hex_color = new_color


THEMES: dict[str, dict[str, str]] = {
    "TrafficBox Standard (Gelb & Blau)": {
        "down": "#FFEA00",
        "up": "#4A5CFF",
        "guest_down": "#00E676",
        "guest_up": "#FF9100",
        "ping": "#00E5FF",
        "jitter": "#FF9100",
        "bg": "#1C2428",
        "border": "#5E616C",
        "grid": "#32383D",
        "title": "#E0E4E8",
    },
    "Cyberpunk Neon (Cyan & Pink)": {
        "down": "#00E5FF",
        "up": "#FF007F",
        "guest_down": "#00E676",
        "guest_up": "#FF9100",
        "ping": "#D500F9",
        "jitter": "#FFD600",
        "bg": "#0D1117",
        "border": "#00E5FF",
        "grid": "#21262D",
        "title": "#58A6FF",
    },
    "FRITZ!Box Classic (AVM Rot & Blau)": {
        "down": "#E0001B",
        "up": "#0066CC",
        "guest_down": "#28A745",
        "guest_up": "#FD7E14",
        "ping": "#17A2B8",
        "jitter": "#FFC107",
        "bg": "#1F2326",
        "border": "#495057",
        "grid": "#343A40",
        "title": "#F8F9FA",
    },
    "Emerald Matrix (Giftgrün & Minze)": {
        "down": "#00E676",
        "up": "#00B0FF",
        "guest_down": "#76FF03",
        "guest_up": "#1DE9B6",
        "ping": "#69F0AE",
        "jitter": "#FFD600",
        "bg": "#0A140F",
        "border": "#1B4D3E",
        "grid": "#132E25",
        "title": "#E8F5E9",
    },
    "Minimalist Monochrome (Weiß & Grau)": {
        "down": "#FFFFFF",
        "up": "#90CAF9",
        "guest_down": "#B0BEC5",
        "guest_up": "#78909C",
        "ping": "#80D8FF",
        "jitter": "#CFD8DC",
        "bg": "#121212",
        "border": "#37474F",
        "grid": "#263238",
        "title": "#ECEFF1",
    },
}


class SettingsDialog(QDialog):
    """Comprehensive settings window for TrafficBox with modern tabs."""

    GITHUB_REPO_URL = "https://github.com/WhiteSephi/traffic-box"
    GITHUB_RELEASES_URL = "https://github.com/WhiteSephi/traffic-box/releases"
    GITHUB_ISSUES_URL = "https://github.com/WhiteSephi/traffic-box/issues"

    def __init__(
        self,
        config: AppConfig,
        on_apply: Callable[[], None],
        parent: QWidget | None = None,
        initial_tab: int = 0,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.on_apply = on_apply

        self.setWindowTitle("TrafficBox Einstellungen")
        self.setMinimumSize(600, 480)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self._build_ui()
        self._restore_geometry()
        self._load_from_config()
        if 0 <= initial_tab < self.tabs.count():
            self.tabs.setCurrentIndex(initial_tab)

    def _restore_geometry(self) -> None:
        """Restore window position and size from config if valid on current screens."""
        cfg_w = max(600, self.config.settings_width)
        cfg_h = max(480, self.config.settings_height)
        self.resize(cfg_w, cfg_h)

        if self.config.settings_pos_x >= 0 and self.config.settings_pos_y >= 0:
            target_pt = QPoint(self.config.settings_pos_x, self.config.settings_pos_y)
            target_rect = QRect(target_pt, QSize(cfg_w, cfg_h))
            for screen in QApplication.screens():
                if screen.availableGeometry().intersects(target_rect):
                    self.move(target_pt)
                    return

        primary = QApplication.primaryScreen()
        if primary:
            avail = primary.availableGeometry()
            x = avail.x() + max(0, (avail.width() - cfg_w) // 2)
            y = avail.y() + max(0, (avail.height() - cfg_h) // 2)
            self.move(x, y)

    def _save_geometry_to_config(self) -> None:
        """Store current window geometry in config."""
        self.config.settings_pos_x = self.x()
        self.config.settings_pos_y = self.y()
        self.config.settings_width = self.width()
        self.config.settings_height = self.height()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry_to_config()
        self.config.save()
        super().closeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._save_geometry_to_config()
        super().hideEvent(event)

    def accept(self) -> None:
        self._save_geometry_to_config()
        self.config.save()
        super().accept()

    def reject(self) -> None:
        self._save_geometry_to_config()
        self.config.save()
        super().reject()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        root_layout.addWidget(self.tabs)

        # =========================================================================
        # TAB 1: FRITZ!Box (Verbindung & Login)
        # =========================================================================
        tab_fritz = QWidget()
        fritz_layout = QVBoxLayout(tab_fritz)
        fritz_layout.setContentsMargins(8, 8, 8, 8)
        fritz_layout.setSpacing(8)

        # Verbindungsparameter
        conn_group = QGroupBox("Verbindungsparameter (UPnP)")
        conn_form = QFormLayout(conn_group)
        conn_form.setContentsMargins(10, 10, 10, 10)
        conn_form.setVerticalSpacing(6)

        self.txt_host = QLineEdit()
        self.txt_host.setPlaceholderText("z. B. fritz.box oder 192.168.178.1")
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_refresh = QSpinBox()
        self.spin_refresh.setRange(1, 60)
        self.spin_refresh.setSuffix(" Sek.")

        conn_form.addRow("Fritz!Box Name/IP:", self.txt_host)

        row_nums = QHBoxLayout()
        row_nums.addWidget(QLabel("UPnP Port:"))
        row_nums.addWidget(self.spin_port)
        row_nums.addSpacing(16)
        row_nums.addWidget(QLabel("Aktualisierung:"))
        row_nums.addWidget(self.spin_refresh)
        row_nums.addStretch(1)
        conn_form.addRow(row_nums)
        fritz_layout.addWidget(conn_group)

        # Fritz!OS Login
        login_group = QGroupBox("Fritz!OS Login (für Online-Zähler && Gäste-WLAN)")
        login_form = QFormLayout(login_group)
        login_form.setContentsMargins(10, 10, 10, 10)
        login_form.setVerticalSpacing(6)

        self.chk_guest = QCheckBox("Fritz!OS Login aktivieren")
        self.chk_guest.toggled.connect(self._on_guest_toggled)
        self.txt_user = QLineEdit()
        self.txt_user.setPlaceholderText("Optional (leer lassen für Standard-Benutzer)")
        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pass.setPlaceholderText("Fritz!Box Passwort")

        self.lbl_bound_box = QLabel("")
        self.lbl_bound_box.setWordWrap(True)
        self.lbl_bound_box.setStyleSheet("color: #8E9297; font-size: 8.5pt;")

        self.btn_test_conn = QPushButton(" Verbindung && Login testen")
        self.btn_test_conn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_conn.clicked.connect(self._on_test_connection)
        self.lbl_test_result = QLabel("")
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setVisible(False)

        box_label_row = QHBoxLayout()
        lbl_box_title = QLabel("Heim-Router Bindung:")
        lbl_box_title.setStyleSheet("font-weight: bold; color: #E0E4E8; font-size: 8.5pt;")
        tooltip_binding = (
            "Schützt dein Passwort: Das Widget sendet Zugangsdaten ausschließlich an deinen "
            "persönlichen Heim-Router. In fremden WLAN-Netzen (z. B. Büro, Hotel) wird der Login "
            "automatisch blockiert."
        )
        lbl_box_title.setToolTip(tooltip_binding)
        self.lbl_bound_box.setToolTip(tooltip_binding)
        box_label_row.addWidget(lbl_box_title)
        box_label_row.addWidget(self.lbl_bound_box, 1)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_test_conn)
        btn_row.addStretch(1)

        login_form.addRow(self.chk_guest)
        login_form.addRow("Fritz!Box Benutzer:", self.txt_user)
        login_form.addRow("Fritz!Box Passwort:", self.txt_pass)
        login_form.addRow(box_label_row)
        login_form.addRow(btn_row)
        login_form.addRow(self.lbl_test_result)
        fritz_layout.addWidget(login_group)
        fritz_layout.addStretch(1)

        self.tabs.addTab(self._wrap_in_scroll(tab_fritz), "FRITZ!Box")

        # =========================================================================
        # TAB 2: Allgemein (Systemstart, Fenster & Verhalten)
        # =========================================================================
        tab_general = QWidget()
        gen_layout = QVBoxLayout(tab_general)
        gen_layout.setContentsMargins(8, 8, 8, 8)
        gen_layout.setSpacing(8)

        # Systemstart & Autostart
        sys_group = QGroupBox("Systemstart && Autostart")
        sys_form = QFormLayout(sys_group)
        sys_form.setContentsMargins(10, 10, 10, 10)
        sys_form.setVerticalSpacing(6)

        self.chk_autostart = QCheckBox("Autostart mit dem Betriebssystem aktivieren")
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 120)
        self.spin_delay.setSuffix(" Sek.")
        self.spin_delay.setToolTip("Wartezeit nach dem Systemstart vor dem ersten Verbindungsversuch")

        sys_form.addRow(self.chk_autostart)
        sys_form.addRow("Startverzögerung beim Booten:", self.spin_delay)
        gen_layout.addWidget(sys_group)

        # Fenster & Position
        win_group = QGroupBox("Fenster-Verhalten && Position")
        win_form = QFormLayout(win_group)
        win_form.setContentsMargins(10, 10, 10, 10)
        win_form.setVerticalSpacing(6)

        self.chk_always_on_top = QCheckBox("Immer im Vordergrund (Always on Top)")
        self.chk_locked_pos = QCheckBox("Position auf dem Desktop sperren (LockedPos)")

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Deckkraft (Opacity):"))
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(25, 100)
        self.lbl_opacity_val = QLabel("85%")
        self.slider_opacity.valueChanged.connect(
            lambda v: self.lbl_opacity_val.setText(f"{v}%")
        )
        opacity_row.addWidget(self.slider_opacity, 1)
        opacity_row.addWidget(self.lbl_opacity_val)

        win_form.addRow(self.chk_always_on_top)
        win_form.addRow(self.chk_locked_pos)
        win_form.addRow(opacity_row)
        gen_layout.addWidget(win_group)
        gen_layout.addStretch(1)

        self.tabs.addTab(self._wrap_in_scroll(tab_general), "Allgemein")

        # =========================================================================
        # TAB 3: Anzeige (Skalierung, Graphen & Raten-Darstellung)
        # =========================================================================
        tab_display = QWidget()
        disp_layout = QVBoxLayout(tab_display)
        disp_layout.setContentsMargins(8, 8, 8, 8)
        disp_layout.setSpacing(8)

        # Benutzeroberflächen-Skalierung
        ui_scale_group = QGroupBox("Benutzeroberflächen-Skalierung (HiDPI / Kleine Displays)")
        ui_scale_form = QFormLayout(ui_scale_group)
        ui_scale_form.setContentsMargins(10, 10, 10, 10)
        ui_scale_form.setVerticalSpacing(6)

        scale_row = QHBoxLayout()
        self.slider_ui_scale = QSlider(Qt.Orientation.Horizontal)
        self.slider_ui_scale.setRange(70, 300)
        self.slider_ui_scale.setSingleStep(5)
        self.slider_ui_scale.setPageStep(25)
        self.slider_ui_scale.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_ui_scale.setTickInterval(25)

        self.spin_ui_scale = QSpinBox()
        self.spin_ui_scale.setRange(70, 300)
        self.spin_ui_scale.setSingleStep(5)
        self.spin_ui_scale.setSuffix(" %")

        self.slider_ui_scale.valueChanged.connect(self.spin_ui_scale.setValue)
        self.spin_ui_scale.valueChanged.connect(self.slider_ui_scale.setValue)

        btn_scale_100 = QPushButton("100 % (Standard)")
        btn_scale_100.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_scale_100.clicked.connect(lambda: self.spin_ui_scale.setValue(100))

        scale_row.addWidget(self.slider_ui_scale, 1)
        scale_row.addWidget(self.spin_ui_scale, 0)
        scale_row.addWidget(btn_scale_100, 0)

        ui_scale_form.addRow("UI-Größe / Skalierung:", scale_row)
        lbl_scale_hint = QLabel(
            "Skaliert alle Elemente des Widgets (Header, Raten-Zahlen, DNS-Pille, Buttons & Zähler) für hochauflösende Bildschirme."
        )
        lbl_scale_hint.setStyleSheet("color: #8E9297; font-size: 8.5pt;")
        lbl_scale_hint.setWordWrap(True)
        ui_scale_form.addRow(lbl_scale_hint)
        disp_layout.addWidget(ui_scale_group)

        # Skalierung & Leitungskapazität
        scale_group = QGroupBox("Graph-Skalierung && Leitungskapazität")
        scale_form = QFormLayout(scale_group)
        scale_form.setContentsMargins(10, 10, 10, 10)
        scale_form.setVerticalSpacing(6)

        self.cmb_scale_mode = QComboBox()
        self.cmb_scale_mode.addItem(
            "Wurzel-Skala (Smart: kleine Raten sichtbar + bis 100% Leitung)", "sqrt"
        )
        self.cmb_scale_mode.addItem(
            "Dynamisch (Skaliert auf aktuellen Peak, %-Balken zeigt echte Last)",
            "dynamic",
        )
        self.cmb_scale_mode.addItem(
            "Fix auf Leitungskapazität (Original-Verhalten)", "fixed"
        )

        self.chk_auto_link = QCheckBox(
            "Maximale Bandbreite automatisch per UPnP von Fritz!Box lesen"
        )
        self.chk_auto_link.toggled.connect(self._on_auto_link_toggled)

        self.spin_max_down = QDoubleSpinBox()
        self.spin_max_down.setRange(1.0, 10000.0)
        self.spin_max_down.setDecimals(1)
        self.spin_max_down.setSuffix(" Mbit/s")

        self.spin_max_up = QDoubleSpinBox()
        self.spin_max_up.setRange(0.5, 10000.0)
        self.spin_max_up.setDecimals(1)
        self.spin_max_up.setSuffix(" Mbit/s")

        scale_form.addRow("Skalierungs-Modus:", self.cmb_scale_mode)
        scale_form.addRow(self.chk_auto_link)
        scale_form.addRow("Max. Download (Manuell):", self.spin_max_down)
        scale_form.addRow("Max. Upload (Manuell):", self.spin_max_up)
        disp_layout.addWidget(scale_group)

        # Raten & Graphen-Darstellung
        rates_group = QGroupBox("Raten- && Graphen-Darstellung")
        rates_grid = QGridLayout(rates_group)
        rates_grid.setContentsMargins(10, 10, 10, 10)
        rates_grid.setVerticalSpacing(6)

        self.chk_compact = QCheckBox("Kompakt-Modus (Graph ausblenden)")
        self.chk_graph_only = QCheckBox("Nur-Graph-Modus (obere Zahlen ausblenden)")
        self.chk_switch_up_down = QCheckBox("Download oben / Upload unten")
        self.chk_show_bits = QCheckBox("Als Bit/s anzeigen (Mbit/s statt MB/s)")
        self.chk_show_peak = QCheckBox("Peak-Rate anzeigen (z. B. Peak 60s)")
        self.chk_show_guest_meta = QCheckBox("Gäste-WLAN-Rate unter Raten anzeigen")
        self.chk_session_totals = QCheckBox("Online- / Session-Zähler im Footer:")

        self.chk_compact.toggled.connect(
            lambda chk: self.chk_graph_only.setChecked(False) if chk else None
        )
        self.chk_graph_only.toggled.connect(
            lambda chk: self.chk_compact.setChecked(False) if chk else None
        )

        self.cmb_footer_mode = QComboBox()
        self.cmb_footer_mode.addItem("Heute (Fritz!Box Online-Zähler)", "today")
        self.cmb_footer_mode.addItem("Gestern (Fritz!Box Online-Zähler)", "yesterday")
        self.cmb_footer_mode.addItem("Aktuelle Woche (Fritz!Box Online-Zähler)", "week")
        self.cmb_footer_mode.addItem("Aktueller Monat (Fritz!Box Online-Zähler)", "month")
        self.cmb_footer_mode.addItem("Vormonat (Fritz!Box Online-Zähler)", "last_month")
        self.cmb_footer_mode.addItem("Seit Widget-Start (ohne Login)", "session")

        rates_grid.addWidget(self.chk_compact, 0, 0)
        rates_grid.addWidget(self.chk_graph_only, 0, 1)
        rates_grid.addWidget(self.chk_switch_up_down, 1, 0)
        rates_grid.addWidget(self.chk_show_bits, 1, 1)
        rates_grid.addWidget(self.chk_show_peak, 2, 0)
        rates_grid.addWidget(self.chk_show_guest_meta, 2, 1)

        footer_row = QHBoxLayout()
        footer_row.addWidget(self.chk_session_totals)
        footer_row.addWidget(self.cmb_footer_mode, 1)
        rates_grid.addLayout(footer_row, 3, 0, 1, 2)
        disp_layout.addWidget(rates_group)
        disp_layout.addStretch(1)

        self.tabs.addTab(self._wrap_in_scroll(tab_display), "Anzeige")

        # =========================================================================
        # TAB 4: Netzwerk (Eigener PC & Diagnose)
        # =========================================================================
        tab_net = QWidget()
        net_layout = QVBoxLayout(tab_net)
        net_layout.setContentsMargins(8, 8, 8, 8)
        net_layout.setSpacing(8)

        # Local Device Group
        pc_group = QGroupBox("Lokales Gerät (Eigener PC-Traffic Anteil)")
        pc_layout = QVBoxLayout(pc_group)
        pc_layout.setContentsMargins(10, 10, 10, 10)
        self.chk_local_pc = QCheckBox("Eigenen PC-Traffic überwachen (Anteil am Internet-Traffic)")
        self.chk_pc_in_graph = QCheckBox("Eigenen Anteil im Graphen einfärben (abgedunkelte Nuance)")
        self.chk_pc_in_header = QCheckBox("Eigene Rate als Text unter den Haupt-Raten anzeigen")
        self.chk_local_pc.toggled.connect(self._on_local_pc_toggled)

        pc_layout.addWidget(self.chk_local_pc)
        pc_sub_layout = QVBoxLayout()
        pc_sub_layout.setContentsMargins(20, 2, 0, 0)
        pc_sub_layout.setSpacing(5)
        pc_sub_layout.addWidget(self.chk_pc_in_graph)
        pc_sub_layout.addWidget(self.chk_pc_in_header)
        pc_layout.addLayout(pc_sub_layout)
        net_layout.addWidget(pc_group)

        # Internet-Diagnose
        diag_group = QGroupBox("Internet-Diagnose && Ping")
        diag_form = QFormLayout(diag_group)
        diag_form.setContentsMargins(10, 10, 10, 10)
        diag_form.setVerticalSpacing(6)

        self.chk_ping_graph = QCheckBox("Ping- && Jitter-Graph unterhalb von Down/Up anzeigen")
        self.cmb_ping_endpoint = QComboBox()
        self.cmb_ping_endpoint.setEditable(True)
        self.cmb_ping_endpoint.addItems(["1.1.1.1", "8.8.8.8", "9.9.9.9", "heise.de", "google.com"])

        self.chk_wan_pill = QCheckBox("WAN-Verbindungsstatus anzeigen (✓ WAN OK / ⚠ Kein Sync / ✕ Offline)")
        self.chk_dns_pill = QCheckBox("Aktiven System-DNS-Server überwachen (Antwortzeit in ms)")

        diag_form.addRow("", self.chk_ping_graph)
        diag_form.addRow("Ping-Ziel (Endpoint):", self.cmb_ping_endpoint)
        diag_form.addRow("", self.chk_wan_pill)
        diag_form.addRow("", self.chk_dns_pill)
        net_layout.addWidget(diag_group)
        net_layout.addStretch(1)

        self.tabs.addTab(self._wrap_in_scroll(tab_net), "Netzwerk")

        # =========================================================================
        # TAB 5: Farben (Modernes Theme & Farbpalette)
        # =========================================================================
        tab_colors = QWidget()
        col_layout = QVBoxLayout(tab_colors)
        col_layout.setContentsMargins(8, 8, 8, 8)
        col_layout.setSpacing(8)

        # Theme Schnellauswahl
        theme_group = QGroupBox("Theme-Schnellauswahl (Farb-Vorlagen)")
        theme_layout = QHBoxLayout(theme_group)
        theme_layout.setContentsMargins(10, 8, 10, 8)
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(list(THEMES.keys()))
        btn_apply_theme = QPushButton("Theme anwenden")
        btn_apply_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply_theme.clicked.connect(self._apply_selected_theme)

        theme_layout.addWidget(QLabel("Vorlage:"))
        theme_layout.addWidget(self.cmb_theme, 1)
        theme_layout.addWidget(btn_apply_theme)
        col_layout.addWidget(theme_group)

        colors_row = QHBoxLayout()
        colors_row.setSpacing(10)

        # Traffic & Ping Graphen
        traffic_group = QGroupBox("Traffic && Ping Graphen")
        traffic_form = QFormLayout(traffic_group)
        traffic_form.setContentsMargins(10, 10, 10, 10)
        traffic_form.setVerticalSpacing(6)
        self.btn_col_down = ColorButton(self.config.download_color)
        self.btn_col_up = ColorButton(self.config.upload_color)
        self.btn_col_guest_down = ColorButton(self.config.guest_download_color)
        self.btn_col_guest_up = ColorButton(self.config.guest_upload_color)
        self.btn_col_ping = ColorButton(self.config.ping_color)
        self.btn_col_jitter = ColorButton(self.config.jitter_color)

        traffic_form.addRow("Download-Farbe:", self.btn_col_down)
        traffic_form.addRow("Upload-Farbe:", self.btn_col_up)
        traffic_form.addRow("Gäste-Download:", self.btn_col_guest_down)
        traffic_form.addRow("Gäste-Upload:", self.btn_col_guest_up)
        traffic_form.addRow("Ping-Farbe:", self.btn_col_ping)
        traffic_form.addRow("Jitter-Farbe:", self.btn_col_jitter)
        colors_row.addWidget(traffic_group)

        # Widget Design & Hintergrund
        theme_box = QGroupBox("Widget Design")
        theme_form = QFormLayout(theme_box)
        theme_form.setContentsMargins(10, 10, 10, 10)
        theme_form.setVerticalSpacing(6)
        self.btn_col_bg = ColorButton(self.config.background_color)
        self.btn_col_border = ColorButton(self.config.border_color)
        self.btn_col_grid = ColorButton(self.config.grid_color)
        self.btn_col_title = ColorButton(self.config.title_color)

        theme_form.addRow("Hintergrund:", self.btn_col_bg)
        theme_form.addRow("Rahmen:", self.btn_col_border)
        theme_form.addRow("Raster (Grid):", self.btn_col_grid)
        theme_form.addRow("Titelfarbe:", self.btn_col_title)
        colors_row.addWidget(theme_box)

        col_layout.addLayout(colors_row)
        col_layout.addStretch(1)

        self.tabs.addTab(self._wrap_in_scroll(tab_colors), "Farben")

        # =========================================================================
        # TAB 6: Über (App-Info, Systemdiagnose, Datenschutz & Lizenz)
        # =========================================================================
        tab_about = self._build_about_tab()
        self.tabs.addTab(self._wrap_in_scroll(tab_about), "Über")

        # =========================================================================
        # Untere Aktions-Buttons
        # =========================================================================
        btn_row = QHBoxLayout()
        self.btn_reset = QPushButton("Reset (Standardwerte)")
        self.btn_reset.clicked.connect(self._reset_defaults)
        self.btn_apply = QPushButton("Übernehmen")
        self.btn_apply.clicked.connect(self._apply_changes)
        self.btn_ok = QPushButton("Speichern && Schließen")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._save_and_close)

        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_ok)
        root_layout.addLayout(btn_row)

        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _build_about_tab(self) -> QWidget:
        """Build a sleek, compact 'Über' tab that fits without any scrollbar."""
        tab_about = QWidget()
        about_layout = QVBoxLayout(tab_about)
        about_layout.setContentsMargins(10, 10, 10, 10)
        about_layout.setSpacing(10)

        # 1. Hero / App Identity Group
        hero_group = QGroupBox("Über TrafficBox")
        hero_vlayout = QVBoxLayout(hero_group)
        hero_vlayout.setContentsMargins(12, 10, 12, 10)
        hero_vlayout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        lbl_app_icon = QLabel()
        lbl_app_icon.setPixmap(create_router_icon(True).pixmap(QSize(36, 36)))
        lbl_app_icon.setFixedSize(38, 38)
        lbl_app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(lbl_app_icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)

        name_badge_row = QHBoxLayout()
        name_badge_row.setSpacing(8)
        lbl_app_name = QLabel("TrafficBox")
        lbl_app_name.setStyleSheet("font-size: 12pt; font-weight: bold;")
        self.lbl_about_version = QLabel(f"v{__version__}")
        self.lbl_about_version.setStyleSheet(
            "color: #00E5FF; background-color: rgba(0, 229, 255, 0.12); "
            "border: 1px solid rgba(0, 229, 255, 0.4); border-radius: 6px; "
            "padding: 1px 7px; font-weight: bold; font-size: 8.5pt;"
        )
        name_badge_row.addWidget(lbl_app_name)
        name_badge_row.addWidget(self.lbl_about_version)
        name_badge_row.addStretch(1)

        lbl_tagline = QLabel(
            "Schlankes Live-Desktop-Widget für Router-Traffic (UPnP), PC-Anteil, Ping, Jitter & DNS."
        )
        lbl_tagline.setStyleSheet("color: #8E9297; font-size: 8.5pt;")

        title_col.addLayout(name_badge_row)
        title_col.addWidget(lbl_tagline)
        top_row.addLayout(title_col, 1)
        hero_vlayout.addLayout(top_row)

        # Quick Action Buttons
        links_row = QHBoxLayout()
        links_row.setSpacing(6)

        self.btn_about_github = QPushButton("🌐 GitHub")
        self.btn_about_github.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_about_github.setToolTip(self.GITHUB_REPO_URL)
        self.btn_about_github.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self.GITHUB_REPO_URL))
        )

        self.btn_about_releases = QPushButton("🚀 Releases")
        self.btn_about_releases.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_about_releases.setToolTip(self.GITHUB_RELEASES_URL)
        self.btn_about_releases.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self.GITHUB_RELEASES_URL))
        )

        self.btn_about_issues = QPushButton("🐛 Fehler melden")
        self.btn_about_issues.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_about_issues.setToolTip(self.GITHUB_ISSUES_URL)
        self.btn_about_issues.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self.GITHUB_ISSUES_URL))
        )

        self.btn_about_config_dir = QPushButton("📂 Konfig-Ordner")
        self.btn_about_config_dir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_about_config_dir.setToolTip("Öffnet den Konfigurationsordner im Dateimanager")
        self.btn_about_config_dir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_config_dir())))
        )

        links_row.addWidget(self.btn_about_github)
        links_row.addWidget(self.btn_about_releases)
        links_row.addWidget(self.btn_about_issues)
        links_row.addWidget(self.btn_about_config_dir)
        hero_vlayout.addLayout(links_row)
        about_layout.addWidget(hero_group)

        # 2. Compact System & Legal Info Group
        info_group = QGroupBox("System-Diagnose && Rechtliches")
        info_form = QFormLayout(info_group)
        info_form.setContentsMargins(12, 8, 12, 8)
        info_form.setVerticalSpacing(5)

        is_frozen = getattr(sys, "frozen", False)
        build_mode = "Binary" if is_frozen else "Source"
        cfg_dir = get_config_dir()
        is_portable = cfg_dir.name.lower() == "local"
        storage_mode = "Portabel (local/)" if is_portable else "Systemprofil"

        lbl_sys_val = QLabel(
            f"{platform.system()} {platform.release()} ({platform.machine()}) • "
            f"Python {platform.python_version()} • Qt {qVersion()} • {build_mode}"
        )
        lbl_sys_val.setStyleSheet("font-size: 8.5pt;")

        lbl_cfg_val = QLabel(storage_mode)
        lbl_cfg_val.setToolTip(f"Pfad: {cfg_dir}")
        lbl_cfg_val.setStyleSheet("font-size: 8.5pt;")

        lbl_notes = QLabel(
            "Open Source (MIT) • 100 % lokal ohne Telemetrie • "
            "<span style='color: #8E9297;'>Kein Produkt der FRITZ! GmbH (ehem. AVM).</span>"
        )
        lbl_notes.setStyleSheet("font-size: 8.5pt;")

        info_form.addRow("Laufzeit:", lbl_sys_val)
        info_form.addRow("Speicherort:", lbl_cfg_val)
        info_form.addRow("Hinweise:", lbl_notes)
        about_layout.addWidget(info_group)

        about_layout.addStretch(1)
        return tab_about

    def _on_tab_changed(self, index: int) -> None:
        """Disable tab-reset button when viewing the read-only 'Über' tab."""
        self.btn_reset.setEnabled(index != 5)

    def _apply_selected_theme(self) -> None:
        """Apply a selected color theme preset across all color buttons."""
        theme_name = self.cmb_theme.currentText()
        theme = THEMES.get(theme_name)
        if not theme:
            return
        self.btn_col_down.hex_color = theme["down"]
        self.btn_col_up.hex_color = theme["up"]
        self.btn_col_guest_down.hex_color = theme["guest_down"]
        self.btn_col_guest_up.hex_color = theme["guest_up"]
        self.btn_col_ping.hex_color = theme["ping"]
        self.btn_col_jitter.hex_color = theme["jitter"]
        self.btn_col_bg.hex_color = theme["bg"]
        self.btn_col_border.hex_color = theme["border"]
        self.btn_col_grid.hex_color = theme["grid"]
        self.btn_col_title.hex_color = theme["title"]

    @staticmethod
    def _wrap_in_scroll(content_widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content_widget)
        return scroll

    def _on_auto_link_toggled(self, checked: bool) -> None:
        self.spin_max_down.setEnabled(not checked)
        self.spin_max_up.setEnabled(not checked)

    def _on_guest_toggled(self, checked: bool) -> None:
        self.txt_user.setEnabled(checked)
        self.txt_pass.setEnabled(checked)

    def _on_local_pc_toggled(self, checked: bool) -> None:
        self.chk_pc_in_graph.setEnabled(checked)
        self.chk_pc_in_header.setEnabled(checked)

    def _on_test_connection(self) -> None:
        """Test UPnP reachability and Fritz!OS login and show immediate inline feedback."""
        host = self.txt_host.text().strip() or "fritz.box"
        port = self.spin_port.value()
        user = self.txt_user.text().strip()
        pwd = self.txt_pass.text()

        self.btn_test_conn.setEnabled(False)
        self.btn_test_conn.setText(" Teste Verbindung...")
        self.lbl_test_result.setVisible(True)
        self.lbl_test_result.setText("Verbindung wird geprüft...")
        self.lbl_test_result.setStyleSheet("color: #CCCCCC; font-size: 8pt;")
        QApplication.processEvents()

        try:
            # 1. Test basic UPnP reachability and discover box identity
            upnp_client = FritzUpnpClient(host=host, port=port, timeout=2.5)
            try:
                upnp_client._discover_endpoints()
                upnp_ok = True
            except Exception:
                upnp_ok = False

            if not upnp_ok:
                self.lbl_test_result.setText(f"✕ Fritz!Box unter '{host}:{port}' nicht erreichbar.")
                self.lbl_test_result.setStyleSheet("color: #FF5252; font-weight: bold; font-size: 8.5pt;")
                return

            # Update detected box info
            if upnp_client.box_udn:
                short_id = upnp_client.box_udn.split("-")[-1]
                box_name = upnp_client.box_name or "FRITZ!Box"
                self.lbl_bound_box.setText(f"Erkannt: {box_name} (ID: {short_id})")

            # 2. Test Fritz!OS Login if enabled
            if self.chk_guest.isChecked():
                if not pwd:
                    self.lbl_test_result.setText("⚠ Bitte ein Passwort eingeben, um den Login zu testen.")
                    self.lbl_test_result.setStyleSheet("color: #FFAB00; font-weight: bold; font-size: 8.5pt;")
                    return

                client = FritzGuestMonitorClient(host=host, username=user, password=pwd, timeout=4.0)
                ok, msg, _block_time = client.test_login()
                if ok:
                    if upnp_client.box_udn:
                        self.config.bound_box_udn = upnp_client.box_udn
                        self.config.bound_box_name = upnp_client.box_name
                        short_id = upnp_client.box_udn.split("-")[-1]
                        box_name = upnp_client.box_name or "FRITZ!Box"
                        self.lbl_bound_box.setText(f"✓ Gebunden an {box_name} (ID: {short_id})")
                        self.lbl_bound_box.setStyleSheet("color: #00E676; font-size: 8.5pt;")
                    self.lbl_test_result.setText(f"✓ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 8.5pt;")
                elif msg.startswith("Bitte noch"):
                    self.lbl_test_result.setText(f"⚠ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #FFAB00; font-weight: bold; font-size: 8.5pt;")
                else:
                    self.lbl_test_result.setText(f"✕ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #FF5252; font-weight: bold; font-size: 8.5pt;")
            else:
                self.lbl_test_result.setText("✓ UPnP erreichbar (Live-Traffic aktiv).")
                self.lbl_test_result.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 8.5pt;")
        finally:
            self.btn_test_conn.setEnabled(True)
            self.btn_test_conn.setText(" Verbindung && Login testen")

    def _load_from_config(self) -> None:
        self.txt_host.setText(self.config.fritzbox_host)
        self.spin_port.setValue(self.config.upnp_port)
        self.spin_refresh.setValue(self.config.refresh_interval_sec)
        self.spin_delay.setValue(self.config.start_delay_sec)

        self.chk_autostart.setChecked(
            is_autostart_enabled() or self.config.autostart
        )
        self.chk_always_on_top.setChecked(self.config.always_on_top)
        self.chk_locked_pos.setChecked(self.config.locked_pos)
        self.chk_switch_up_down.setChecked(self.config.switch_up_down)
        self.chk_show_bits.setChecked(self.config.show_as_bits)
        self.chk_compact.setChecked(self.config.compact_mode)
        self.chk_graph_only.setChecked(self.config.graph_only_mode)
        self.chk_session_totals.setChecked(self.config.show_session_totals)
        self.chk_show_peak.setChecked(self.config.show_peak_rate)
        self.chk_show_guest_meta.setChecked(self.config.show_guest_rate_labels)
        self.chk_local_pc.setChecked(self.config.enable_local_traffic_monitor)
        self.chk_pc_in_graph.setChecked(self.config.show_local_traffic_in_graph)
        self.chk_pc_in_header.setChecked(self.config.show_local_traffic_in_header)
        self._on_local_pc_toggled(self.config.enable_local_traffic_monitor)
        f_idx = self.cmb_footer_mode.findData(self.config.footer_counter_mode)
        self.cmb_footer_mode.setCurrentIndex(max(0, f_idx))
        self.slider_opacity.setValue(self.config.opacity)
        self.spin_ui_scale.setValue(self.config.ui_scale_percent)

        idx = self.cmb_scale_mode.findData(self.config.scale_mode)
        self.cmb_scale_mode.setCurrentIndex(max(0, idx))
        self.chk_auto_link.setChecked(self.config.auto_link_scale)
        self.spin_max_down.setValue(self.config.manual_download_mbps)
        self.spin_max_up.setValue(self.config.manual_upload_mbps)
        self._on_auto_link_toggled(self.config.auto_link_scale)

        self.chk_ping_graph.setChecked(self.config.enable_ping_graph)
        self.cmb_ping_endpoint.setEditText(self.config.ping_endpoint)
        self.chk_wan_pill.setChecked(self.config.show_wan_status_pill)
        self.chk_dns_pill.setChecked(self.config.enable_dns_monitor)

        self.btn_col_down.hex_color = self.config.download_color
        self.btn_col_up.hex_color = self.config.upload_color
        self.btn_col_guest_down.hex_color = self.config.guest_download_color
        self.btn_col_guest_up.hex_color = self.config.guest_upload_color
        self.btn_col_ping.hex_color = self.config.ping_color
        self.btn_col_jitter.hex_color = self.config.jitter_color
        self.btn_col_bg.hex_color = self.config.background_color
        self.btn_col_border.hex_color = self.config.border_color
        self.btn_col_grid.hex_color = self.config.grid_color
        self.btn_col_title.hex_color = self.config.title_color

        self.chk_guest.setChecked(self.config.enable_guest_monitor)
        self.txt_user.setText(self.config.fritz_username)
        self.txt_pass.setText(self.config.fritz_password)
        self._on_guest_toggled(self.config.enable_guest_monitor)

        if self.config.bound_box_udn:
            short_id = self.config.bound_box_udn.split("-")[-1]
            box_label = self.config.bound_box_name or "FRITZ!Box"
            self.lbl_bound_box.setText(f"✓ Gebunden an {box_label} (ID: {short_id})")
            self.lbl_bound_box.setStyleSheet("color: #00E676; font-size: 8.5pt;")
        else:
            self.lbl_bound_box.setText("Nicht gebunden (wird beim ersten Login automatisch an diesen Heim-Router gebunden)")
            self.lbl_bound_box.setStyleSheet("color: #8E9297; font-size: 8.5pt;")

    def _apply_changes(self) -> None:
        self.config.fritzbox_host = self.txt_host.text().strip() or "fritz.box"
        self.config.upnp_port = self.spin_port.value()
        self.config.refresh_interval_sec = self.spin_refresh.value()
        self.config.start_delay_sec = self.spin_delay.value()

        want_autostart = self.chk_autostart.isChecked()
        if want_autostart:
            set_autostart(True)
        elif is_autostart_enabled():
            set_autostart(False)
        self.config.autostart = want_autostart

        self.config.always_on_top = self.chk_always_on_top.isChecked()
        self.config.locked_pos = self.chk_locked_pos.isChecked()
        self.config.switch_up_down = self.chk_switch_up_down.isChecked()
        self.config.show_as_bits = self.chk_show_bits.isChecked()
        self.config.compact_mode = self.chk_compact.isChecked()
        self.config.graph_only_mode = self.chk_graph_only.isChecked()
        self.config.show_session_totals = self.chk_session_totals.isChecked()
        self.config.show_peak_rate = self.chk_show_peak.isChecked()
        self.config.show_guest_rate_labels = self.chk_show_guest_meta.isChecked()
        self.config.enable_local_traffic_monitor = self.chk_local_pc.isChecked()
        self.config.show_local_traffic_in_graph = self.chk_pc_in_graph.isChecked()
        self.config.show_local_traffic_in_header = self.chk_pc_in_header.isChecked()
        self.config.footer_counter_mode = str(self.cmb_footer_mode.currentData() or "today")
        self.config.opacity = self.slider_opacity.value()
        self.config.ui_scale_percent = self.spin_ui_scale.value()
        self._save_geometry_to_config()

        self.config.scale_mode = str(self.cmb_scale_mode.currentData() or "sqrt")
        self.config.auto_link_scale = self.chk_auto_link.isChecked()
        self.config.manual_download_mbps = self.spin_max_down.value()
        self.config.manual_upload_mbps = self.spin_max_up.value()

        self.config.enable_ping_graph = self.chk_ping_graph.isChecked()
        self.config.ping_endpoint = self.cmb_ping_endpoint.currentText().strip() or "1.1.1.1"
        self.config.show_wan_status_pill = self.chk_wan_pill.isChecked()
        self.config.enable_dns_monitor = self.chk_dns_pill.isChecked()

        self.config.download_color = self.btn_col_down.hex_color
        self.config.upload_color = self.btn_col_up.hex_color
        self.config.guest_download_color = self.btn_col_guest_down.hex_color
        self.config.guest_upload_color = self.btn_col_guest_up.hex_color
        self.config.ping_color = self.btn_col_ping.hex_color
        self.config.jitter_color = self.btn_col_jitter.hex_color
        self.config.background_color = self.btn_col_bg.hex_color
        self.config.border_color = self.btn_col_border.hex_color
        self.config.grid_color = self.btn_col_grid.hex_color
        self.config.title_color = self.btn_col_title.hex_color

        self.config.enable_guest_monitor = self.chk_guest.isChecked()
        self.config.fritz_username = self.txt_user.text().strip()
        new_pwd = self.txt_pass.text()
        pwd_changed = new_pwd != self.config.fritz_password
        self.config.fritz_password = new_pwd

        if self.config.enable_guest_monitor and new_pwd:
            if not self.config.bound_box_udn or pwd_changed:
                try:
                    probe = FritzUpnpClient(host=self.config.fritzbox_host, port=self.config.upnp_port, timeout=1.5)
                    probe._discover_endpoints()
                    if probe.box_udn:
                        self.config.bound_box_udn = probe.box_udn
                        self.config.bound_box_name = probe.box_name
                except Exception:
                    pass
        elif not new_pwd:
            self.config.bound_box_udn = ""
            self.config.bound_box_name = ""

        self.config.save()
        self.on_apply()

    def _save_and_close(self) -> None:
        self._apply_changes()
        self.accept()

    def _reset_defaults(self) -> None:
        current_idx = self.tabs.currentIndex()
        tab_name = self.tabs.tabText(current_idx).replace("&&", "&")

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Standardwerte wiederherstellen")
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setText(
            f"Möchtest du nur den aktuellen Reiter '{tab_name}' oder alle Einstellungen zurücksetzen?"
        )
        btn_tab = msg_box.addButton(f"Nur '{tab_name}' zurücksetzen", QMessageBox.ButtonRole.ActionRole)
        btn_all = msg_box.addButton("Alle Einstellungen zurücksetzen", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = msg_box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(btn_tab)

        msg_box.exec()
        clicked = msg_box.clickedButton()

        if clicked == btn_tab:
            self._reset_single_tab(current_idx)
        elif clicked == btn_all:
            self.config.reset_defaults()
            self._load_from_config()
            self.config.save()
            self.on_apply()

    def _reset_single_tab(self, tab_idx: int) -> None:
        """Reset only the settings belonging to a specific tab index."""
        defaults = AppConfig()

        if tab_idx == 0:  # FRITZ!Box
            self.txt_host.setText(defaults.fritzbox_host)
            self.spin_port.setValue(defaults.upnp_port)
            self.spin_refresh.setValue(defaults.refresh_interval_sec)
            self.chk_guest.setChecked(defaults.enable_guest_monitor)
            self.txt_user.setText(defaults.fritz_username)
            self.txt_pass.setText(defaults.fritz_password)
            self.lbl_bound_box.setText("Nicht gebunden (wird beim ersten Login automatisch an diesen Heim-Router gebunden)")
            self.lbl_bound_box.setStyleSheet("color: #8E9297; font-size: 8.5pt;")
            self.lbl_test_result.setVisible(False)
        elif tab_idx == 1:  # Allgemein
            self.chk_autostart.setChecked(defaults.autostart)
            self.spin_delay.setValue(defaults.start_delay_sec)
            self.chk_always_on_top.setChecked(defaults.always_on_top)
            self.chk_locked_pos.setChecked(defaults.locked_pos)
            self.slider_opacity.setValue(defaults.opacity)
        elif tab_idx == 2:  # Anzeige
            self.spin_ui_scale.setValue(defaults.ui_scale_percent)
            idx = self.cmb_scale_mode.findData(defaults.scale_mode)
            self.cmb_scale_mode.setCurrentIndex(max(0, idx))
            self.chk_auto_link.setChecked(defaults.auto_link_scale)
            self.spin_max_down.setValue(defaults.manual_download_mbps)
            self.spin_max_up.setValue(defaults.manual_upload_mbps)
            self.chk_compact.setChecked(defaults.compact_mode)
            self.chk_graph_only.setChecked(defaults.graph_only_mode)
            self.chk_switch_up_down.setChecked(defaults.switch_up_down)
            self.chk_show_bits.setChecked(defaults.show_as_bits)
            self.chk_show_peak.setChecked(defaults.show_peak_rate)
            self.chk_show_guest_meta.setChecked(defaults.show_guest_rate_labels)
            self.chk_session_totals.setChecked(defaults.show_session_totals)
            f_idx = self.cmb_footer_mode.findData(defaults.footer_counter_mode)
            self.cmb_footer_mode.setCurrentIndex(max(0, f_idx))
        elif tab_idx == 3:  # Netzwerk
            self.chk_local_pc.setChecked(defaults.enable_local_traffic_monitor)
            self.chk_pc_in_graph.setChecked(defaults.show_local_traffic_in_graph)
            self.chk_pc_in_header.setChecked(defaults.show_local_traffic_in_header)
            self.chk_ping_graph.setChecked(defaults.enable_ping_graph)
            self.cmb_ping_endpoint.setEditText(defaults.ping_endpoint)
            self.chk_wan_pill.setChecked(defaults.show_wan_status_pill)
            self.chk_dns_pill.setChecked(defaults.enable_dns_monitor)
        elif tab_idx == 4:  # Farben
            self.btn_col_down.hex_color = defaults.download_color
            self.btn_col_up.hex_color = defaults.upload_color
            self.btn_col_guest_down.hex_color = defaults.guest_download_color
            self.btn_col_guest_up.hex_color = defaults.guest_upload_color
            self.btn_col_ping.hex_color = defaults.ping_color
            self.btn_col_jitter.hex_color = defaults.jitter_color
            self.btn_col_bg.hex_color = defaults.background_color
            self.btn_col_border.hex_color = defaults.border_color
            self.btn_col_grid.hex_color = defaults.grid_color
            self.btn_col_title.hex_color = defaults.title_color
