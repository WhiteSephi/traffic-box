# Changelog

Alle relevanten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.
Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.17.1] - 2026-11-19
### Changed
- **Kompaktere Diagnose-Tooltips & klare Trennung (`src/ui/widget.py`, `src/api/internet_health.py`):**
  - Header (`lbl_icon` / `lbl_title`) zeigt nun wieder ausschließlich den kompakten FRITZ!Box-/Router-Tooltip, während die Status-Pille im Footer (`lbl_wan_pill`) einen eigenen, auf 3–4 Zeilen verdichteten Internet-Diagnose-Tooltip anzeigt.
  - Redundante Wiederholungen in `DEGRADED`-Gründen (z. B. doppelte `Leitung ausgelastet`-Zusätze und doppelte Latenz-/Jitter-Werte) entfernt.

### Fixed
- **Tooltip-Styling & Kontrast (`src/ui/widget.py`):** CSS für Status-Pillen (`_get_pill_style`, `lbl_footer`) auf `QLabel` eingeschränkt und explizites `QToolTip`-Theme-Styling ergänzt, damit Tooltips über Status-Pillen keine Pillen-Hintergrundfarben mehr erben.

## [0.17.0] - 2026-11-19
### Added
- **Mehrstufige Internet-Qualitäts- & Erreichbarkeits-Diagnose (`src/api/internet_health.py`, `src/api/net_health.py`):**
  - **End-to-End-Prüfung mit Quorum & Hysterese:** Prüft zusätzlich zum Router-Status die lokale Gateway-Referenz, zwei unabhängige Dual-Stack-HTTPS-`204`-Canaries (`cp.cloudflare.com` & `connectivitycheck.gstatic.com`, jeweils frische TLS-Verbindung ohne Keep-Alive/Redirects, mit RAM-IP-Cache und Kaltstart-Direkt-IP-Fallback) sowie Uncached-DNS.
  - **5-Stufen-Statusmodell mit „Zombie-WAN“-Erkennung (`src/api/models.py`, `src/ui/widget.py`):** Unterscheidet klar zwischen **Stabil**, **Eingeschränkt** (z. B. IPv4-/IPv6-Teilausfall, 2–20 % Verlust, Latenz-/Jitter-Abweichung oder langsamer DNS), **DNS-Störung** (HTTPS per IP ok, aber lokaler DNS/AdGuard gestört), **Offline / Zombie-WAN** (Router meldet „Verbunden“, aber Internetverkehr hängt) und **LAN-Problem** (Heimnetz/Router gestört).
  - **Sliding Window & Idle-Baseline:** Berechnet über 60 Sekunden Paketverlust %, Median, p95-Latenz und Jitter gegen eine automatisch im Leerlauf (`< 40 %` Auslastung) gelernte Baseline inkl. Untergrenzen und Bufferbloat-Hinweis bei ausgelasteter Leitung (`>= 75 %`).
  - **Theme-bewusste UI, Tray-LED & Ping-Verlustmarker (`src/ui/widget.py`, `src/ui/tray.py`, `src/ui/graph_canvas.py`):** Status-Pille im Footer (Grün `#00E676` bei „Stabil“ mit ruhiger Anpassung für monochrome/helle Themes), farbige Status-LED am Router- & Tray-Icon, kompakter Diagnose-Abschnitt im HTML-Tooltip sowie sichtbare Lücken + rote Verlustmarker bei Ping-Timeouts im Graphen.
  - **Konfiguration & Einstellungen (`src/config.py`, `src/ui/settings_dlg.py`):** Neue Optionen unter `Netzwerk → Internet-Diagnose & Erreichbarkeit` (Aktivierung, IP-Protokollmodus `Auto / Nur IPv4 / Dual-Stack`, Normal-Intervall `10–120 s` mit automatischem `5 s`-Verifikations-Burst bei Störung, Uncached-DNS-Schalter).
- **Automatisierte Tests (`tests/test_internet_health.py`):** Umfangreiche Offline-Testsuite für alle 5 Statusstufen, Quorum, Hysterese, Sliding-Window/Baseline, IPv6-Auto-Erkennung, IP-Cache/Kaltstart-Fallback, RCODE-/Hijack-Prüfung und Theme-/Tooltip-Tests (`119` Tests gesamt).

### Changed
- **Uncached-DNS statt 1-Sekunden-Cache-Polling (`src/api/net_health.py`, `src/api/worker.py`):** Bei aktiver Internet-Diagnose entfällt das sekündliche Abfragen einer statischen Domain; stattdessen werden im 30s-Intervall (bzw. 5s-Burst) eindeutige Nonce-Subdomains abgefragt und RCODE (`NXDOMAIN`/`NOERROR` vs. `SERVFAIL`/`REFUSED`) sowie Private-IP-Umleitungen (`0.0.0.0`/RFC1918) geprüft. Das reduziert die DNS-Last um ~97 % und umgeht lokale DNS-Caches (z. B. AdGuard Optimistic Cache).
- **Windows-DNS-Erkennung (`src/api/net_health.py`):** `detect_active_os_dns()` bevorzugt unter Windows nun direkt `iphlpapi.GetNetworkParams` vor der Registry-Adapter-Schleife, um zuverlässig den aktiven System-DNS zu treffen.

### Fixed
- **Ping-Aussetzer im Graphen (`src/ui/graph_canvas.py`):** Verlorene Pings werden im Ping-/Jitter-Graphen nicht mehr irreführend als `0 ms` gezeichnet, sondern unterbrechen die Kurve mit Verlust-Marker und Anzeige von `Loss: X%` bzw. `✕ Timeout` im Hover-HUD.

## [0.16.3] - 2026-11-19
### Security
- **Heim-Router-Bindung & DNS-Fallback gehärtet (`src/api/worker.py`, `src/ui/settings_dlg.py`):**
  - Gast-/Online-Zähler-Logins nutzen nun durchgängig die bereits geprüfte, lokal aufgelöste Gateway-IP (`self.upnp.host`) statt des unaufgelösten Hostnamens, sodass bei manipuliertem oder externem `fritz.box`-DNS keine Anmeldedaten nach außen gesendet werden.
  - **Fail-Closed UDN-Prüfung:** Ist eine `bound_box_udn` hinterlegt, aber das Gerät liefert keine `<UDN>`, wird der Login nun blockiert statt durchgelassen.
  - Der Verbindungstest in den Einstellungen wertet den Rückgabewert von `_discover_endpoints()` nun korrekt aus und beendet Test-Sessions direkt per `logout()`.
- **Fritz!OS-Client & UPnP-HTTP-Härtung (`src/api/fritz_monitor.py`, `src/api/upnp_client.py`):**
  - MD5-v1-Downgrade ist standardmäßig blockiert (`allow_legacy_md5=False`); PBKDF2-Iterationen sind auf `MAX_PBKDF2_ITERATIONS = 100_000` (Salt-Länge `1..64` Bytes) begrenzt.
  - HTTP-Redirects werden über `_NoRedirectHandler` strikt abgelehnt, Antwortgrößen auf `1 MiB` (`MAX_RESPONSE_BYTES`) begrenzt und UPnP-`controlURL`-Pfade gegen Pfad-/URL-Injektion validiert.
  - Aktive Fritz!OS-Sessions werden beim Beenden/Neuladen über `logout()` (`logout=1`) sauber abgemeldet.
- **Konfiguration, Secrets & Dateirechte (`src/config.py`, `src/api/crypto.py`, `src/main.py`):**
  - Linux-/Fallback-Schutz nutzt nun authentifiziertes Encrypt-then-MAC (`v2:` mit PBKDF2-HMAC-SHA256, 200.000 Iterationen, HMAC-SHA256 & User-UID im Salt); Windows DPAPI erhält explizite `argtypes`/`restype` und sichere Buffer-Lebensdauer.
  - `AppConfig.save()` schreibt atomar über temporäre Dateien (`os.replace`) mit `0o600`-Rechten (und `0o700` für den Konfig-Ordner unter POSIX).
  - `.env`-Werte (insb. `FRITZBOX_PASSWORD`) werden über `read_dotenv_file()` direkt in `AppConfig` gelesen, ohne sie über `os.environ` an Kindprozesse zu vererben.
  - `AppConfig.sanitize()` validiert `fritzbox_host` und `ping_endpoint` per `is_valid_host()`, prüft alle 10 Hex-Farbfelder gegen `#RRGGBB` und bereinigt auch `enable_local_fallback` (sowie CLI `--host` in `src/main.py`).
- **Netzwerkdiagnose, Autostart, UI & Speicher-Sicherheit (`src/api/net_health.py`, `src/api/local_traffic.py`, `src/autostart.py`, `src/ui/widget.py`, `src/ui/settings_dlg.py`):**
  - `measure_ping()` prüft Ziele per `is_valid_host()`, Linux-`ping`-Fallback nutzt `--`; `measure_dns_latency()` verwendet zufällige 2-Byte-TxIDs und prüft Quell-IP sowie TxID der Antwort.
  - `_MIB_IF_ROW2` in `local_traffic.py` um die fehlenden 8 `uint64`-Felder (64 Bytes → `1352` Bytes unter Win64) korrigiert und `argtypes`/`restype` für `iphlpapi` ergänzt.
  - Autostart-Skriptgenerierung nutzt voll qualifiziertes `wscript.exe`, Base64-gekapselten Pfad im Windows-Fallback, Freedesktop-konformes Escaping in `.desktop`-Dateien und atomares Schreiben für `kwinrulesrc`.
  - Tooltips in `TrafficBox._update_tooltip()` escapen UPnP-Gerätedaten per `html.escape()`; Status-Labels im Einstellungs-Dialog erzwingen `PlainText`; Hinweis im „Über“-Tab auf *„Keine Telemetrie (Ping-/DNS-Checks optional)“* präzisiert.

