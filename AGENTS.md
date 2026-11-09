# Repository Guidelines

## Projektstruktur

Baue die Anwendung schrittweise auf: zuerst eine minimale, getestete Polar-H7-Verbindung mit RR-Aufzeichnung, danach Oberfläche und Analyse. Trenne BLE-Kommunikation, Aufzeichnung/Export, GUI, Ereignisse, Artefakterkennung und HRV-Analyse in eigene Module. Geeignete Verzeichnisse sind `src/`, `tests/`, `docs/` und `notebooks/`; halte GUI-unabhängige Messlogik in `src/`. Notebooks dienen Exploration, nicht als einzige Implementierung reproduzierbarer Berechnungen.

## Plattform und Abhängigkeiten

Zielplattform ist Linux Mint auf Ubuntu-24.04-Basis mit Python 3.12. Entwickle in einer virtuellen Umgebung und bevorzuge kostenlose lokale Bibliotheken. Für BLE ist BleakHeart gemäß aktueller offizieller Dokumentation und Beispiele zu verwenden. Prüfe vor Änderungen dessen tatsächlich verfügbare API; erfinde keine Methoden. Der Polar H7 liefert Herzfrequenz und RR-Intervalle, aber kein Roh-EKG. Vermeide unnötige Änderungen an BlueZ-Systemdiensten und verlange möglichst keine Administratorrechte.

## Messdaten und Zeitbezug

Behandle empfangene RR-Werte als Rohdaten: niemals automatisch glätten, interpolieren, überschreiben oder löschen. Ein BLE-Paket kann mehrere Intervalle enthalten; schreibe jedes einzeln und in Empfangsreihenfolge. Dokumentiere Einheiten und unterscheide Paketempfangszeit von rekonstruiertem Herzschlagzeitpunkt. Speichere Messungen in eindeutigen Session-Ordnern mit `raw_rr.csv`, `events.csv`, `metadata.json` und Analyseexporten; überschreibe keine vorhandenen Messungen. Bedingungswechsel müssen unabhängig vom BLE-Empfang mit Zeitstempel protokolliert werden.

## Stil, Tests und Entwicklung

Verwende Python 3.12, vier Leerzeichen Einrückung, `snake_case` für Module/Funktionen/Variablen und `CapWords` für Klassen. Halte Module klein und annotiere öffentliche Funktionen. Ergänze automatisierte Tests für Mehrfach-RR-Pakete, CSV- und Event-Export, Verbindungsabbrüche, bekannte SDNN-/RMSSD-Werte sowie Artefaktkennzeichnung. Ein Simulationsmodus muss GUI und Speicherung ohne Sensor prüfen lassen. Führe die Tests mit `python -m unittest discover -s tests -v` aus (`python -m pytest` ist optional); dokumentiere tatsächliche Start- und Installationsbefehle in README und `pyproject.toml` oder `requirements.txt`.

## Wissenschaftliche Auswertung und Beiträge

Kennzeichne Artefakte nachvollziehbar, bewahre Rohwerte und weise korrigierte Werte getrennt aus. Gib Qualitätsmängel und den Artefaktanteil an; berechne keine scheinbar verlässlichen Kennwerte bei unzureichenden Daten. Frequenzbasierte Kennwerte nur bei geeigneter Dauer und Qualität ausgeben. Dokumentiere, was simuliert bzw. softwareseitig getestet wurde und was einen echten Polar H7 erfordert. Commits erhalten kurze imperative Betreffzeilen; Pull Requests beschreiben Änderung, Validierung und gegebenenfalls reale Sensortests. Keine Zugangsdaten, identifizierenden Versuchspersonendaten oder sensiblen Rohmessungen einchecken.
