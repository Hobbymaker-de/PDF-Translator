# PDF-Übersetzer (nach Deutsch)

Ein Offline-Werkzeug, das Text aus PDF-Dateien extrahiert und ihn mit lokalen Übersetzungsmodellen nach Deutsch übersetzt. Es werden keine Daten ins Internet gesendet. Das Ergebnis wird als Textdatei (`.txt`) gespeichert.

## Funktionen

- Grafische Oberfläche (Tkinter) mit Dateiauswahl, Sprachauswahl und Fortschrittsanzeige
- Kommandozeilenmodus für Stapelverarbeitung oder Automatisierung
- Automatische Erkennung der Ausgangssprache (`langdetect`), oder manuelle Auswahl
- Übersetzung mit [Argos Translate](https://www.argosopentech.com/), vollständig offline
- Ausgabe mit Seitenmarkierungen (`--- Seite n ---`); Seiten ohne erkennbaren Text werden gemeldet

## Voraussetzungen

- Windows (die fertige `.exe` wird für Windows gebaut)
- Python 3.13 (das Projekt wurde mit 3.13 getestet)

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Übersetzungsmodelle laden

Die Übersetzungsmodelle werden nicht mit dem Repository mitgeliefert. Einmalig herunterladen:

```powershell
python download_models.py
```

Das Skript lädt alle verfügbaren Argos-Pakete in den Ordner `models/argos/`. Dafür ist eine Internetverbindung nötig. Danach arbeitet das Programm offline.

Die Modelle eines Sprachpaars müssen nach Deutsch vorhanden sein (z. B. `en_de`, `el_de`, `ru_de`). Nur installierte Sprachen erscheinen in der Auswahl.

## Verwendung

### Grafische Oberfläche

```powershell
python pdf_translator.py
```

1. PDF-Datei über „Durchsuchen …“ auswählen.
2. Ausgangssprache wählen (oder „Automatisch erkennen“).
3. „Übersetzen“ klicken und Speicherort wählen.

### Kommandozeile

```powershell
python pdf_translator.py --cli datei.pdf
python pdf_translator.py --cli datei.pdf --source en --out ergebnis.txt
```

| Option | Beschreibung |
| --- | --- |
| `--cli` | ohne Oberfläche ausführen |
| `--source` | Ausgangssprache als Code (z. B. `en`, `el`, `ru`) oder `auto` (Standard) |
| `--out` | Ausgabedatei; Standard ist `<PDF-Name>_de.txt` neben der PDF |

## Eine .exe bauen

```powershell
pyinstaller PDF-Translator.spec
```

Das Ergebnis liegt in `dist\PDF-Translator\`. Der Ordner `models\argos` wird beim Bauen mit eingepackt, daher vorher `download_models.py` ausführen.

## Projektstruktur

| Datei / Ordner | Inhalt |
| --- | --- |
| `pdf_translator.py` | Hauptprogramm (GUI und CLI) |
| `download_models.py` | Lädt die Argos-Übersetzungsmodelle |
| `PDF-Translator.spec` | PyInstaller-Konfiguration für die `.exe` |
| `requirements.txt` | Python-Abhängigkeiten |
| `models/argos/` | Lokale Übersetzungsmodelle |
| `tests/` | Testskripte und Beispiel-PDFs (`tests/samples/`) |

## Einschränkungen

- **Gescannte PDFs** werden nicht per OCR gelesen. Enthält eine Seite nur ein Bild, bleibt sie leer und wird als „Seite ohne Text“ gemeldet. Die Testdateien mit `_scan` im Namen zeigen diesen Fall.
- Die Qualität hängt vom jeweiligen Argos-Modell ab.
- Die Spaltenstruktur des PDFs geht teilweise verloren, da Absätze aus dem reinen Textfluss gebildet werden.

## Abhängigkeiten

| Paket | Version | Zweck |
| --- | --- | --- |
| [PyMuPDF](https://pymupdf.readthedocs.io/) | 2.1 | Text aus PDFs lesen |
| [langdetect](https://github.com/Mimino666/langdetect) | 1.0.9 | Sprache erkennen |
| [Argos Translate](https://github.com/argosopentech/argos-translate) | 1.11.0 | Offline-Übersetzung |
| [PyInstaller](https://pyinstaller.org/) | 6.22.3 | `.exe` bauen (optional) |