## [0.16.2] - 2026-11-19
### Changed
- **Datenschutz & GitHub-Vorbereitung (`.gitignore`, `TrafficBox.spec`, `CHANGELOG.md`):** `TODO.md` und `config.json` in `.gitignore` ergänzt, optionales App-Icon in `TrafficBox.spec` defensiv geprüft (damit Builds ohne `local/` funktionieren) und DNS-Hinweis im Changelog neutralisiert.

## [0.16.1] - 2026-11-17
### Added
- **Graph-Legende für Down & Up (`src/ui/graph_canvas.py`):** Download- und Upload-Graph zeigen oben links nun analog zu `◆ Ping` / `▲ Jitter` die farbige Bezeichnung `↓ Down` bzw. `↑ Up` an.

## [0.16.0] - 2026-11-17
### Added
- **Automatischer Fallback auf lokalen Netzwerktraffic (`src/api/worker.py`, `src/api/local_traffic.py`, `src/ui/widget.py`, `src/ui/settings_dlg.py`):**
  - Ist keine FRITZ!Box erreichbar (z. B. unterwegs im Fremdnetzwerk), schaltet TrafficBox automatisch auf die Messung des lokalen Netzwerkadapters um und zeigt Live-Down/Up-Raten, Graph, Auslastungsbalken, Peak-Werte sowie das Session-Volumen (`Seit Widget-Start`) an.
  - Die Status-Pill zeigt im Fallback-Modus `⚡ Lokal (ohne Box)` an; ein 10-Sekunden-UPnP-Cooldown verhindert wiederholte Timeouts im 1-Sekunden-Takt und wechselt automatisch zurück, sobald wieder eine FRITZ!Box gefunden wird.
  - Die Graph-Skalierung richtet sich im Fallback-Modus (bei aktivierter automatischer Leitungsskalierung) dynamisch am gemessenen Traffic aus (`Dyn (√)` bzw. `Dyn`, mindestens 1 Mbit/s), statt auf die statischen Home-Werte zurückzufallen.
  - Neue Einstellungsoption unter `Netzwerk → Lokales Gerät`: `Lokalen Netzwerktraffic als Fallback anzeigen (wenn keine FRITZ!Box erreichbar ist)` (standardmäßig aktiviert).

### Changed
- **Header-Buttons vergrößert (`src/ui/widget.py`):** Die Buttons `Graph`, `Zähler` und das Einstellungs-Zahnrad (`⚙`) sind nun etwas größer skaliert (`26 px` Höhe statt `20 px`, größere Icons und Schrift), um besser zum Rest des Widgets zu passen.
- **UI-Modularisierung (`src/ui/widget_window.py`, `src/ui/color_picker.py`):**
  - Fenster-Interaktion, Edge-Snapping, `VisualSizeGrip`, Kontextmenü und Tray-/Shutdown-Logik aus `src/ui/widget.py` nach `src/ui/widget_window.py` (`TrafficBoxWindowMixin`) ausgelagert.
  - Farbauswahl-Popup (`ModernColorPickerPopup`), `ColorButton` und `THEMES` aus `src/ui/settings_dlg.py` nach `src/ui/color_picker.py` ausgelagert.

### Fixed
- **Ping/Jitter-Legende (`src/ui/graph_canvas.py`):** Die Position von `▲ Jitter` wird nun per `QFontMetrics` dynamisch hinter `◆ Ping` berechnet, sodass sich beide Labels bei größeren Schriftarten/Skalierungen nicht mehr überlappen.

## [0.15.4] - 2026-11-13
### Changed
- **Einheitliche Benennung in `Anzeige` (`src/ui/settings_dlg.py`):** Gruppe auf `Globale Darstellung`, Label auf `UI-Skalierung:` sowie Prozentangaben einheitlich ohne Leerzeichen (`100% (Standard)`, `setSuffix("%")`) an SystemBox angeglichen.

## [0.15.3] - 2026-11-13
### Changed
- **Einstellungen an SystemBox angeglichen (`src/ui/settings_dlg.py`):**
  - Eigenes Router-Icon (`create_router_icon()`) als Fenster- & Taskleisten-Icon im Einstellungsdialog gesetzt.
  - `Deckkraft` in den Tab `Anzeige` verschoben und englische Klammerzusätze (`(Always on Top)`, `(LockedPos)`, `(Opacity)`) entfernt.
  - Tab `Farben` in `Design & Themes` umbenannt und untere Button-Leiste auf `Reset (Standardwerte)` + `Übernehmen | OK | Abbrechen` vereinheitlicht.

## [0.15.2] - 2026-11-13
### Changed
- **PyInstaller-Build verschlankt (`TrafficBox.spec`):** Ungenutzte Qt-Imageformat- und Touch-Plugins (`qtiff`, `qwebp`, `qjpeg`, `qpdf`, `qsvg`, `qtga`, `qwbmp`, `qicns`, `qgif`, `qsvgicon`, `qtuiotouchplugin`) sowie ungenutzte Python-Module (`decimal`, `lzma`, `bz2`, `sqlite3`) werden nun ausgeschlossen.

### Fixed
- **Qt-Übersetzungsfilter unter Windows (`TrafficBox.spec`):** Pfadtrenner werden vor dem Abgleich auf `PySide6/translations/` normalisiert, sodass neben `qt_help_*` nun tatsächlich alle nicht benötigten Sprachdateien (außer `de`/`en`) entfernt werden. Die Binary-Größe sinkt dadurch von 26,43 MB auf **23,27 MB** (-3,16 MB).

## [0.15.1] - 2026-11-12
### Changed
- **Reihenfolge im Einstellungsfenster:** Die Reiter `Allgemein` und `FRITZ!Box` wurden getauscht, sodass die Einstellungen nun standardmäßig mit `Allgemein` starten (inkl. Anpassung der tab-spezifischen Zurücksetzen-Logik).

## [0.15.0] - 2026-11-12
### Added
- **Magnetisches Einrasten an Bildschirmrändern (Edge Snapping / Docking):**
  - Analog zu *SystemBox* dockt das `TrafficBox`-Widget beim Verschieben nun innerhalb einer 14-Pixel-Schwelle magnetisch an allen Rändern des aktuellen Bildschirms (`availableGeometry()`, inkl. Multi-Monitor-Unterstützung) an.
  - Neue Konfigurationsoption `snap_to_edges` (Standard: `True`) sowie zugehörige Checkbox `Magnetisches Einrasten an Bildschirmrändern` im Reiter `Allgemein` unter `Fenster-Verhalten & Position`.

## [0.14.0] - 2026-11-12
### Added
- **Separate Speicherung der Position & Größe des Einstellungsfensters:**
  - Das Einstellungsfenster speichert nun seine Desktop-Koordinaten (`settings_pos_x`, `settings_pos_y`) sowie Abmessungen (`settings_width`, `settings_height`) in der Konfiguration (`config.json`).
  - Beim erneuten Öffnen wird die exakte Position auf dem Bildschirm wiederhergestellt, inklusive Sicherheitsprüfung gegen getrennte Monitore (automatisches Re-Centering bei fehlendem Bildschirm).
- **Vordergrund-Garantie für das Einstellungsfenster (Z-Order Korrektur):**
  - Behoben: Das Einstellungsfenster öffnete sich zuvor hinter dem Widget, da das rahmenlose Widget als `Tool`-Fenster mit optionalem `WindowStaysOnTopHint` über normalen Standard-Fenstern gerendert wurde.
  - Das Einstellungsfenster besitzt nun `Qt.WindowType.WindowStaysOnTopHint` und wird beim Öffnen über `raise_()` und `activateWindow()` garantiert in den Vordergrund über das Widget geholt.
- **Umfassende UI-Skalierung für HiDPI / kleine Bildschirme (70 % bis 300 % in 5 %-Schritten):**
  - Neuer Bereich `Benutzeroberflächen-Skalierung (HiDPI / Kleine Displays)` im Reiter `Anzeige` der Einstellungen mit Slider, SpinBox (beide fest in 5 %-Schritten gerastert) und Schnellwahl-Button `100 % (Standard)`.
  - Skaliert alle visuellen Elemente konsistent mit:
    - **Header:** Router-Icon, Fenstertitel, View-Buttons („Graph“ / „Zähler“) und Einstellungen-Button.
    - **Raten-Anzeige:** Header („Down:“ / „Up:“), Raten-Texte, Auslastungsbalken, Meta-Zeilen sowie PC- und Gast-WLAN-Labels.
    - **Live-Graph:** Mindesthöhe, Achsenskalierungs-Labels, Ping- und Jitter-Badges sowie Hover-HUD-Tooltip.
    - **Footer:** WAN-Status-Pille, Volumen-Zähler, DNS-Pille (`lbl_dns_pill`) sowie Resize-Grip (`VisualSizeGrip`).
    - **Online-Zähler Ansicht:** Perioden-Karten, Schriftgrößen, Balkenhöhe und Pfeil-Icons.
    - **Fenstermaße:** Dynamische Skalierung der Mindestmaße (`minimumSize`) zur Vermeidung von Textüberlappungen.

## [0.13.5] - 2026-11-09
### Added
- **Sichtbarer Resize-Griff (`VisualSizeGrip`) unten rechts:**
  - Unter Linux (insbesondere KDE Plasma Breeze) zeichnet das native `QSizeGrip`-Widget auf dunklem, transparentem Hintergrund keinerlei Punkte oder Linien, wodurch der Anfasser zur Größenänderung unsichtbar war.
  - Mit `VisualSizeGrip` wird nun plattformübergreifend ein klares, klassisches 6-Punkte-Diagonalraster mit Schatten und Highlight unten rechts gerendert, inklusive Größenänderungs-Cursor (`SizeFDiagCursor`) und Tooltip.
