# Projekt: HRV-Messsoftware für Polar H7 unter Linux Mint

Ich möchte eine eigene, kostenlose HRV-Messsoftware in Python entwickeln, die unter **Linux Mint (Ubuntu-24.04-Basis)** läuft.

Die Software wird für meine Bachelorarbeit im Bereich Elektrotechnik-Toningenieurwesen verwendet. Ich untersuche, wie sich vibrotaktile Stimulation beim Musikhören auf das emotionale Erleben, die Immersion und physiologische Parameter auswirkt.

Dazu möchte ich mit einem **Polar H7 Brustgurt** die Herzfrequenz und insbesondere die **RR-Intervalle** aufzeichnen und anschließend die Herzratenvariabilität (HRV) wissenschaftlich auswerten.

## 1. Technische Anforderungen

- Betriebssystem: Linux Mint, Ubuntu-24.04-Basis
- Programmiersprache: Python 3.12
- Sensor: Polar H7
- Verbindung: Bluetooth Low Energy (BLE), Linux BlueZ
- Bluetooth-Bibliothek: **BleakHeart** (basierend auf Bleak)
- GitHub: https://github.com/fsmeraldi/bleakheart
- Installation in einer isolierten Python-Umgebung (`venv`)
- Keine kommerzielle Software oder Cloud-Dienste erforderlich

Verwende die aktuelle, dokumentierte BleakHeart-API und orientiere dich an den offiziellen Beispielen. Erfinde keine API-Funktionen.

Der Polar H7 unterstützt die Übertragung von Herzfrequenz und RR-Intervallen. Er bietet jedoch keine Roh-EKG-Aufzeichnung wie der Polar H10. Implementiere daher ausschließlich Funktionen, die mit dem H7 tatsächlich verfügbar sind.

## 2. Bluetooth-Verbindung

Implementiere:

1. Automatische Suche nach BLE-Herzfrequenzsensoren.
2. Anzeige gefundener Geräte mit Gerätename und Kennung.
3. Auswahl und Verbindung mit dem Polar H7.
4. Anzeige des aktuellen Verbindungsstatus.
5. Verarbeitung der Bluetooth-Benachrichtigungen mit BleakHeart.
6. Erkennung von Verbindungsabbrüchen.
7. Kontrollierte Wiederverbindung ohne Verlust bereits gespeicherter Daten.
8. Verständliche Fehlermeldungen, wenn das Gerät nicht gefunden wird oder keine RR-Intervalle überträgt.

Die Anwendung darf nicht abstürzen, wenn Bluetooth vorübergehend ausfällt.

## 3. Live-Messung

Während der Aufzeichnung möchte ich folgende Werte sehen:

- Aktuelle Herzfrequenz in BPM
- Letztes empfangenes RR-Intervall in Millisekunden
- Verlauf der RR-Intervalle über die Zeit
- Laufende Messdauer
- Anzahl empfangener RR-Intervalle
- Bluetooth-Verbindungsstatus

Erstelle eine übersichtliche grafische Benutzeroberfläche für Linux, beispielsweise mit PySide6 und PyQtGraph. Die Messung muss auch bei vorübergehend geschlossener oder verzögerter grafischer Darstellung zuverlässig gespeichert werden.

## 4. Datenaufzeichnung

Implementiere Start-, Stopp- und Speicherfunktionen.

Speichere die Rohdaten in einer CSV-Datei.

Mindestens folgende Informationen sollen vorhanden sein:

- Versuchsperson-ID
- Session-ID
- Laufende Messnummer
- Zeitstempel
- Relative Zeit seit Messbeginn
- RR-Intervall in Millisekunden
- Herzfrequenz in BPM, soweit verfügbar
- Aktuelle Versuchsbedingung
- Eventuelle Qualitätskennzeichnung

Wichtig: Ein BLE-Paket kann mehrere RR-Intervalle enthalten. Speichere jedes RR-Intervall einzeln und in der richtigen Reihenfolge.

Unterscheide zwischen dem Empfangszeitpunkt des BLE-Pakets und einem rekonstruierten Herzschlagzeitpunkt. Kennzeichne die Zeitstempel entsprechend und behaupte keine höhere zeitliche Präzision, als technisch verfügbar ist.

Die Rohdaten dürfen niemals automatisch geglättet, interpoliert oder gelöscht werden.

## 5. Versuchsbedingungen markieren

Für meine Bachelorarbeit möchte ich während einer laufenden Messung verschiedene Bedingungen markieren:

- Baseline
- Music only
- Music + Vibration
- Rest
- Freie Anmerkung

