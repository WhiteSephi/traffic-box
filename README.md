# TrafficBox

> Schlankes, plattformübergreifendes Live-Desktop-Widget (CachyOS / KDE Plasma & Windows) zur Echtzeit-Überwachung von Upload- und Download-Raten an Routern (wie AVM FRITZ!Box) per UPnP sowie optionaler Gäste-WLAN- und lokaler PC-Traffic-Analyse.

---

## 🛠️ Tech-Stack & Voraussetzungen

- **Sprache / Runtime:** Python 3.11+ (getestet mit Python 3.12)
- **GUI-Framework:** PySide6 (Qt6) – native Darstellung unter KDE Plasma (Wayland/X11) und Windows
- **Netzwerk / Protokolle:** Python Standardbibliothek (`urllib`, `xml.etree`, `hashlib`) für UPnP SOAP (`WANCommonIFC1` über Port `49000`) & optional Fritz!OS Lua/TR-064 Online-Monitor

---

## 🚀 Installation & Setup

1. **Repository klonen:**
   ```bash
   git clone https://github.com/WhiteSephi/traffic-box.git
   cd traffic-box
   ```

2. **Umgebung & Abhängigkeiten einrichten:**
   - **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     pip install -r requirements.txt
     ```
   - **CachyOS / Arch Linux:**
     ```bash
     # Entweder über System-Paket (empfohlen unter KDE Plasma):
     sudo pacman -S pyside6
     # Oder in einer virtuellen Umgebung:
     python -m venv .venv
     source .venv/bin/activate
     pip install -r requirements.txt
     ```

3. **Konfiguration & Speicherort:**
   - **Standard-Speicherort:** Einstellungen werden automatisch im benutzerspezifischen Systemordner als `config.json` abgelegt:
     - Windows: `%APPDATA%\trafficbox\config.json`
     - Linux/CachyOS: `~/.config/trafficbox/config.json`
   - **Portabler Modus (z. B. USB-Stick):** Liegt im Projekt- bzw. Programmverzeichnis der Ordner `local/` und befindet sich darin eine `config.json`, liest und schreibt das Widget alle Einstellungen direkt dort hinein, ohne das Betriebssystem zu berühren.
   - **Umgebungsvariablen (optional):**
     ```bash
     cp .env.example .env
     ```
   *(Alle Einstellungen lassen sich bequem direkt über den Einstellungs-Dialog im Rechtsklick- bzw. System-Tray-Menü anpassen.)*

---

## 💻 Verwendung / Starten

- **Per Doppelklick / Starter-Skript:**
  - **Windows (ohne Konsolenfenster):** Doppelklick auf `start_windows.vbs`
  - **CachyOS / Linux:** `./start_linux.sh` (nach `chmod +x start_linux.sh`)
- **Über das Terminal:**
  ```bash
  python -m src.main
  ```
- **Bedienung im Widget:**
  - **Ziehen mit linker Maustaste:** Widget frei auf dem Desktop positionieren (sofern Position nicht gesperrt ist).
  - **Doppelklick / Rechtsklick:** Öffnet die **Einstellungen** bzw. das Schnellmenü (Skalierungs-Modus, Bit/Byte-Umschaltung, Kompakt-Modus, Immer im Vordergrund, Position sperren).

---

## 🧪 Automatisierte Tests

Das Projekt verfügt über eine schlanke Unit-Testsuite auf Basis der Python-Standardbibliothek (`unittest`), die ohne zusätzliche Abhängigkeiten direkt ausgeführt werden kann:

```bash
# Alle Tests ausführen
python -m unittest discover -s tests -v
```

---

## 📂 Projektstruktur

```text
.
├── src/
│   ├── main.py                 # Einstiegspunkt der Anwendung
│   ├── config.py               # Konfigurations-Management & .env-Support
│   ├── autostart.py            # Cross-Platform Autostart (Windows Registry & Linux XDG)
│   ├── api/
│   │   ├── models.py           # Datenmodelle (TrafficSample, OnlineCounterStats, PeriodCounter)
│   │   ├── worker.py           # Hintergrund-Thread & Polling-Orchestrierung (QObject)
│   │   ├── upnp_client.py      # Passwortfreier UPnP-SOAP-Client (Port 49000)
│   │   ├── fritz_monitor.py    # Optionaler Fritz!OS-Client für Online-Zähler & Gäste-WLAN
│   │   ├── net_health.py       # Ping-, Jitter- und aktiver OS-DNS-Latenz-Monitor
│   │   ├── local_traffic.py    # Lokaler PC-Traffic-Monitor (Windows iphlpapi & Linux /proc/net/dev)
│   │   └── crypto.py           # Sichere Passwort-Verschlüsselung (Windows DPAPI & PBKDF2)
│   └── ui/
│       ├── widget.py           # Rahmenloses Haupt-Widget (Header, Prozentbalken, Footer)
│       ├── graph_canvas.py     # Custom Qt6-Graph mit Oszilloskop-Hover-HUD & Mehrschicht-Flächen
│       ├── online_counter_view.py # Integrierte Online-Zähler-Tabellenansicht
│       ├── settings_dlg.py     # Umfangreicher Einstellungs-Dialog (Tabs, Farb-Picker, Cooldowns)
│       ├── formatters.py       # Formatierungshelfer für Raten, Einheiten (SI-Dezimal/Binär) & Zeiten
│       ├── icons.py            # Vektorgrafiken & Icons (Pfeile, UI-Symbole)
│       └── tray.py             # System-Tray-Integration & Schnellzugriff-Menü
├── tests/                      # Automatisierte Unit-Tests (unittest)
│   ├── test_config.py          # Konfiguration, Standardwerte & .env-Parser
│   ├── test_crypto.py          # Ver-/Entschlüsselung & Windows DPAPI Roundtrip
│   ├── test_formatters.py      # Raten-, Datenvolumen- & Uptime-Formatierung
│   ├── test_local_traffic.py   # Linux /proc/net/dev-Parsing & lokale Ratenberechnung
│   ├── test_net_health.py      # Ping-Regex (Windows/Linux) & Jitter-Berechnung
│   ├── test_upnp_client.py     # UPnP-Session-Tracking, UDN-Erkennung & 32-Bit-Überlaufschutz
│   └── test_worker_foreign_box.py # Schutz vor Fehl-Logins auf fremden FRITZ!Boxen (Roaming)
├── requirements.txt            # Python-Abhängigkeiten (PySide6)
├── .env.example                # Vorlage für Umgebungsvariablen
└── CHANGELOG.md                # Chronologische Änderungshistorie
```