- **Direktes Umschalten des Footer-Zählers im Kontextmenü:**
  - Im Kontextmenü steht nun der direkte Umschalter `Footer-Zähler anzeigen` zur Verfügung, sodass der Zähler ohne Umweg über das Einstellungsmenü per Rechtsklick ein- und ausgeschaltet werden kann.

### Changed
- **Klarer Deaktiviert-Status im Zeitraum-Untermenü:**
  - Ist der Footer-Zähler in den Einstellungen oder im Kontextmenü deaktiviert, wechselt der Titel des Untermenüs auf `Footer-Zähler (Deaktiviert)`.
  - Im Untermenü selbst wurde der explizite Eintrag `Ausblenden (deaktiviert)` ergänzt, der im deaktivierten Zustand angehakt ist.
  - Das Anklicken eines beliebigen Zeitraums (z. B. Heute, Woche, Monat) aktiviert den Footer-Zähler automatisch und wechselt direkt auf den gewählten Zeitraum.
  - Die Kontextmenü-Aktion `Zähler „Seit Widget-Start“ zurücksetzen` wird bei deaktiviertem Footer-Zähler ausgegraut.
  - Das Kontextmenü des System-Tray-Icons wird bei visuellen Einstellungsänderungen nun ebenfalls sofort dynamisch aktualisiert.

## [0.13.4] - 2026-11-09
### Fixed
- **Ausblenden aus der Taskleiste unter XCB / XWayland:**
  - **Automatisches Setzen des EWMH-Atoms `_NET_WM_STATE_SKIP_TASKBAR`:** Unter X11/XWayland setzt Qt bei `Tool`-Fenstern zwar den Window-Type `UTILITY`, jedoch nicht zwingend das EWMH-Zustandsatom `_NET_WM_STATE_SKIP_TASKBAR`. In `showEvent()` wendet TrafficBox nun via `xprop` direkt `_NET_WM_STATE_SKIP_TASKBAR` und `_NET_WM_STATE_SKIP_PAGER` auf die native X11-Window-ID an.
  - **Regex-Match in KWin-Fensterregel (`.*[Tt]raffic[Bb]ox.*`):** Unter X11 lautet der Window-Class-String `"TrafficBox"` (Großschreibung), während er unter Wayland klein war (`"trafficbox"`). In `sync_kwin_position_rule()` wurde der Abgleich auf reguläre Ausdrücke (`wmclassmatch=3`) mit `.*[Tt]raffic[Bb]ox.*` umgestellt, sodass KWin das Fenster sowohl unter Wayland als auch unter XWayland/X11 zwingend aus der Taskleiste (`skiptaskbar=true`, `skiptaskbarrule=2`) verbannt.

## [0.13.3] - 2026-11-09
### Fixed
- **Verlässliche Positionserkennung & dauerhafte Desktop-Speicherung unter Linux:**
  - **Präferenz für XCB/XWayland (`QT_QPA_PLATFORM="xcb;wayland"`):** Nativ unter Wayland verbietet das Protokoll Anwendungen das Abfragen und Setzen globaler Bildschirmkoordinaten (`pos()` liefert stets `0, 0`). In `start_linux.sh` und `src/main.py` wird nun standardmäßig `xcb;wayland` als Plattform-Fallback vorgegeben, wodurch Qt via XWayland echte Desktop-Koordinaten verarbeiten kann und `move(x, y)` pixelgenau funktioniert.
  - **Direktes Client-seitiges Drag & Drop mit `_last_drag_pos`:** Das zuvor genutzte `startSystemMove()` übertrug die Maus-Steuerung an den Compositor, wodurch in Qt nach dem Loslassen kein `mouseReleaseEvent()` mehr ankam und neue Positionen niemals in `local/config.json` gespeichert wurden. Auf Nicht-Wayland-Plattformen (XCB, Windows, macOS) führt TrafficBox nun wieder direktes Verschieben aus und sichert beim Loslassen der linken Maustaste die exakten Koordinaten dauerhaft ab.

## [0.13.2] - 2026-11-09
### Fixed
- **Ausblenden des Widgets aus der Taskleiste (Task-Manager) unter Linux:**
  - **Tool-Window-Flag plattformübergreifend aktiviert:** In `_configure_window_flags()` war `Qt.WindowType.Tool` bisher ausschließlich auf `win32` beschränkt. Unter Linux führte dies dazu, dass TrafficBox als normales Hauptfenster behandelt und in der KDE-Plasma-Taskleiste als aktives Anwendungsfenster angezeigt wurde. Das Flag `Qt.WindowType.Tool` ist nun plattformübergreifend aktiv, wodurch das Widget wie unter Windows rein als Desktop-Widget bzw. über das System-Tray-Icon agiert und nicht mehr in der Taskleiste erscheint.
  - **Erzwungene KWin-Regel `skiptaskbar=true` & `skipswitcher=true`:** In `sync_kwin_position_rule()` wurden die Direktiven `skiptaskbar=true` (`skiptaskbarrule=2` / Force) und `skipswitcher=true` (`skipswitcherrule=2` / Force) in die KWin-Regel (`~/.config/kwinrulesrc`) integriert, sodass KWin das Widget auch auf Compositor-Ebene unter Wayland dauerhaft aus der Taskleiste und der Fensterumschaltung (Alt+Tab) fernhält.
- **Dauerhafte Speicherung der Widget-Position beim Systemstart:**
  - **Schutz vor ungewolltem Überschreiben der Startkoordinaten (`_user_is_moving`):** Wenn Wayland bzw. KWin das Widget beim Starten auf dem Bildschirm platziert hat, feuerte Qt bisher sofort ein `moveEvent()`, das die gespeicherten Desktop-Koordinaten innerhalb von 500 ms mit der zentrierten Position überschrieben hat. Das automatische Speichern von `pos_x` und `pos_y` sowie der 500-ms-Timer greifen nun nur noch, wenn der Nutzer das Widget aktiv mit der Maus bewegt (`_user_is_moving = True`).
  - **KWin-Regelstruktur für KDE Plasma 6 korrigiert:** In `~/.config/kwinrulesrc` werden im Block `[General]` nun zuverlässig `count=`, `rules=` und `Order=` gepflegt und der Fensterabgleich mit `wmclassmatch=2` (Teilstring) sowie `wmclasscomplete=false` ausgeführt, sodass KWin die Fensterregel verlässlich auf die TrafficBox anwendet.

## [0.13.1] - 2026-11-09
### Fixed
- **Widget-Fenster unter CachyOS / KDE Plasma (Wayland) wieder frei verschiebbar:**
  - Behoben: In der automatischen KWin-Regel (`~/.config/kwinrulesrc`) war `positionrule=2` hinterlegt. Im KWin-Enum bedeutet `2` jedoch `Force` (Erzwingen). KWin hat dadurch jeden Versuch, das Widget mit der Maus zu bewegen, blockiert und das Fenster festgenagelt.
  - Korrigiert auf `positionrule=3` (`Apply` = nur beim initialen Fensteraufbau anwenden). Das Widget startet weiterhin an der gespeicherten Position, lässt sich danach aber wieder völlig frei mit der Maus auf dem Desktop platzieren.
- **Hängender Graph & Verbindungsverlust behoben:**
  - Behoben: Ein Einstellungsdialog-Testlauf hatte die echte `local/config.json` mit Testwerten (`host=192.168.1.254`, `port=49001`, `refresh_interval=4s`) überschrieben. Da die IP/Port-Kombination nicht existierte, liefen die UPnP-Abfragen ins Leere, und das 4-Sekunden-Intervall ließ den Graphen einfrieren.
  - Test-Isolation: `tests/test_settings_dlg.py` und alle weiteren Tests mocken `config.save()`, sodass reale Konfigurationsdateien niemals berührt werden.
  - Die Konfigurationsdatei wurde auf die korrekten Standardwerte (`fritz.box`, Port `49000`, 1 s Intervall) repariert.
## [0.13.0] - 2026-11-06
### Added
- **„Über“-Seite im Einstellungs-Dialog & Kontextmenü (`Über TrafficBox...`):**
  - **Neuer Reiter „Über“:** Übersichtlich als 6. Tab im Einstellungs-Dialog integriert sowie direkt per Rechtsklick- und System-Tray-Menü über den Eintrag `Über TrafficBox...` erreichbar.
  - **App-Identität & Schnellzugriff:** Zeigt App-Icon, aktuelle Versionsnummer (`v0.13.0`), Kurzbeschreibung sowie Schnellzugriffs-Buttons für das GitHub-Repository, Releases/Updates, Fehlerberichte (Issues) und das lokale Konfigurationsverzeichnis (`📂 Konfig-Ordner`).
  - **System- & Laufzeit-Diagnose (Privacy-Safe):** Zeigt App-Version, Build-Modus (Standalone-Binary vs. Python-Quellcode), Betriebssystem, Python-/Qt6-Version und Speichermodus (ohne private Benutzerpfade im Klartext auf Screenshots preiszugeben). Inklusive 1-Klick-Button `📋 Info kopieren` für anonymisierte Bug-Reports.
  - **Schlankes No-Scrollbar-Layout:** Kompaktes 2-Karten-Design ohne vertikalen Scrollbalken, optimiert für Bildschirmauflösungen ab 600 px Fensterbreite.
  - **Datenschutz-, Lizenz- & Markenhinweise:** Transparente Übersicht zu *Privacy by Design* (100 % lokal, keine Telemetrie, DPAPI/PBKDF2-Verschlüsselung & UDN-Router-Bindung), Open-Source-Lizenzen (MIT, PSF, LGPLv3) sowie markenrechtlichem AVM/FRITZ!-Disclaimer.

