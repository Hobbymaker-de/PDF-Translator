# Programmablauf

Das Diagramm zeigt die beiden Startwege (GUI und CLI) und den gemeinsamen Kern `translate_pdf()`.

```mermaid
flowchart TD
    Start([python pdf_translator.py]) --> Import

    subgraph Init["Beim Import (einmalig)"]
        Import["Modelle-Pfad setzen<br/>ARGOS_PACKAGES_DIR"] --> Patch["stanza.Pipeline patchen<br/>download_method = NONE"]
    end

    Patch --> Main["main(): Argumente lesen"]
    Main --> Mode{"--cli gesetzt?"}

    Mode -- "Ja" --> CliPdf{"PDF angegeben?"}
    CliPdf -- "Nein" --> Err1(["Fehler: PDF fehlt"])
    CliPdf -- "Ja" --> Cli["cli(): Ausgabe = PDF_de.txt<br/>oder --out"]
    Cli --> Core

    Mode -- "Nein" --> Gui["gui(): Fenster aufbauen<br/>Sprachliste aus installierten Modellen"]
    Gui --> Input["Nutzer wählt PDF und Sprache"]
    Input --> Save["Speicherdialog"]
    Save --> Thread["Hintergrundthread: worker()"]
    Thread --> Core

    subgraph Core["translate_pdf()"]
        direction TB
        C1["Alle Seiten lesen<br/>pdf_paragraphs() je Seite"] --> C2{"Text vorhanden?"}
        C2 -- "Nein" --> Err2(["ValueError: kein Text"])
        C2 -- "Ja" --> C3{"Quellsprache = auto?"}
        C3 -- "Ja" --> C4["langdetect erkennt Sprache<br/>(erste 3000 Zeichen)"]
        C3 -- "Nein" --> C5
        C4 --> C5{"Modell Quelle → de<br/>installiert?"}
        C5 -- "Nein" --> Err3(["ValueError: kein Modell"])
        C5 -- "Ja" --> C6["Absätze übersetzen<br/>(Argos, offline)"]
        C6 --> C7["Textdatei schreiben<br/>mit --- Seite n ---"]
    end

    C1 -. "report()" .-> Prog
    C4 -. "report()" .-> Prog
    C6 -. "report()" .-> Prog

    subgraph GuiEvents["Nur GUI"]
        Prog["Warteschlange (events)"] --> Poll["poll() alle 100 ms<br/>Fortschritt / Fertig / Fehler"]
    end

    C7 --> Done(["Ausgabedatei fertig"])
    Core -. "Exception" .-> Thread
    Thread -. "error-Ereignis" .-> Poll
```

## Erläuterungen

- **Stanza-Patch:** Läuft einmal beim Import, bevor Argos Stanza nutzt. Deshalb wirkt er in CLI und GUI gleich.
- **`translate_pdf()` ist der gemeinsame Kern.** CLI und GUI rufen dieselbe Funktion auf. Sie unterscheiden sich nur in der Art der Fortschrittsmeldung (`report`): Die CLI druckt, die GUI legt in die Warteschlange.
- **Die GUI arbeitet mit zwei Threads:** Die Übersetzung läuft im Hintergrund, die Oberfläche wird nur von `poll()` im Hauptthread aktualisiert. Dadurch friert das Fenster während der Übersetzung nicht ein.
