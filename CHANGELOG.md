# Changelog

Alle relevanten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.
Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

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