## [0.12.2] - 2026-11-06
### Fixed
- **Kein `PING.EXE - Application Error (0xc0000142)` mehr beim Herunterfahren von Windows:**
  - **Native In-Process-ICMP-Messung unter Windows (`iphlpapi.dll`):** Statt für jede Ping-Messung sekündlich einen externen `ping.exe`-Kindprozess über `subprocess.run()` zu starten (dessen DLL-Initialisierung während des Windows-Shutdowns mit `STATUS_DLL_INIT_FAILED` / `0xc0000142` fehlschlägt), nutzt `measure_ping()` unter Windows nun direkt die native Win32-API `IcmpCreateFile` / `IcmpSendEcho` / `IcmpCloseHandle` aus `iphlpapi.dll` (ohne Admin-Rechte, komplett im selben Prozess und mit Sub-Millisekunden-Präzision).
  - **In-Process-DNS-Fallback unter Windows:** Der Fallback auf `ipconfig /all` in `detect_active_os_dns()` wurde durch die native Win32-Funktion `GetNetworkParams` (`iphlpapi.dll`) ersetzt, sodass unter Windows keinerlei Konsolen-Subprozesse mehr erzeugt werden.
  - **Unprivilegierte In-Process-ICMP-Sockets unter Linux:** Unter Linux nutzt `measure_ping()` primär unprivilegierte Kernel-Datagram-ICMP-Sockets (`SOCK_DGRAM` / `IPPROTO_ICMP`), wodurch auch unter Linux (z. B. CachyOS/Arch) das sekündliche Forken von `/usr/bin/ping` entfällt.
  - **Sauberer OS-Session-Shutdown-Handler (`commitDataRequest`, `aboutToQuit` & `SIGTERM`):** Das Widget fängt das Abmelde-/Shutdown-Signal des Betriebssystems (`QApplication.commitDataRequest` bzw. `WM_QUERYENDSESSION`, `aboutToQuit` sowie `SIGINT`/`SIGTERM`) ab, setzt sofort das Stop-Flag im `PollingWorker` und beendet Timer sowie Hintergrund-Thread kontrolliert.

## [0.12.1] - 2026-11-05
### Fixed
- **Defensive Konfigurations-Validierung & Range-Clamping:**
  - Manuell editierte oder korrumpierte Einträge in `config.json` (z. B. Buchstaben in Zahlenfeldern wie `upnp_port`, `refresh_interval_sec`, `opacity` oder negative Werte) werden beim Laden in `AppConfig.load()` automatisch abgefangen, bereinigt und auf sichere Standardwerte zurückgesetzt.
- **Automatische Positionsspeicherung & Wayland/KWin-Zentrierung nach Systemstart:**
  - **Debounced Positionsspeicherung:** Unter Wayland (KDE Plasma) wird das Verschieben des Fensters über `startSystemMove()` vom Window Manager gesteuert, wodurch bei Maustastenfreigabe kein `mouseReleaseEvent` im Qt-Widget eintrifft. Beim Verschieben wird nun über einen 500-ms-Timer die neue Desktop-Position nach jeder Bewegung automatisch und dauerhaft in `local/config.json` gesichert.
  - **KWin-Regel-Synchronisation für KDE Plasma (Wayland):** Da Wayland Clients das programmatische Setzen von Startkoordinaten (`move()`) verbietet und KWin neue Fenster standardmäßig in der Bildschirmmitte zentriert, synchronisiert TrafficBox unter Linux nun automatisch eine KWin-Fensterregel (`TrafficBox-Position` mit `wmclass=trafficbox` in `~/.config/kwinrulesrc`) und setzt `app.setDesktopFileName("trafficbox")`. KWin platziert das Widget beim Systemstart dadurch verlässlich an den gespeicherten Koordinaten.
  - **Verzögerte Geometrie-Wiederherstellung:** In `_restore_geometry()` wird die Zielposition nach dem ersten Anzeigen kurz verzögert erneut angewandt, um aggressives Zentrieren durch Compositor-Events zu überschreiben.
  - **Test-Isolation:** Automatisierte Unit-Tests überschreiben ab sofort nicht mehr die reale Konfiguration des Benutzers auf der Festplatte.

## [0.12.0] - 2026-11-05
### Added
- **Nur-Graph-Modus (obere Zahlen ausblenden):**
  - Neuer Modus zur ausschließlichen Beschränkung auf den Live-Graphen: Blendet die oberen Raten-Labels („Down:“, „Up:“), Übertragungsraten, Fortschrittsbalken und Prozentanzeigen komplett aus.
  - Der Live-Graph nutzt automatisch den gesamten vertikalen Raum im Widget aus.
  - Einstellbar über das Rechtsklick-Schnellmenü („Nur-Graph-Modus (Zahlen ausblenden)“) sowie im Einstellungs-Dialog unter dem Reiter „Anzeige“ („Nur-Graph-Modus (obere Zahlen ausblenden)“).
  - Flexible Mindesthöhe: Das Widget kann im Nur-Graph-Modus auf Wunsch flacher auf bis zu 160 px skaliert werden (statt standardmäßig 210 px).
  - Intelligente gegenseitige Verriegelung mit dem Kompakt-Modus („nur Zahlen“): Die beiden gegensätzlichen Ansichtsmodi schalten sich bei Auswahl automatisch wechselseitig um.

## [0.11.20] - 2026-11-05
### Fixed
- **Überlappung von Elementen im Kompakt-Modus (nur Zahlen):**
  - Behoben: Im Kompakt-Modus war das Widget auf eine veraltete Maximalhöhe von 115 px (bei initialer Zielgröße von 95–98 px) beschränkt. Durch die später hinzugekommenen Komponenten (WAN-Status-Pill, DNS-Pill, Footer-Zähler und Header-Buttons) reichte diese Höhe nicht aus, sodass Qt Rate-Labels („Down:“, „Up:“), Übertragungszahlen („910,0 kbit/s“), Fortschrittsbalken und Prozentwerte vertikal ineinander gequetscht und überlappt hat.
  - Dynamische Kompakthöhe: Eine neue Methode `_get_compact_height()` berechnet die benötigte Mindesthöhe dynamisch anhand der aktiven UI-Komponenten (Basis ca. 122–134 px, mit PC-/Gastnetz-Raten entsprechend angepasst), sodass alle Elemente jederzeit sauber getrennt mit ausreichend Abstand gerendert werden.
  - Header-View-Pills: Die Umschalt-Buttons „Graph“ und „Zähler“ leuchten im Kompaktmodus nicht mehr fälschlicherweise als aktiver Tab gelb auf, sondern bleiben dezent inaktiv gestylt (beim Klick darauf wird der Kompakt-Modus weiterhin wie gewohnt beendet und die jeweilige Ansicht geöffnet).

## [0.11.19] - 2026-11-05
### Fixed
- **Linux-Autostart bei Pfaden mit Leerzeichen (systemd-xdg-autostart-generator):**
  - Behoben: Befand sich das Projekt in einem Ordnerpfad mit Leerzeichen (z. B. `.../TrafficBox App/...`), trennte der unter Linux/CachyOS genutzte `systemd-xdg-autostart-generator` die `Exec`-Zeile beim ersten Leerzeichen ab (`Exec binary ... does not exist`) und verweigerte das Anlegen der systemd-Dienste.
  - Neu: In `trafficbox.desktop` wird der ausführbare Pfad in `Exec` nun automatisch in Anführungszeichen gefasst, sodass der Autostart auch bei Leerzeichen im Verzeichnisnamen zuverlässig startet und in KDE Plasma aktiv registriert wird.

## [0.11.18] - 2026-11-05
### Changed
- **Linux-Autostart & Binary-Harmonisierung:**
  - **Linux XDG-Autostart optimiert:** Beim Erstellen von `trafficbox.desktop` wird nun geprüft, ob das Widget als kompilierte ELF-Binary läuft (`Exec=/pfad/zu/TrafficBox`) oder als Skript (`Exec=start_linux.sh`), sodass die virtuelle Umgebung auch unter Linux (z. B. CachyOS) vollautomatisch gewählt wird.
  - **Einheitlicher Binary-Name:** PyInstaller-Build auf `TrafficBox.exe` (bzw. `TrafficBox`) vereinheitlicht.

## [0.11.17] - 2026-11-05
### Fixed
- **Autostart-Aktualisierung im Einstellungsdialog:**
  - Behoben: Beim Klick auf „Speichern“ prüfte der Dialog bisher nur, ob sich der Haken geändert hatte (`want_autostart != is_autostart_enabled()`). War Autostart bereits aktiv, wurde der Registry-Befehl nicht mit dem aktuellen Startpfad überschrieben. Nun wird der Autostart-Befehl beim Speichern mit gesetztem Haken immer zuverlässig auf den aktuellen Stand aktualisiert.

## [0.11.16] - 2026-11-05
### Changed
- **Fußzeilen-Layout & dynamische DNS-IP-Anzeige:**
  - **Feste Pill-Positionierung:** Die WAN-Pill bleibt dauerhaft ganz links verankert und die DNS-Pill ganz rechts. Wenn der mittlere Online-Zähler ausgeblendet ist, springen die Pills nicht mehr nach links zusammen, sondern behalten ihren Platz mit einem flexiblen Zwischenraum.
  - **Dynamische IP-Einblendung:** Die DNS-IP-Adresse wird ohne mittleren Zähler bereits ab 270 px Fensterbreite vollständig dargestellt (statt bisher starr ab 490 px); mit aktivem Zähler ab 420 px. Bei Fenstergrößenänderungen aktualisiert sich die Anzeige nun verzögerungsfrei in Echtzeit.

