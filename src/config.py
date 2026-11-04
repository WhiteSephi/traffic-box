"""Configuration management and environment variable loader."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import sys

from src.api.crypto import decrypt_secret, encrypt_secret


def _log_warn(msg: str) -> None:
    """Safely log a warning even when running as a windowless GUI binary (sys.stderr is None)."""
    if sys.stderr is not None:
        try:
            print(msg, file=sys.stderr)
        except OSError:
            pass


def load_dotenv_file(env_path: Path | None = None) -> None:
    """Load key-value pairs from a local .env file without external dependencies."""
    target = env_path or Path.cwd() / ".env"
    if not target.is_file():
        return
    try:
        for raw_line in target.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError as exc:
        _log_warn(f"[WARN] Konnte .env nicht lesen: {exc}")


def get_config_dir() -> Path:
    """Return platform-specific configuration directory with portable local/ fallback."""
    if getattr(sys, "frozen", False):
        base_root = Path(sys.executable).resolve().parent
    else:
        base_root = Path(__file__).resolve().parent.parent
    local_dir = base_root / "local"
    if (local_dir / "config.json").is_file():
        return local_dir

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    cfg_dir = base / "trafficbox"
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        return cfg_dir
    except OSError:
        local_dir.mkdir(parents=True, exist_ok=True)
        return local_dir


@dataclass
class AppConfig:
    """Persistent configuration for the TrafficBox Widget."""

    # Connection
    fritzbox_host: str = "fritz.box"
    upnp_port: int = 49000
    refresh_interval_sec: int = 1
    start_delay_sec: int = 0

    # Optional Fritz!OS Authentication (for Guest Wi-Fi traffic breakdown)
    enable_guest_monitor: bool = False
    fritz_username: str = ""
    fritz_password: str = ""
    bound_box_udn: str = ""  # Unique UDN of the Fritz!Box these credentials belong to
    bound_box_name: str = ""  # Friendly model name of the bound Fritz!Box

    # Optional Local Device (PC) Traffic Monitor
    enable_local_traffic_monitor: bool = False
    show_local_traffic_in_graph: bool = True
    show_local_traffic_in_header: bool = False

    # Window & Behavior
    title: str = "TrafficBox"
    autostart: bool = False
    always_on_top: bool = False
    locked_pos: bool = False
    compact_mode: bool = False
    # active_view: "graph" (Live-Graph) or "counters" (Online-Zähler Tabelle)
    active_view: str = "graph"
    switch_up_down: bool = True  # True = Download on top, Upload on bottom
    show_as_bits: bool = False  # False = kB/s & MB/s, True = kbit/s & Mbit/s
    show_peak_rate: bool = True  # True = "X,X% • Peak (60s): ...", False = "X,X%"
    show_guest_rate_labels: bool = True  # True = "Gast: ...", False = hidden in header
    show_session_totals: bool = True
    # footer_counter_mode: "today", "yesterday", "week", "month", "last_month", "session"
    footer_counter_mode: str = "today"
    show_connection_tooltip: bool = True
    opacity: int = 85  # 20..100 %
    widget_width: int = 460
    widget_height: int = 300
    pos_x: int = -1
    pos_y: int = -1

    # Scaling & Bandwidth Limits
    # scale_mode: "sqrt" (Wurzel-Skala), "dynamic" (Auto-Peak), "fixed" (Leitungs-Max)
    scale_mode: str = "sqrt"
    auto_link_scale: bool = False
    manual_download_mbps: float = 500.0
    manual_upload_mbps: float = 36.0
    history_seconds: int = 60

    # Diagnostics & Network Health
    enable_ping_graph: bool = True
    ping_endpoint: str = "1.1.1.1"
    show_wan_status_pill: bool = True
    enable_dns_monitor: bool = True

    # Colors
    download_color: str = "#FFEA00"
    upload_color: str = "#4A5CFF"
    guest_download_color: str = "#00E676"
    guest_upload_color: str = "#FF9100"
    ping_color: str = "#00E5FF"
    jitter_color: str = "#FF9100"
    background_color: str = "#1C2428"
    border_color: str = "#5E616C"
    grid_color: str = "#32383D"
    title_color: str = "#E0E4E8"

    @classmethod
    def config_file_path(cls) -> Path:
        """Return full path to the JSON config file."""
        return get_config_dir() / "config.json"

    @classmethod
    def load(cls) -> AppConfig:
        """Load configuration from disk and apply environment variable overrides."""
        load_dotenv_file()
        cfg = cls()
        path = cls.config_file_path()
        if path.is_file():
            try:
                raw_data = json.loads(path.read_text(encoding="utf-8"))
                valid_keys = {f.name for f in fields(cls)}
                for key, value in raw_data.items():
                    if key in valid_keys:
                        setattr(cfg, key, value)
                # Transparently decrypt stored password if encrypted
                cfg.fritz_password = decrypt_secret(cfg.fritz_password)
            except (OSError, json.JSONDecodeError) as exc:
                _log_warn(f"[WARN] Konnte Konfiguration nicht laden ({path}): {exc}")

        # Environment variable overrides (.env)
        if os.environ.get("FRITZBOX_HOST"):
            cfg.fritzbox_host = os.environ["FRITZBOX_HOST"].strip()
        if os.environ.get("FRITZBOX_UPNP_PORT"):
            try:
                cfg.upnp_port = int(os.environ["FRITZBOX_UPNP_PORT"])
            except ValueError:
                pass
        if os.environ.get("FRITZBOX_USERNAME") and not cfg.fritz_username:
            cfg.fritz_username = os.environ["FRITZBOX_USERNAME"].strip()
        if os.environ.get("FRITZBOX_PASSWORD") and not cfg.fritz_password:
            cfg.fritz_password = os.environ["FRITZBOX_PASSWORD"]
            cfg.enable_guest_monitor = True

        return cfg

    def save(self, target_path: Path | None = None) -> None:
        """Save current configuration to disk with encrypted credentials."""
        path = target_path or self.config_file_path()
        try:
            data = asdict(self)
            if data.get("fritz_password"):
                data["fritz_password"] = encrypt_secret(self.fritz_password)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            _log_warn(f"[ERROR] Konnte Konfiguration nicht speichern ({path}): {exc}")

    def reset_defaults(self) -> None:
        """Reset all settings back to default values."""
        defaults = AppConfig()
        for field_info in fields(AppConfig):
            setattr(self, field_info.name, getattr(defaults, field_info.name))