Ich möchte diese Bedingungen während der Messung über Buttons oder Tastenkürzel auswählen können.

Jedes Ereignis soll einen Zeitstempel erhalten und in einer separaten Event-Datei gespeichert werden.

Die Messung der RR-Intervalle muss dabei ohne Unterbrechung weiterlaufen.

## 6. HRV-Auswertung

Implementiere eine separate Analysefunktion für gespeicherte CSV-Dateien.

Berechne zunächst:

- Mittlere Herzfrequenz
- Mittleres NN-Intervall
- SDNN
- RMSSD
- pNN50

Verwende für die Berechnung geeignete Python-Bibliotheken wie NumPy, Pandas und gegebenenfalls NeuroKit2.

Erstelle außerdem eine grafische Darstellung der RR-Intervalle.

Implementiere eine nachvollziehbare Artefakterkennung, die auffällige RR-Intervalle markiert.

Wichtige Anforderungen:

- Rohdaten unverändert erhalten.
- Artefakte kennzeichnen, nicht unbemerkt löschen.
- Anteil auffälliger Intervalle ausgeben.
- Die angewendete Artefaktkorrektur dokumentieren.
- Rohwerte und korrigierte Werte unterscheiden.
- Bei unzureichender Datenqualität keine scheinbar zuverlässigen HRV-Ergebnisse ausgeben.
- Frequenzbasierte HRV-Werte nur berechnen, wenn Messdauer und Datenqualität dafür geeignet sind.

## 7. Export

Für jede Messung sollen folgende Dateien erzeugt werden können:

1. `raw_rr.csv` – unveränderte RR-Intervalle
2. `events.csv` – Zeitpunkte der Versuchsbedingungen
3. `metadata.json` – Versuchsperson, Sensor, Einstellungen, Beginn und Ende
4. `hrv_results.csv` – berechnete HRV-Kennwerte
5. `rr_plot.png` – grafische Darstellung der Intervalle

Alle Dateien sollen in einem eindeutig benannten Session-Ordner gespeichert werden.

## 8. Softwarestruktur

Erstelle eine übersichtliche und wartbare Projektstruktur mit getrennten Modulen für:

- Bluetooth-Kommunikation
- Rohdatenaufzeichnung
- Grafische Benutzeroberfläche
- Ereignismarkierungen
- Artefakterkennung
- HRV-Analyse
- CSV-Export

Verwende ein sauberes Logging-System und vermeide das unbeabsichtigte Überschreiben vorhandener Messdateien.

## 9. Installation und Dokumentation

Erstelle:

- `requirements.txt` oder `pyproject.toml`
- Installationsanleitung für Linux Mint
- Automatische Einrichtung einer virtuellen Python-Umgebung
- Startskript
- README mit Bedienungsanleitung
- Beschreibung aller gespeicherten Spalten und Einheiten
- Anleitung zur Bluetooth-Fehlerbehebung

Die Software soll möglichst ohne Administratorrechte laufen. Verwende keine unnötigen Änderungen an den Bluetooth-Systemdiensten.

## 10. Tests und Validierung

Implementiere einen Simulationsmodus, mit dem ich die Benutzeroberfläche und Datenspeicherung ohne Polar H7 testen kann.

Erstelle automatisierte Tests für:

- Verarbeitung mehrerer RR-Intervalle pro BLE-Benachrichtigung
- CSV-Export
- Ereignismarkierungen
- Verbindungsabbrüche
- Berechnung von RMSSD und SDNN anhand bekannter Testdaten
- Artefakterkennung

Unterscheide in der Dokumentation zwischen softwareseitig getesteten Funktionen und Funktionen, die erst mit einem echten Polar H7 überprüft werden können.

## Ziel

Ich möchte eine zuverlässige, reproduzierbare HRV-Messsoftware für meine Bachelorarbeit erhalten.

Priorität haben:

1. Zuverlässiger Empfang der RR-Intervalle vom Polar H7
2. Verlustfreie Speicherung der Rohdaten
3. Korrekte Zeitstempel und Ereignismarkierungen
4. Übersichtliche Live-Anzeige
5. Nachvollziehbare wissenschaftliche HRV-Auswertung

Bitte beginne mit der Prüfung der BleakHeart-Dokumentation und einer funktionsfähigen Minimalversion, die den Polar H7 verbindet und RR-Intervalle aufzeichnet. Erweitere diese anschließend schrittweise um die grafische Oberfläche und Analysefunktionen.

Erstelle die tatsächlichen Projektdateien und teste den Code, soweit die Ausführungsumgebung es erlaubt. Beschränke dich nicht auf eine konzeptionelle Beschreibung.