## [0.11.15] - 2026-11-05
### Fixed
- **Windows-Autostart im VBS- & Python-Modus:**
  - Behoben: Beim Setzen der Autostart-Option im Python-/VBS-Modus wurde `pythonw.exe -m src.main` in die Registry geschrieben. Da Windows Autostart-Einträge standardmäßig aus `C:\Windows\System32` startet, brach Python vor der Ausführung lautlos mit `ModuleNotFoundError: No module named 'src'` ab.
  - Neu: Im Quellcode-Modus wird nun automatisch `wscript.exe "<Projektpfad>\start_windows.vbs"` (bzw. ein robuster Python-Befehl mit Pfadinitialisierung) als Autostart hinterlegt, sodass das Widget sowohl als kompilierte Binary (`.exe`) als auch mit dem VBS-Starter zuverlässig beim Windows-Boot startet.

## [0.11.14] - 2026-11-05
### Fixed
- **Datenschutz & Privacy (Zero-Leak-Policy):** Spezifische Subnetz- und externe IP-Angaben in Unit-Tests (`test_resolve_fritzbox_host_fallback`) und Changelog-Einträgen auf neutrale RFC-5737-Dokumentations-IPs (`198.51.100.1`) und Standard-Gateways (`192.168.1.1` / `192.168.178.1`) bereinigt.

## [0.11.13] - 2026-11-04
### Changed
- **Reset-Dialog verschlankt:** Die redundanten Erklärungspunkte im Reset-Auswahldialog wurden entfernt, sodass der Dialog nun kompakt und direkt ist; die Buttons (`Nur '[Reiter]' zurücksetzen`, `Alle Einstellungen zurücksetzen`, `Abbrechen`) sprechen für sich selbst.

## [0.11.12] - 2026-11-04
### Added
- **Modernes Dark-Mode Color-Picker Popover:**
  - Die bisherigen Vollflächen-Farbbuttons wurden durch elegante Swatch-Pills (abgerundetes Farbfeld mit sauberem Monospace-Hex-Code `#FFEA00`) ersetzt.
  - Beim Klick öffnet sich ein modernes, dunkles Popover mit einer kuratierten Palette aus 24 abgestimmten Akzentfarben, direktem Hex-Eingabefeld mit Live-Vorschau und Fallback-Möglichkeit zur erweiterten Palette.
- **Theme-Schnellauswahl im Reiter Farben:**
  - 5 vorkonfigurierte Farb-Themen auf 1 Klick anwendbar: *TrafficBox Standard (Gelb & Blau)*, *Cyberpunk Neon (Cyan & Pink)*, *FRITZ!Box Classic (AVM Rot & Blau)*, *Emerald Matrix (Giftgrün & Minze)* und *Minimalist Monochrome (Weiß & Grau)*.
- **Sicherer, reiterbezogener Reset-Auswahldialog:**
  - Der Reset-Button öffnet nun eine strukturierte Auswahlabfrage: Es kann gezielt **nur der aktuell geöffnete Reiter** auf Standardwerte zurückgesetzt werden (ohne Passwörter oder Router-Kopplungen auf anderen Reitern zu löschen) oder die gesamte Konfiguration auf Werkseinstellungen.

## [0.11.11] - 2026-11-04
### Changed
- **Thematische Neustrukturierung der Einstellungs-Tabs (Variante C):**
  - Die Reiter wurden in die 5 allgemeingültigen Bereiche aufgeteilt:
    1. **FRITZ!Box**: Reine Router-Verbindung (IP, UPnP-Port, Refresh) und Fritz!OS-Login & Box-Kopplung.
    2. **Allgemein**: Systemstart- und Desktop-Optionen (Autostart mit System, Startverzögerung beim Booten, Always on Top, Position sperren, Deckkraft).
    3. **Anzeige**: Alle visuellen Raten- und Graph-Optionen (Skalierungsmodus Wurzel/Dyn/Fix, Bandbreiten-Limits, Kompaktmodus, Down/Up-Tausch, Bit/s-Modus, Peak-Rate, Gäste-WLAN-Rate und Footer-Zähler).
    4. **Netzwerk**: Lokale und globale Netzwerk-Gesundheit (PC-Traffic-Monitor, Ping- & Jitter-Graph mit Endpoint, WAN- und DNS-Statuspillen).
    5. **Farben**: Übersichtliche Farbkonfiguration für Traffic/Ping und Widget-Design.
  - Sämtliche Optionen sind auf jedem Bildschirm direkt und ohne vertikale Scrollbalken sichtbar.

## [0.11.10] - 2026-11-04
### Fixed
- **Scrollbalken im FRITZ!Box-Reiter vollständig beseitigt:**
  - Die drei numerischen Spinbox-Zeilen (`UPnP Port`, `Aktualisierung` und `Startverzögerung`) wurden platzsparend in einer gemeinsamen horizontalen Reihe zusammengefasst.
  - Die Netto-Höhe des Reiters sinkt dadurch von 410 px auf 309 px, sodass selbst bei kleiner Fensterhöhe (480–500 px) kein vertikaler Scrollbalken mehr getriggert wird.
  - Das von Qt interpretierte Ampersand-Mnemonic (`&`) wurde in Reiter-Titeln (`Graph && Leitung`, `Diagnose && Ping`), Gruppenüberschriften und Buttons per `&&` escaped, sodass alle Zeichen wieder vollständig dargestellt werden.

## [0.11.9] - 2026-11-04
### Changed
- **Einstellungs-Dialog in 5 fokussierte Bereiche aufgeteilt (vollständig scrollbalkenfrei):**
  - Die Einstellungen wurden aus dem überfüllten Allgemein-Reiter in fünf logisch strukturierte Reiter aufgeteilt:
    1. **FRITZ!Box**: Verbindungsparameter (Host, UPnP-Port, Refresh, Delay), optionaler Fritz!OS-Login und Box-Kopplungsschutz samt Test-Button und Inline-Feedback.
    2. **Darstellung**: Fensterverhalten (Autostart, Always on Top, Position sperren, Kompakt-Modus), Deckkraft-Schieberegler, Ansichts-Optionen (Bit/s, Up/Down-Tausch, Peak, Gäste-WLAN) und Footer-Zähler-Modus.
    3. **Graph & Leitung**: Skalierungsmodus (Wurzel, Dynamisch, Fix), Bandbreitenlimits und Lokaler PC-Traffic-Monitor.
    4. **Diagnose & Ping**: Ping- & Jitter-Graph und WAN-/DNS-Statuspillen.
    5. **Farben**: Übersichtliche zweispaltige Anordnung (Traffic & Ping vs. Widget-Design) aller 10 Farbkonfigurationen.
  - Jeder Reiter ist so kompakt bemessen, dass sämtliche Optionen sofort und ohne störende vertikale Scrollbalken sichtbar sind. Die Scrollbars bleiben als unsichtbare Absicherung (`ScrollBarAsNeeded`) nur für Extremfälle erhalten.

## [0.11.8] - 2026-11-04
### Fixed
- **Scrollbare Einstellungs-Tabs & permanente Speichern-Leiste:**
  - Die Tabs des Einstellungsfensters wurden in eine `QScrollArea` eingebettet, während die Aktionsleiste (`Speichern & Schließen`, `Übernehmen`, `Reset`) fest am unteren Fensterrand verankert bleibt. Dadurch wird verhindert, dass der Speichern-Button auf Bildschirmen mit Panel oder kleineren Auflösungen nach unten aus dem Bild geschoben wird.
  - Das Einklappen/Zerquetschen des Test-Buttons wurde behoben, indem das überflüssige innere Sub-Frame entfernt und der Button direkt mit nativer Mindesthöhe im Formular platziert wurde.
  - Die Dialoggröße wurde auf kompakte 680 × 620 Pixel optimiert (mit Scrollbereich für die Formulare).

## [0.11.7] - 2026-11-04
### Changed
- **Vollzeilige Box-Kopplungskarte & breiteres Einstellungsfenster:**
  - Die Box-Kopplungsanzeige samt Test-Button erstreckt sich nun als dezent gerahmte Karte über die **komplette Fensterbreite** (`addRow(box_card)`), sodass Modellnamen und Hardware-IDs ohne Umbruch voll ausgeschrieben werden.
  - Das Einstellungsfenster wurde auf eine Mindestbreite von 680 px (Standardgröße 700x840 px) vergrößert.
  - Verschachtelte Checkboxen für PC-Traffic und Bandbreitenoptionen wurden von nebeneinander auf ein hierarchisches vertikales Layout umgestellt, wodurch keine Beschriftungen mehr am rechten Fensterrand abgeschnitten werden.

## [0.11.6] - 2026-11-04
### Removed
- **Redundanten Login-Warnbalken in der Zähleransicht entfernt:** Der rote/gesperrte Hinweis-Button am unteren Rand der Zähleransicht (`⚠ Fritz!OS Login fehlgeschlagen` / `🔒 Fritz!OS Login in Einstellungen aktivieren`) wurde komplett entfernt. Die dezenten Einträge `Login nötig` direkt in den betroffenen Perioden-Karten genügen völlig, wodurch die Zähleransicht auch im passwortfreien UPnP-Betrieb ruhig und übersichtlich bleibt.

## [0.11.5] - 2026-11-04
### Fixed
- **Layout-Überlappung im Einstellungs-Dialog behoben:** Das Status-Label `lbl_bound_box` und der Test-Button `btn_test_conn` wurden in einen gemeinsamen vertikalen Container (`QVBoxLayout`) gebettet und die Mindestbreite des Dialogs vergrößert. Dadurch wird verhindert, dass zweizeiliger Box-Identifikationstext mit dem darunterliegenden Test-Button kollidiert.

## [0.11.4] - 2026-11-04
### Fixed
- **Echte Upstream-DNS-Erkennung unter Linux (AdGuard / systemd-resolved):** `detect_active_os_dns` liest unter Linux nun primär die echten Uplink-DNS-Server (über `/run/systemd/resolve/resolv.conf` bzw. `resolvectl dns`) aus und überspringt den lokalen `127.0.0.53`-Stub-Cache. Dadurch wird die tatsächliche Latenz zum konfigurierten Upstream-DNS-Server (z. B. AdGuard Home / Pi-hole) gemessen (statt der lokalen Loopback-Antwortzeit von 0,3 ms).

