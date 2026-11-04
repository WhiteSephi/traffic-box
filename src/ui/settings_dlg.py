"""Settings dialog for configuring the TrafficBox Widget."""

from __future__ import annotations

from typing import Callable
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.api.fritz_monitor import FritzGuestMonitorClient
from src.api.upnp_client import FritzUpnpClient
from src.autostart import is_autostart_enabled, set_autostart
from src.config import AppConfig


class ColorButton(QPushButton):
    """Button that displays and selects a hex color."""

    def __init__(self, hex_color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = hex_color
        self.setFixedHeight(26)
        self.setMinimumWidth(110)
        self._update_style()
        self.clicked.connect(self._pick_color)

    @property
    def hex_color(self) -> str:
        return self._color

    @hex_color.setter
    def hex_color(self, value: str) -> None:
        self._color = value
        self._update_style()

    def _update_style(self) -> None:
        qcol = QColor(self._color)
        luminance = 0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()
        text_col = "#111111" if luminance > 140 else "#F5F5F5"
        self.setText(self._color.upper())
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; color: {text_col}; "
            "border: 1px solid #666; border-radius: 4px; font-weight: bold; }"
        )

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "Farbe wählen")
        if chosen.isValid():
            self.hex_color = chosen.name()


class SettingsDialog(QDialog):
    """Comprehensive settings window for TrafficBox with modern tabs."""

    def __init__(
        self,
        config: AppConfig,
        on_apply: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.on_apply = on_apply

        self.setWindowTitle("TrafficBox Einstellungen")
        self.setMinimumSize(600, 480)
        self.resize(680, 540)
        self._build_ui()
        self._load_from_config()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        tabs = QTabWidget(self)
        root_layout.addWidget(tabs)

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
        lbl_box_title = QLabel("Box-Kopplung (Schutz):")
        lbl_box_title.setStyleSheet("font-weight: bold; color: #E0E4E8; font-size: 8.5pt;")
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

        tabs.addTab(self._wrap_in_scroll(tab_fritz), "FRITZ!Box")

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

        tabs.addTab(self._wrap_in_scroll(tab_general), "Allgemein")

        # =========================================================================
        # TAB 3: Anzeige (Skalierung, Graphen & Raten-Darstellung)
        # =========================================================================
        tab_display = QWidget()
        disp_layout = QVBoxLayout(tab_display)
        disp_layout.setContentsMargins(8, 8, 8, 8)
        disp_layout.setSpacing(8)

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
        self.chk_switch_up_down = QCheckBox("Download oben / Upload unten")
        self.chk_show_bits = QCheckBox("Als Bit/s anzeigen (Mbit/s statt MB/s)")
        self.chk_show_peak = QCheckBox("Peak-Rate anzeigen (z. B. Peak 60s)")
        self.chk_show_guest_meta = QCheckBox("Gäste-WLAN-Rate unter Raten anzeigen")
        self.chk_session_totals = QCheckBox("Online- / Session-Zähler im Footer:")

        self.cmb_footer_mode = QComboBox()
        self.cmb_footer_mode.addItem("Heute (Fritz!Box Online-Zähler)", "today")
        self.cmb_footer_mode.addItem("Gestern (Fritz!Box Online-Zähler)", "yesterday")
        self.cmb_footer_mode.addItem("Aktuelle Woche (Fritz!Box Online-Zähler)", "week")
        self.cmb_footer_mode.addItem("Aktueller Monat (Fritz!Box Online-Zähler)", "month")
        self.cmb_footer_mode.addItem("Vormonat (Fritz!Box Online-Zähler)", "last_month")
        self.cmb_footer_mode.addItem("Seit Widget-Start (ohne Login)", "session")

        rates_grid.addWidget(self.chk_compact, 0, 0)
        rates_grid.addWidget(self.chk_switch_up_down, 0, 1)
        rates_grid.addWidget(self.chk_show_bits, 1, 0)
        rates_grid.addWidget(self.chk_show_peak, 1, 1)
        rates_grid.addWidget(self.chk_show_guest_meta, 2, 0)

        footer_row = QHBoxLayout()
        footer_row.addWidget(self.chk_session_totals)
        footer_row.addWidget(self.cmb_footer_mode, 1)
        rates_grid.addLayout(footer_row, 3, 0, 1, 2)
        disp_layout.addWidget(rates_group)
        disp_layout.addStretch(1)

        tabs.addTab(self._wrap_in_scroll(tab_display), "Anzeige")

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

        tabs.addTab(self._wrap_in_scroll(tab_net), "Netzwerk")

        # =========================================================================
        # TAB 5: Farben
        # =========================================================================
        tab_colors = QWidget()
        col_layout = QVBoxLayout(tab_colors)
        col_layout.setContentsMargins(8, 8, 8, 8)
        col_layout.setSpacing(8)

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
        theme_group = QGroupBox("Widget Design")
        theme_form = QFormLayout(theme_group)
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
        colors_row.addWidget(theme_group)

        col_layout.addLayout(colors_row)
        col_layout.addStretch(1)

        tabs.addTab(self._wrap_in_scroll(tab_colors), "Farben")

        # =========================================================================
        # Untere Aktions-Buttons
        # =========================================================================
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("Reset (Standardwerte)")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_apply = QPushButton("Übernehmen")
        btn_apply.clicked.connect(self._apply_changes)
        btn_ok = QPushButton("Speichern && Schließen")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._save_and_close)

        btn_row.addWidget(btn_reset)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_ok)
        root_layout.addLayout(btn_row)

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
                        self.lbl_bound_box.setText(f"✓ Gekoppelt an {box_name} (ID: {short_id})")
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
            self.lbl_bound_box.setText(f"✓ Gekoppelt an {box_label} (ID: {short_id})")
            self.lbl_bound_box.setStyleSheet("color: #00E676; font-size: 8.5pt;")
        else:
            self.lbl_bound_box.setText("Nicht gekoppelt (wird beim ersten Login automatisch an die Box gebunden)")
            self.lbl_bound_box.setStyleSheet("color: #8E9297; font-size: 8.5pt;")

    def _apply_changes(self) -> None:
        self.config.fritzbox_host = self.txt_host.text().strip() or "fritz.box"
        self.config.upnp_port = self.spin_port.value()
        self.config.refresh_interval_sec = self.spin_refresh.value()
        self.config.start_delay_sec = self.spin_delay.value()

        want_autostart = self.chk_autostart.isChecked()
        if want_autostart != is_autostart_enabled():
            set_autostart(want_autostart)
        self.config.autostart = want_autostart

        self.config.always_on_top = self.chk_always_on_top.isChecked()
        self.config.locked_pos = self.chk_locked_pos.isChecked()
        self.config.switch_up_down = self.chk_switch_up_down.isChecked()
        self.config.show_as_bits = self.chk_show_bits.isChecked()
        self.config.compact_mode = self.chk_compact.isChecked()
        self.config.show_session_totals = self.chk_session_totals.isChecked()
        self.config.show_peak_rate = self.chk_show_peak.isChecked()
        self.config.show_guest_rate_labels = self.chk_show_guest_meta.isChecked()
        self.config.enable_local_traffic_monitor = self.chk_local_pc.isChecked()
        self.config.show_local_traffic_in_graph = self.chk_pc_in_graph.isChecked()
        self.config.show_local_traffic_in_header = self.chk_pc_in_header.isChecked()
        self.config.footer_counter_mode = str(self.cmb_footer_mode.currentData() or "today")
        self.config.opacity = self.slider_opacity.value()

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
        self.config.reset_defaults()
        self._load_from_config()
        self.config.save()
        self.on_apply()
