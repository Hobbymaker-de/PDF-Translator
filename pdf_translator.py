"""PDF-Übersetzer nach Deutsch.

Liest den Text aus PDF-Dateien und übersetzt ihn offline mit Argos Translate.
Das Programm hat zwei Betriebsarten:

- GUI (Tkinter), Standard: ``python pdf_translator.py``
- Kommandozeile: ``python pdf_translator.py --cli datei.pdf``
"""

import argparse
import os
import queue
import re
import sys
import threading
from pathlib import Path


def app_dir() -> Path:
    """Gibt den Ordner zurück, in dem das Programm liegt.

    Bei der fertigen .exe (PyInstaller, eingefroren) ist das der Ordner der EXE.
    Im normalen Python-Betrieb ist es der Ordner dieser Datei.
    Davon hängt ab, wo der Ordner ``models`` gesucht wird.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


MODELS = app_dir() / "models"
# Argos sucht seine Sprachpakete über diese Umgebungsvariable. Sie muss gesetzt
# sein, bevor argostranslate importiert wird.
os.environ["ARGOS_PACKAGES_DIR"] = str(MODELS / "argos")

# Die .exe wird ohne Konsole gebaut (console=False). Dann gibt es kein stdout
# und kein stderr (None). Ohne Ersatz würde jede Ausgabe (z. B. von Bibliotheken)
# mit einem Fehler abbrechen. Ersatz ist ein Null-Gerät, die Ausgabe wird verworfen.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import pymupdf  # noqa: E402
from langdetect import DetectorFactory, detect  # noqa: E402
import argostranslate.translate as tr  # noqa: E402
import stanza  # noqa: E402

# Argos nutzt für die Satztrennung Stanza. Stanza lädt beim Erstellen einer
# Pipeline standardmäßig die aktuelle resources.json von GitHub, auch wenn alle
# Modelle lokal vorliegen. Ohne Netz bricht das ab. Der Patch unten setzt den
# Standard auf NONE, also keine Online-Abfrage. Ein beim Aufruf explizit
# übergebener Wert hat weiterhin Vorrang (setdefault).
_stanza_pipeline = stanza.Pipeline


def _offline_pipeline(*args, **kwargs):
    """Ersetzt ``stanza.Pipeline`` und setzt ``download_method=NONE``, falls nichts angegeben ist."""
    kwargs.setdefault("download_method", stanza.DownloadMethod.NONE)
    return _stanza_pipeline(*args, **kwargs)


stanza.Pipeline = _offline_pipeline

# Seed für langdetect. Ohne festen Seed kann die Spracherkennung bei gleichem
# Text leicht unterschiedliche Ergebnisse liefern.
DetectorFactory.seed = 0

AUTO = "auto"
AUTO_LABEL = "Automatisch erkennen"
# Zielsprache ist immer Deutsch (Argos-Code).
TARGET = "de"
# langdetect verwendet teils andere Codes als Argos. Diese Tabelle übersetzt
# die erkannten Codes in die Argos-Codes.
LANGDETECT_MAP = {"zh-cn": "zh", "zh-tw": "zt", "no": "nb"}


def installed_sources() -> dict[str, tr.Language]:
    """Ermittelt alle Ausgangssprachen, aus denen ins Deutsche übersetzt werden kann.

    Es werden nur Sprachen zurückgegeben, für die ein Übersetzungspaket
    nach Deutsch installiert ist. Deutsch selbst wird übersprungen.

    Rückgabe: Dictionary Sprachcode -> Argos-Language-Objekt.
    Ist Deutsch nicht installiert, ist das Dictionary leer.
    """
    langs = {lang.code: lang for lang in tr.get_installed_languages()}
    target = langs.get(TARGET)
    if target is None:
        return {}
    result = {}
    for code, lang in langs.items():
        if code == TARGET:
            continue
        # get_translation gibt nur dann ein Ergebnis, wenn lang -> de existiert.
        if lang.get_translation(target) is not None:
            result[code] = lang
    return result


def pdf_paragraphs(page) -> list[str]:
    """Liest den Text einer PDF-Seite und teilt ihn in Absätze auf.

    Ablauf:
    1. Silbentrennung am Zeilenende aufheben: ``Über-\\nsetzung`` wird zu
       ``Übersetzung``. Der Bindestrich wird nur entfernt, wenn direkt ein
       Buchstabe/Ziffer folgt.
    2. Text an Leerzeilen in Absätze teilen.
    3. Innerhalb eines Absatzes Zeilenumbrüche und Mehrfachleerzeichen durch
       je ein Leerzeichen ersetzen. Die Übersetzung arbeitet so mit ganzen Sätzen.
    4. Leere Absätze verwerfen.

    Rückgabe: Liste der Absätze der Seite (kann leer sein, z. B. bei Scans).
    """
    text = re.sub(r"-\n(?=\w)", "", page.get_text("text"))
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return [p for p in paragraphs if p]


def translate_pdf(pdf: Path, source: str, out: Path, report) -> Path:
    """Übersetzt eine komplette PDF und schreibt das Ergebnis in eine Textdatei.

    Ablauf:
    1. Alle Seiten lesen und Absätze extrahieren. Seiten ohne Text werden gemerkt.
    2. Bei ``source == "auto"`` die Sprache des gesamten Textes erkennen
       (nur die ersten 3000 Zeichen, das reicht für die Erkennung).
    3. Prüfen, ob ein Übersetzungspaket ``Quelle -> Deutsch`` vorhanden ist.
       Sonst wird ein Fehler ausgelöst.
    4. Jeden Absatz übersetzen und mit ``--- Seite n ---`` als Trennung
       in die Ausgabedatei schreiben.

    Parameter:
        pdf: Pfad zur PDF-Datei.
        source: Sprachcode der Ausgangssprache oder ``"auto"``.
        out: Pfad der zu schreibenden Textdatei.
        report: Callback ``report(erledigt, gesamt, nachricht)`` für den Fortschritt.
            Die GUI und die CLI geben ihn unterschiedlich aus.

    Rückgabe: Tupel aus Ausgabepfad und Liste der Seitennummern ohne Text.
    (Die Typangabe ``-> Path`` oben stimmt nicht genau, das Ergebnis ist ein Tupel.)

    Fehler: ``ValueError``, wenn kein Text gefunden wurde oder kein passendes
    Übersetzungsmodell installiert ist.
    """
    sources = installed_sources()
    doc = pymupdf.open(pdf)
    total = len(doc)

    # Schritt 1: Text aller Seiten sammeln. Zwischenstand melden,
    # damit die Fortschrittsanzeige weiterläuft.
    pages: list[list[str]] = []
    empty_pages = []
    for i, page in enumerate(doc):
        report(i, total, f"Text lesen: Seite {i + 1} von {total}")
        paragraphs = pdf_paragraphs(page)
        if not paragraphs:
            empty_pages.append(i + 1)
        pages.append(paragraphs)
    doc.close()

    # Ist das ganze Dokument leer (z. B. ein reiner Scan), gibt es nichts
    # zu übersetzen. Dann wird abgebrochen.
    all_text = " ".join(p for paras in pages for p in paras)
    if not all_text.strip():
        raise ValueError("Im PDF wurde kein Text gefunden.")

    # Schritt 2: Quellsprache bestimmen. Bei "auto" wird erkannt, sonst
    # wird der übergebene Code verwendet.
    if source == AUTO:
        code = detect(all_text[:3000])
        src_code = LANGDETECT_MAP.get(code, code)
        report(total, total, f"Erkannte Sprache: {src_code}")
    else:
        src_code = source

    # Schritt 3: Passendes Übersetzungspaket suchen. ``translation`` ist das
    # eigentliche Übersetzungsobjekt von der Quellsprache ins Deutsche.
    src = sources.get(src_code)
    if src is None:
        raise ValueError(
            f"Kein Übersetzungsmodell für Sprache '{src_code}' nach Deutsch vorhanden."
        )
    translation = src.get_translation(next(l for l in tr.get_installed_languages() if l.code == TARGET))

    # Schritt 4: Seite für Seite übersetzen. Die Ausgabe ist eine Textdatei
    # mit Seitenüberschriften und einer Leerzeile nach jedem Absatz.
    lines = []
    for i, paragraphs in enumerate(pages, 1):
        report(i - 1, total, f"Übersetze Seite {i} von {total}")
        lines.append(f"--- Seite {i} ---")
        lines.append("")
        for p in paragraphs:
            lines.append(translation.translate(p))
            lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    report(total, total, "Fertig")
    return out, empty_pages


def cli(args) -> None:
    """Führt die Übersetzung im Kommandozeilenmodus aus.

    Ermittelt den Ausgabepfad (Standard: ``<PDF-Name>_de.txt`` neben der PDF),
    gibt den Fortschritt als Textzeilen aus und meldet am Ende die Ausgabedatei
    sowie Seiten ohne Text.
    """
    pdf = Path(args.pdf)
    out = Path(args.out) if args.out else pdf.with_name(pdf.stem + "_de.txt")

    def report(done, total, msg):
        """Schreibt eine Fortschrittszeile auf die Konsole. ``flush`` sorgt für sofortige Ausgabe."""
        print(f"[{done}/{total}] {msg}", flush=True)

    out, empty = translate_pdf(pdf, args.source, out, report)
    print("Ausgabe:", out)
    if empty:
        print("Seiten ohne Text:", empty)


def gui() -> None:
    """Startet die grafische Oberfläche (Tkinter).

    Aufbau: Dateiauswahl, Sprachauswahl, Fortschrittsbalken, Statuszeile und
    Startknopf. Tkinter darf nur im Hauptthread laufen. Deshalb wird die
    Übersetzung in einem Hintergrundthread ausgeführt. Der Thread meldet sich
    über eine Warteschlange (``events``). Die Funktion ``poll`` liest diese
    Warteschlange regelmäßig aus und aktualisiert die Oberfläche.
    """
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    sources = installed_sources()
    # Auswahlliste: Erst "Automatisch erkennen", dann alle installierten
    # Sprachen alphabetisch nach Name. Jeder Eintrag ist (Anzeigename, Code).
    choices = [(AUTO_LABEL, AUTO)] + sorted(
        ((lang.name, code) for code, lang in sources.items()), key=lambda x: x[0].lower()
    )

    root = tk.Tk()
    root.title("PDF-Übersetzer (nach Deutsch)")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=14)
    frame.grid()

    # Variablen, die an die Widgets gebunden sind. Ändert sich der Wert, passt
    # sich das Widget automatisch an.
    pdf_var = tk.StringVar()
    lang_var = tk.StringVar(value=choices[0][0])
    status_var = tk.StringVar(value="Bereit")
    # Warteschlange für Nachrichten vom Hintergrundthread an die Oberfläche.
    events: queue.Queue = queue.Queue()

    def pick_pdf():
        """Öffnet den Dateidialog für die PDF-Auswahl und speichert den Pfad."""
        path = filedialog.askopenfilename(
            title="PDF auswählen", filetypes=[("PDF-Dateien", "*.pdf")]
        )
        if path:
            pdf_var.set(path)

    ttk.Label(frame, text="PDF-Datei:").grid(row=0, column=0, sticky="w")
    ttk.Entry(frame, textvariable=pdf_var, width=60, state="readonly").grid(row=1, column=0, sticky="we", pady=(2, 6))
    ttk.Button(frame, text="Durchsuchen …", command=pick_pdf).grid(row=1, column=1, padx=(8, 0))

    ttk.Label(frame, text="Ausgangssprache:").grid(row=2, column=0, sticky="w", pady=(8, 0))
    combo = ttk.Combobox(frame, textvariable=lang_var, state="readonly", width=57,
                         values=[label for label, _ in choices])
    combo.grid(row=3, column=0, sticky="we", pady=(2, 6))

    progress = ttk.Progressbar(frame, mode="determinate", length=460)
    progress.grid(row=4, column=0, columnspan=2, sticky="we", pady=(6, 0))
    ttk.Label(frame, textvariable=status_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 10))

    start_btn = ttk.Button(frame, text="Übersetzen")
    start_btn.grid(row=6, column=0, columnspan=2)

    def report(done, total, msg):
        """Fortschritts-Callback für ``translate_pdf``. Läuft im Hintergrundthread.

        Legt die Meldung nur in die Warteschlange. Die Oberfläche wird
        ausschließlich von ``poll`` im Hauptthread aktualisiert.
        """
        events.put(("progress", done, total, msg))

    def worker(pdf, code, out):
        """Führt die Übersetzung im Hintergrundthread aus.

        Ergebnis oder Fehler werden als Ereignis in die Warteschlange gelegt.
        Ein Absturz im Thread würde sonst unbemerkt bleiben.
        """
        try:
            out, empty = translate_pdf(pdf, code, out, report)
            events.put(("done", out, empty))
        except Exception as exc:
            events.put(("error", str(exc)))

    def start():
        """Wird beim Klick auf „Übersetzen“ ausgeführt.

        Prüft die Eingaben, fragt den Speicherort ab und startet den
        Hintergrundthread. Der Startknopf wird währenddessen deaktiviert,
        damit nicht parallel zwei Übersetzungen laufen.
        """
        if not pdf_var.get():
            messagebox.showwarning("Hinweis", "Bitte zuerst eine PDF-Datei auswählen.")
            return
        # Anzeigename der Sprache in den Code umwandeln, z. B. "Griechisch" -> "el".
        code = dict(choices).get(lang_var.get(), AUTO)
        pdf = Path(pdf_var.get())
        out_path = filedialog.asksaveasfilename(
            title="Übersetzung speichern unter",
            initialdir=str(pdf.parent),
            initialfile=pdf.stem + "_de.txt",
            defaultextension=".txt",
            filetypes=[("Textdatei", "*.txt")],
        )
        if not out_path:
            return
        start_btn.state(["disabled"])
        progress.config(value=0, maximum=100)
        status_var.set("Starte …")
        threading.Thread(
            target=worker, args=(pdf, code, Path(out_path)), daemon=True
        ).start()

    start_btn.config(command=start)

    def poll():
        """Verarbeitet alle wartenden Ereignisse aus der Warteschlange.

        Läuft im Hauptthread und ruft sich nach 100 ms selbst wieder auf
        (``root.after``). So reagiert die Oberfläche, ohne dass der Thread
        die Widgets direkt verändert.
        """
        try:
            while True:
                ev = events.get_nowait()
                if ev[0] == "progress":
                    _, done, total, msg = ev
                    progress.config(maximum=max(total, 1), value=done)
                    status_var.set(msg)
                elif ev[0] == "done":
                    _, out, empty = ev
                    start_btn.state(["!disabled"])
                    status_var.set(f"Fertig: {out.name}")
                    text = f"Gespeichert unter:\n{out}"
                    if empty:
                        text += f"\n\nSeiten ohne erkannten Text: {empty}"
                    messagebox.showinfo("Fertig", text)
                elif ev[0] == "error":
                    start_btn.state(["!disabled"])
                    status_var.set("Fehler")
                    messagebox.showerror("Fehler", ev[1])
        except queue.Empty:
            # Warteschlange ist leer, also gibt es für diesen Durchlauf nichts zu tun.
            pass
        root.after(100, poll)

    root.after(100, poll)
    root.mainloop()


def main() -> None:
    """Einstiegspunkt. Liest die Kommandozeilenargumente und startet CLI oder GUI.

    Ohne ``--cli`` öffnet sich die Oberfläche. Mit ``--cli`` ist eine PDF-Datei
    Pflicht.
    """
    parser = argparse.ArgumentParser(description="PDF nach Deutsch übersetzen (offline).")
    parser.add_argument("--cli", action="store_true", help="ohne Oberfläche ausführen")
    parser.add_argument("pdf", nargs="?", help="PDF-Datei (mit --cli)")
    parser.add_argument("--source", default=AUTO, help="Ausgangssprache-Code oder 'auto'")
    parser.add_argument("--out", help="Ausgabedatei (.txt)")
    args = parser.parse_args()
    if args.cli:
        if not args.pdf:
            parser.error("PDF-Datei fehlt")
        cli(args)
    else:
        gui()


if __name__ == "__main__":
    main()