## [0.11.3] - 2026-11-04
### Fixed
- **Natives Fenster-Verschieben unter Wayland / KDE Plasma:** Die Mausinteraktion nutzt für das rahmenlose Fenster nun `windowHandle().startSystemMove()` des Fenstersystems. Dadurch lässt sich das Widget unter Wayland (KWin) und modernen Linux-Desktop-Umgebungen wieder flüssig und zuverlässig verschieben.
- **Präzise Kontextmenü-Positionierung:** Auf Linux/Wayland wurde das störende `Qt.WindowType.Tool`-Flag entfernt (welches Wayland-Popups entwurzelte) und das Menü auf `self.mapToGlobal(event.pos())` umgestellt, sodass es exakt am Klickpunkt erscheint.
- **Automatische Router-IP-Erkennung (Gateway-Fallback):** Löst `fritz.box` im lokalen Netzwerk (z. B. durch Public-DNS oder DoH) in eine externe Internet-IP auf oder ist nicht erreichbar, ermittelt das Widget nun automatisch das Standard-Gateway (z. B. `192.168.178.1` via `/proc/net/route`) und verbindet sich direkt mit der FRITZ!Box.
- **Schutz vor Offscreen-Fensterkoordinaten:** Beim Start wird geprüft, ob die gespeicherte Fensterposition (`pos_x`, `pos_y`) auf einem der aktuell angeschlossenen Monitore liegt. Liegen die Koordinaten außerhalb (z. B. nach Wechsel von Multi-Monitor auf Einzeldisplay), wird das Widget automatisch im sichtbaren Desktop-Bereich platziert.

## [0.11.2] - 2026-11-04
### Fixed
- **Bereinigung von Stylesheet-Syntaxfehlern:** Doppelte schließende geschweifte Klammern in CSS-Definitionen von Buttons (`widget.py`, `online_counter_view.py` und `settings_dlg.py`) korrigiert, wodurch Qt-Parser-Warnungen beim Anwendungsstart unter Linux vollständig eliminiert wurden.

## [0.11.1] - 2026-11-04
### Fixed
- **Robuste plattformübergreifende Entschlüsselung:** `decrypt_secret` fängt nun Decodierfehler und ungültige Payloads (z. B. wenn eine unter Windows mit DPAPI verschlüsselte Konfigurationsdatei direkt auf ein Linux-System kopiert wird) sicher ab, ohne den Anwendungsstart zu blockieren.
- **Vollständige Namensbereinigung:** Alle verbliebenen Docstrings und der Linux-Desktop-Autostart-Eintrag wurden einheitlich auf `TrafficBox` aktualisiert.

## [0.11.0] - 2026-11-04
### Added
- **Sichere Passwort-Verschlüsselung (Encryption at Rest) ohne Zusatzabhängigkeiten:**
  - **Native Windows DPAPI:** Verschlüsselt hinterlegte Fritz!OS-Passwörter in `config.json` über `CryptProtectData` (in `crypt32.dll` via `ctypes`) mit dem Masterschlüssel des aktuellen Windows-Benutzerkontos.
  - **Plattformunabhängiger Krypto-Fallback:** Schützt Passwörter auf Linux mittels symmetrischer PBKDF2-HMAC-SHA256-Schlüsselableitung (`/etc/machine-id` + User-UID).
  - **Vollkommen transparente Speicherung:** Im Arbeitsspeicher bleibt das Passwort unberührt, während auf der Festplatte ausschließlich sichere `enc:...`-Blobs gespeichert werden.
  - **Abwärtskompatibler Import:** Erkennt legacy Klartext-Passwörter beim Laden automatisch und überführt sie beim nächsten Speichern in den verschlüsselten Zustand.
  - **Unit-Testsuite erweitert:** Neue Tests in `tests/test_crypto.py` und `tests/test_config.py` sichern Ver- und Entschlüsselung sowie Roundtrip-Szenarien ab.

## [0.10.0] - 2026-11-04
### Added
- **Intelligente Box-Erkennung & Schutz fremder FRITZ!Boxen bei Standortwechsel (Roaming):**
  - **Passwortfreie UDN-Identifikation:** Liest beim Verbindungsaufbau automatisch die eindeutige Hardware-ID (`<UDN>`, inklusive MAC-Adresse) und das Modell (`<friendlyName>`, z. B. `FRITZ!Box 7590`) aus der UPnP-Gerätebeschreibung `/igddesc.xml` aus.
  - **Box-Bindung für Zugangsdaten:** Hinterlegte Fritz!OS-Passwörter (für Online-Zähler und Gäste-WLAN) werden fest an die erkannte Box-ID gekoppelt.
  - **Automatischer Schutzmodus für fremde Boxen:** Verbindet sich ein Laptop mit einer anderen FRITZ!Box (z. B. im Büro oder bei Freunden), werden Live-Raten via UPnP weiterhin voll angezeigt, jedoch **garantiert keine Login-Versuche mit dem fremden Passwort** gestartet. Dadurch werden Fehlversuche und die exponentielle Fritz!OS-Sperrzeit (`<BlockTime>`) auf fremden Boxen zuverlässig verhindert.
  - **Transparente Status-Rückmeldung:** Sowohl der Verbindungs-Tooltip als auch die Zähler-Ansicht weisen dezent auf den geschützten Gast-Modus hin (`ℹ Fremde Box (Modell) – Login zum Schutz vor Sperrung pausiert`).
  - **Kopplungs-Status im Einstellungs-Dialog:** Zeigt unter den Verbindungsdaten die aktuell erkannte FRITZ!Box und den Kopplungsstatus an. Bei Passworteingabe wird die neue Box beim Speichern oder Testen sofort übernommen.
  - **Unit-Test-Absicherung:** Neue Tests in `tests/test_worker_foreign_box.py` und `tests/test_upnp_client.py` verifizieren das Überspringen von Logins auf fremden Boxen.

## [0.9.2] - 2026-11-04
### Refactored
- **Entflechtung von UI und Hintergrund-Worker (`src/api/worker.py`):** Die Klasse `PollingWorker` (inklusive UPnP-, Fritz!OS Lua-, Ping- und Local-Traffic-Koordination) wurde aus `src/ui/widget.py` in ein eigenes Modul `src/api/worker.py` ausgelagert. Dadurch schrumpft das Haupt-Widget um über 100 Zeilen und trennt strikt die Datenabfrage von der UI-Darstellung.
- **Flexibleres Config-Speichern:** Die Methode `AppConfig.save(target_path=None)` akzeptiert nun optional einen benutzerdefinierten Zielpfad für vereinfachte Testbarkeit und Snapshot-Sicherungen.

### Added
- **Automatisierte Unit-Testsuite (`tests/`):** 17 modulare Tests auf Basis der Standardbibliothek (`unittest`) zur Absicherung der zentralen Komponenten ohne zusätzliche externe Abhängigkeiten:
  - `test_config.py`: Standardwerte, JSON-Speichern/Laden, `.env`-Parser.
  - `test_formatters.py`: Raten-Berechnung (Bits/Bytes), SI-Dezimalvolumen (GB/TB) und Uptime.
  - `test_local_traffic.py`: Linux `/proc/net/dev`-Parser, Interface-Filterung und Delta-Berechnung.
  - `test_net_health.py`: Ping-Regex (Windows & Linux) und gleitende Jitter-Glättung (EMA).
  - `test_upnp_client.py`: Session-Byte-Zähler und 32-Bit-Überlaufschutz.

### Changed
- **Aktualisierte Dokumentation & Struktur:** Der Dateibaum in der `README.md` spiegelt nun alle Module (`models.py`, `worker.py`, `local_traffic.py`, `net_health.py`, `formatters.py`, `icons.py`) wider und enthält eine Anleitung zur Ausführung der Testsuite.
- **Bereinigtes Arbeitsverzeichnis:** Temporäre Testskripte aus vorherigen Entwicklungsphasen in `local/` wurden sauber in `local/scratch/` einsortiert.

## [0.9.1] - 2026-11-04
### Fixed
- **Keine störende Tooltip-Überlagerung mehr über dem Diagramm:** Der allgemeine Fritz!Box-Verbindungsdetails-Tooltip (`Status: Connected • Externe IP...`) wurde vom Hauptfenster entkoppelt und gezielt an das Router-Icon, den Titel und die WAN-Status-Pille gebunden. Zudem unterdrückt die Diagrammfläche (`SplitTrafficGraphWidget`) Tooltip-Events, sodass das schwebende HUD-Badge bei der Messpunkt-Inspektion niemals verdeckt wird.
- **Bereinigtes HUD-Badge ohne PC-Emoji:** Das PC-Symbol (`💻`) wurde aus der HUD-Karte entfernt (`PC: ↓ ... • ↑ ...`) und die Badge-Breite erweitert, sodass auch hohe dreistellige Raten (wie `467,78 Mbit/s`) ohne Textabschneiden sauber und vollständig dargestellt werden.

## [0.9.0] - 2026-11-04
### Added
- **Lokaler PC-Traffic-Monitor (Eigener Internet-Anteil im Graphen):**
  - **Plattformunabhängig ohne Fremdbibliotheken:** Ermittelt den lokalen Netzwerkdurchsatz des Rechners auf Windows (native `iphlpapi.dll` via `ctypes`) und Linux (`/proc/net/dev`) rein über die Python-Standardbibliothek.
  - **Harmonische Farbkopplung:** Der eigene PC-Anteil leitet sich automatisch als dunklere Nuance der Hauptfarben ab (`color.darker(150)`), sodass bei einem Wechsel des Farbschemas alles perfekt abgestimmt bleibt.
  - **Smarte NAS-Filterung (Plausibilitäts-Clamp):** Der PC-Anteil wird an die gemessene Fritz!Box-WAN-Rate gedeckelt. Massive lokale Kopiervorgänge (z. B. 1 Gbit/s auf ein lokales NAS) verzerren den Internet-Graphen nicht und werden bei Bedarf mit `[LAN]` markiert.
  - **Standardmäßig deaktiviert (Default AUS):** Kann in den Einstellungen unter *Lokales Gerät (Eigener PC-Traffic Anteil)* aktiviert und separat für den Graphen-Layer und/oder die Textzeile unter den Raten zugeschaltet werden.
  - **HUD-Badge-Erweiterung:** Bei aktiver Überwachung zeigt die schwebende Hover-Infokarte im Diagramm auch den genauen PC-Anteil des gewählten Zeitpunkts (`💻 PC: ↓ ... ↑ ...`).

## [0.8.1] - 2026-11-04
### Removed
- **Header-Scrubbing (Variante 3):** Die oberen Raten- und Balkenanzeigen verbleiben nun auch beim Überfahren des Graphen mit der Maus stabil und ruhig auf den aktuellen Live-Echtzeitwerten. Die Detailinspektion historischer Punkte erfolgt fokussiert im Diagramm (Fadenkreuz, Kurven-Marker und schwebendes HUD-Badge).

### Added
- **Einstellbare Raten-Metaanzeigen für einen aufgeräumten Header:**
  - **Peak-Rate ausblendbar:** Unter *Einstellungen > Allgemein & Skalierung* kann die `Peak (60s): ...`-Anzeige deaktiviert werden, sodass lediglich der schlanke Prozentwert (`0,9%`) angezeigt wird.
  - **Gäste-WLAN-Zeile separat schaltbar:** Die Zeile `Gast: 0 bit/s` kann ausgeblendet werden, ohne die Gäste-WLAN-Überwachung oder die Online-Zähler-Erfassung im Hintergrund zu beeinträchtigen.

## [0.8.0] - 2026-11-04
### Added
- **Interaktive Messpunkt-Inspektion bei Mouse-Hover (Hybrid aus Fadenkreuz-HUD & Header-Scrubbing):**
  - **Oszilloskop-Fadenkreuz & Kurven-Pips:** Beim Überfahren des Graphen mit der Maus wird an der jeweiligen Zeitposition eine vertikale gestrichelte Cursorlinie eingeblendet und auf den Kurven (Down, Up sowie Ping/Jitter) leuchtet ein Marker-Dot (mit Akzentfarbe und weißem Zentrum) exakt am Kurvenpunkt auf.
  - **Schwebendes HUD-Badge (Card-Overlay):** Direkt neben dem Cursor erscheint eine transluzente, abgerundete Info-Karte im Widget-Design mit Zeitstempel (`[vor Xs]` bzw. `[Jetzt • Live]`), den Raten für Download und Upload sowie bei aktivem Ping-Monitor auch Latenz (`◆ Ping`) und Jitter (`▲ Jit`).
  - **Temporäres Header-Scrubbing:** Zeitgleich passen sich die oberen großen Ratenanzeigen (`Down [vor Xs]: ...` / `Up [vor Xs]: ...`) sowie die Auslastungsbalken dem historischen Zeitpunkt an.
  - **Nahtlose Rückkehr:** Sobald der Mauszeiger das Diagramm verlässt, schalten die Anzeigen verzögerungsfrei wieder auf die Live-Echtzeitwerte um.
  - **Ungestörtes Fenster-Verschieben:** Linksklick und Ziehen werden transparent an das Hauptfenster weitergeleitet, sodass das Widget weiterhin an jeder beliebigen Stelle gepackt und verschoben werden kann.

## [0.7.4] - 2026-11-04
### Changed
- **Volumen-Berechnung nach Fritz!OS SI-Standard (Dezimal GB/TB):** Die Zähler-Formatierung (`format_bytes`) wurde von Basis 1024 (GiB) auf Basis 1000 (Dezimal-GB / TB) umgestellt. Dadurch stimmen sämtliche Zählerstände (Heute, Gestern, Woche, Monat, Vormonat) nun auf die Nachkommastelle exakt mit der Fritz!Box Web-Oberfläche (`Internet > Online-Monitor > Online-Zähler`) überein.

## [0.7.3] - 2026-11-04
### Changed
- **Kompakte & intuitive Login-Statusmeldungen im Einstellungs-Dialog:**
  - Fehlversuch: `✕ Passwort falsch – Box pausiert für Xs`
  - Erneuter Klick während der Zwangspause: `⚠ Bitte noch Xs warten (Box blockiert noch)`
  - Erfolg: `✓ Login erfolgreich (Online-Zähler & Gäste-WLAN aktiv)`

## [0.7.2] - 2026-11-04
### Added
- **Button „Verbindung & Login testen“ in den Einstellungen:** Sofortige Live-Überprüfung von UPnP-Erreichbarkeit und Fritz!OS-Login mit präziser Rückmeldung (`✓ Login erfolgreich`, `✕ Passwort falsch`, `⚠ Fritz!Box Sperrzeit aktiv` oder `✕ Nicht erreichbar`).
- **Fritz!Box Account-Schutz & Backoff-Cooldown:** Erkennt die Fritz!Box `<BlockTime>`-Verzögerung. Nach einem Fehlversuch pausiert das Widget automatische Login-Wiederholungen für mindestens 30 Sekunden, wodurch eine Kontosperre oder ein endloses Anwachsen der Fritz!Box-Sperrzeit ausgeschlossen wird.
- **Klare Fehler-Rückmeldung in der Zähler-Ansicht:** Schlägt der Login fehl, zeigt die Zähler-Ansicht sofort den roten Hinweis `⚠ Fritz!OS Login fehlgeschlagen (Passwort in ⚙ Einstellungen prüfen)` statt still veraltete Werte einzufrieren.

## [0.7.1] - 2026-11-04
### Fixed
- **Echte ICMP-Ping-Latenz auf deutschem Windows:** Ein Umlaut-Encoding-Problem (`ü` in der Windows-`ping.exe`-Ausgabe mit OEM-Codepage `cp850`) führte zuvor zu einem unbemerkten Fallback auf einen TCP-Handshake (Port 443), wodurch die gemessene Ping-Zeit bei ~30 ms statt echter ~12–14 ms lag. Durch binäres Auslesen und `cp850`-Decodierung misst der Ping nun exakt die reelle ICMP-Latenz (z. B. ~12 ms zu `1.1.1.1`).
- **Verständliche Bezeichnungen im Einstellungs-Dialog:** Den Entwickler-Begriff „Footer-Pill“ durch allgemeinverständliches Deutsch ersetzt („Status- & Diagnose-Anzeige (Fußzeile)“, „WAN-Verbindungsstatus anzeigen“ und „Aktiven System-DNS-Server überwachen“).

## [0.7.0] - 2026-11-04
### Added
- **Barrierefreie Status- & Diagnose-Pills im 1-zeiligen Footer ("Calm UI"):**
  - **WAN-Status (`lbl_wan_pill`):** Zeigt den Status mit barrierefreien Formen und kontrastreichen Farben (Rot-Grün-Schwäche-optimiert): `✓ WAN OK` (Cyan `#00E5FF`), `⚠ Kein Sync` (Amber `#FFAB00`), `⚠ Kein Internet` (Amber `#FFAB00`) oder `✕ Box Offline` (Crimson `#FF5252`).
  - **Aktiver OS-DNS-Monitor (`lbl_dns_pill`):** Erkennt automatisch den aktuell vom Betriebssystem genutzten primären DNS-Server (über Windows-Registry / Linux `/etc/resolv.conf`) und misst live dessen Antwortzeit in Millisekunden per UDP Port 53.
- **Kombinierter Internet Ping- & Jitter-Graph:**
  - Drittes Diagramm-Band unterhalb von Download & Upload, das den echten Ping zu einem frei konfigurierbaren Endpoint (Standard `1.1.1.1`) sowie den berechneten Jitter (Latenzschwankung) in Echtzeit visualisiert.
  - Eindeutige Formen in der Legende (`◆ Ping` in Cyan `#00E5FF` und `▲ Jitter` in Amber `#FF9100`), `Min / Max`-Anzeige und abgerundete Live-Wert-Badges am rechten Graphenrand.
- **Neuer Einstellungs-Tab "Diagnose & Ping":** Sämtliche neuen Diagnose-Features (Ping-Graph, Endpoint-Auswahl, WAN-Pill, DNS-Monitor, Theme-Farben für Ping und Jitter) können individuell aktiviert und angepasst werden.

### Changed
- **Bereinigter Header:** Das passive Skalierungs-Badge (`√-Skala` / `Max-Fix`) oben neben den Tabs entfernt, sodass rechts im Header ausschließlich klickbare Elemente (`Graph`, `Zähler`, `⚙`) liegen.
- **Echtes Sync-Loss-Handling:** Raten-Anzeigen und Status erkennen nun zuverlässig, wenn der DSL-/Glasfaser-Sync verloren geht (`Kein Sync`) oder die Einwahl fehlt (`Kein Internet`), und setzen die Leitungskapazität korrekt zurück.

## [0.6.1] - 2026-11-04
### Added
- **Dynamische Schrift- & Elementskalierung:** Schriftgrößen, Verteilungs-Balkenhöhen, Pfeil-Icons und Auslastungsbalken passen sich nun dezent der aktuellen Fenstergröße an:
  - *Kompakt (`260–300 px`):* Zierliche 8–9 pt Schriften, 3–4 px feine Balken und kompakte Abstände.
  - *Groß (`> 600 px`):* Deutlich gewachsene Geschwindigkeitsraten (bis 15 pt), 11–12 pt Zähler-Beschriftungen und 6–7 px kräftigere Verteilungsbalken, sodass große Monitore harmonisch ausgefüllt werden.

## [0.6.0] - 2026-11-04
### Added
- **Maßgeschneiderte Vektor-Icons für View-Tabs:** Die Emojis in den Umschalt-Buttons durch elegante Vektor-Icons (Pulse-Kurve für `Graph`, 3 Säulen für `Zähler`) ersetzt, die dynamisch ihre Farbe an den aktiven/inaktiven Zustand anpassen.
- **Direkter Einstellungs-Button (`⚙`):** Ein dezenter Zahnrad-Button rechts im Header öffnet mit einem Klick direkt den Einstellungs-Dialog (ohne Rechtsklick-Umweg).

### Changed
- **Einheitlich kompakte Mindestbreite:** Die Mindestbreite für die Zähler-Ansicht wurde von 460 px auf 260 px gesenkt, sodass sich das Widget in beiden Ansichten (`Graph` & `Zähler`) gleich kompakt auf Widget-Größe zusammenschieben lässt.
- **Header-Responsive:** Das Skalierungs-Badge (`√-Skala`) wird bei sehr schmalen Fensterbreiten (< 320 px) automatisch ausgeblendet, um dem Titel Platz zu machen.

## [0.5.2] - 2026-11-04
### Changed
- **Kompakter Hover-Tooltip:** Die redundante Online-Zähler-Tabelle aus dem Hover-Tooltip des Widgets entfernt, da diese nun direkt über den `📊 Zähler`-Button im Widget dargestellt wird. Der Tooltip beschränkt sich nun übersichtlich auf Verbindungsstatus, Externe IP, Verbunden seit, Leitungskapazität und Sitzungs-Volumen.

## [0.5.1] - 2026-11-04
### Added
- **Elegante Card-Zeilen im Online-Zähler (Variante 2):** Zeitraum (`Heute`..`Vormonat`) links, Gesamtsumme (`Gesamt: X GB`) rechtsbündig oben, darunter ein feiner durchgehender 4px-Verteilungsbalken (`download_color` links, `upload_color` rechts) und darunter Download- & Upload-Werte mit passenden Vektor-Pfeilen.
- **Dynamische Vektor-Pfeile (`src/ui/icons.py`):** Neues Icon-Modul `create_arrow_pixmap()`, das schlanke, monochrome Pfeile mit `QPainter` pixelgenau in den konfigurierten Theme-Farben zeichnet.

### Changed
- **Windows-Emoji-Kästen eliminiert:** Alle klobigen Unicode-Emojis (`⬇`, `⬆`) im Header (`Down:`, `Up:`), Footer (`↓`, `↑`) und Tooltip durch scharfe Vektor-Icons bzw. saubere Schriftzeichen ersetzt.

## [0.5.0] - 2026-11-04
### Added
- **Visuelle Verteilungs-Balken (`Anteil ⬇ / ⬆`) im Online-Zähler:** Fünfte Spalte (`RatioBarWidget`) in `src/ui/online_counter_view.py` ergänzt, die für jeden Zeitraum (`Heute`, `Gestern`, `Aktuelle Woche`, `Aktueller Monat`, `Vormonat`) das Verhältnis von Download (Gelb) zu Upload (Blau) grafisch darstellt und bei breiter gezogenem Fenster zusätzlich die Prozentwerte (`% ⬇ / % ⬆`) einblendet.

### Changed
- **Harmonisches Responsive-Layout für beide Tabs (`📈 Graph` & `📊 Zähler`):** Spalten `0..3` passen sich kompakt ihrem Inhalt an (`ResizeToContents`), während die Balken-Spalte (`Stretch`) und die Zeilenhöhen (`verticalHeader().setSectionResizeMode(Stretch)`) dynamisch jede vom Nutzer gewählte Fenstergröße ausfüllen.

### Fixed
- Störende graue Einzelzellen-Markierung (Windows-11-Hover-/Fokus-Rechteck) in der Online-Zähler-Tabelle entfernt.

## [0.4.4] - 2026-11-03
### Docs
- Dokumentation der Standard-Speicherorte (`%APPDATA%` / `~/.config`) sowie des portablen Modus (`local/config.json`) in `README.md` ergänzt.

## [0.4.3] - 2026-11-03
### Removed
- Redundanten Kontextmenü-Eintrag `Ansicht: Online-Zähler anzeigen` entfernt, da die Umschaltung direkt über die Header-Buttons (`📈 Graph` | `📊 Zähler`) erfolgt.

## [0.4.2] - 2026-11-03
### Fixed
- Unterstützung für kompilierte Standalone-Binaries (`PyInstaller --onefile --windowed`) in `src/config.py` und `src/autostart.py` ergänzt (sicheres Logging ohne Konsole sowie direkter `.exe`-Pfad im Windows-Autostart).

## [0.4.1] - 2026-11-03
### Changed
- **Peak-Anzeige als gleitendes 60s-Maximum (`Peak (60s)`):** Der Peak-Wert bezieht sich jetzt automatisch auf das sichtbare Zeitfenster des Graphen (letzte 60 Sekunden) und setzt sich von selbst zurück, sobald eine Lastspitze aus dem Graphen herauswandert.
- **Verständliche Zähler-Bezeichnungen ohne Login:** Statt `Seit Sync (UPnP)` und `Widget-Session` heißen die Zähler nun selbsterklärend **`Seit Verbindung (2d 09h)`** (bzw. `Seit Router-Start`) und **`Seit Widget-Start`**.

## [0.4.0] - 2026-11-03
### Added
- Direkt-Umschalter im Widget-Header (`📈 Graph` | `📊 Zähler`) implementiert (`src/ui/online_counter_view.py` & `src/ui/widget.py`), mit dem sich die Hauptfläche des Widgets nahtlos zwischen dem Live-Graphen und der Online-Zähler-Tabelle (`Heute`, `Gestern`, `Aktuelle Woche`, `Aktueller Monat`, `Vormonat`) umschalten lässt.
- Intelligenter Fallback in der Zähler-Ansicht ohne Login: Zeigt `Widget-Session` und `Seit Sync (UPnP)` samt Direkt-Button zum Aktivieren des Fritz!OS-Logins in den Einstellungen.

## [0.3.0] - 2026-11-03
### Added
- Auslesen des offiziellen Fritz!Box **Online-Zählers** (`inetstat:status/Today`, `Yesterday`, `ThisWeek`, `ThisMonth`, `LastMonth` über `/query.lua` mit 64-Bit High/Low-Berechnung) in `src/api/fritz_monitor.py`.
- Umschaltbare Zeitraum-Anzeige im Widget-Footer (`Heute`, `Gestern`, `Aktuelle Woche`, `Aktueller Monat`, `Vormonat` oder `Widget-Session`) über die Einstellungen sowie das Rechtsklick-Kontextmenü (`Footer-Zähler`).
- Vollständige Online-Zähler-Tabelle (Gesamt, Gesendet, Empfangen für alle 5 Zeiträume) im Hover-Tooltip des Widgets.

## [0.2.2] - 2026-11-03
### Changed
- Zugangsdaten für den optionalen Gäste-WLAN-Monitor direkt in die Verbindungs-Sektion auf dem ersten Reiter (`Allgemein & Skalierung`) verschoben; zweiter Reiter enthält nun ausschließlich die Farbeinstellungen (`Farben`).

### Fixed
- Wiederherstellung der letzten Fenstergröße nach dem Beenden des Kompakt-Modus repariert (verhindert das Überschreiben der gespeicherten Höhe durch `resizeEvent` beim Ein-/Ausblenden des Graphen).
- Darstellung von `&`-Zeichen in Tab-Titeln, Gruppenrahmen und Checkboxen korrigiert (`&&` gegen Qt-Mnemonic-Verschlucken).

## [0.2.1] - 2026-11-03
### Changed
- Standard-Host der Fritz!Box in Code und `.env.example` auf `fritz.box` statt einer spezifischen lokalen IP-Adresse gesetzt.

## [0.2.0] - 2026-11-03
### Added
- Passwortfreier UPnP-SOAP-Client (`src/api/upnp_client.py`) für AVM FRITZ!Box über Port `49000` (`GetAddonInfos`, `GetCommonLinkProperties`, `GetStatusInfo`, `GetExternalIPAddress`) mit automatischer Endpunkt-Erkennung (`/igddesc.xml`).
- Optionaler authentifizierter Fritz!OS-Client (`src/api/fritz_monitor.py`) zur Abfrage des Gäste-WLAN-Anteils (`ds_guest_bps` / `us_guest_bps` via `login_sid.lua` v2 PBKDF2 & `netMoni`).
- Rahmenloses, transparentes Cross-Platform Desktop-Widget (`src/ui/widget.py`) auf Basis von PySide6 (Qt6) für CachyOS (KDE Plasma) und Windows.
- Pflicht-Feature: Live-Auslastungsanzeige in Prozent (`%`), Auslastungs-Fortschrittsbalken und Peak-Raten-Tracking relativ zur Leitungskapazität.
- Split-Area-Echtzeitgraph (`src/ui/graph_canvas.py`) mit drei umschaltbaren Skalierungs-Modi: Wurzel-Skala (`sqrt`), Dynamisch (`dynamic`) und Fix auf Leitungskapazität (`fixed`) sowie separater Gäste-WLAN-Kurveneinfärbung.
- Umfangreicher Einstellungs-Dialog (`src/ui/settings_dlg.py`), System-Tray-Integration (`src/ui/tray.py`) und plattformübergreifender Autostart (`src/autostart.py`).
- Start-Skripte für Windows (`start_windows.vbs`) und Linux/CachyOS (`start_linux.sh`).

## [0.1.0] - 2026-11-03
### Added
- Initiales Projekt-Setup aus dem Basis-Template erstellt (`traffic-box`).
