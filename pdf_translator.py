import argparse
import os
import queue
import re
import sys
import threading
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


MODELS = app_dir() / "models"
os.environ["ARGOS_PACKAGES_DIR"] = str(MODELS / "argos")

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import pymupdf  # noqa: E402
from langdetect import DetectorFactory, detect  # noqa: E402
import argostranslate.translate as tr  # noqa: E402
import stanza  # noqa: E402

_stanza_pipeline = stanza.Pipeline


def _offline_pipeline(*args, **kwargs):
    kwargs.setdefault("download_method", stanza.DownloadMethod.NONE)
    return _stanza_pipeline(*args, **kwargs)


stanza.Pipeline = _offline_pipeline

DetectorFactory.seed = 0

AUTO = "auto"
AUTO_LABEL = "Automatisch erkennen"
TARGET = "de"
LANGDETECT_MAP = {"zh-cn": "zh", "zh-tw": "zt", "no": "nb"}


def installed_sources() -> dict[str, tr.Language]:
    langs = {lang.code: lang for lang in tr.get_installed_languages()}
    target = langs.get(TARGET)
    if target is None:
        return {}
    result = {}
    for code, lang in langs.items():
        if code == TARGET:
            continue
        if lang.get_translation(target) is not None:
            result[code] = lang
    return result


def pdf_paragraphs(page) -> list[str]:
    text = re.sub(r"-\n(?=\w)", "", page.get_text("text"))
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return [p for p in paragraphs if p]


def translate_pdf(pdf: Path, source: str, out: Path, report) -> Path:
    sources = installed_sources()
    doc = pymupdf.open(pdf)
    total = len(doc)

    pages: list[list[str]] = []
    empty_pages = []
    for i, page in enumerate(doc):
        report(i, total, f"Text lesen: Seite {i + 1} von {total}")
        paragraphs = pdf_paragraphs(page)
        if not paragraphs:
            empty_pages.append(i + 1)
        pages.append(paragraphs)
    doc.close()

    all_text = " ".join(p for paras in pages for p in paras)
    if not all_text.strip():
        raise ValueError("Im PDF wurde kein Text gefunden.")

    if source == AUTO:
        code = detect(all_text[:3000])
        src_code = LANGDETECT_MAP.get(code, code)
        report(total, total, f"Erkannte Sprache: {src_code}")
    else:
        src_code = source

    src = sources.get(src_code)
    if src is None:
        raise ValueError(
            f"Kein Übersetzungsmodell für Sprache '{src_code}' nach Deutsch vorhanden."
        )
    translation = src.get_translation(next(l for l in tr.get_installed_languages() if l.code == TARGET))

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
    pdf = Path(args.pdf)
    out = Path(args.out) if args.out else pdf.with_name(pdf.stem + "_de.txt")

    def report(done, total, msg):
        print(f"[{done}/{total}] {msg}", flush=True)

    out, empty = translate_pdf(pdf, args.source, out, report)
    print("Ausgabe:", out)
    if empty:
        print("Seiten ohne Text:", empty)


def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    sources = installed_sources()
    choices = [(AUTO_LABEL, AUTO)] + sorted(
        ((lang.name, code) for code, lang in sources.items()), key=lambda x: x[0].lower()
    )

    root = tk.Tk()
    root.title("PDF-Übersetzer (nach Deutsch)")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=14)
    frame.grid()

    pdf_var = tk.StringVar()
    lang_var = tk.StringVar(value=choices[0][0])
    status_var = tk.StringVar(value="Bereit")
    events: queue.Queue = queue.Queue()

    def pick_pdf():
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
        events.put(("progress", done, total, msg))

    def worker(pdf, code, out):
        try:
            out, empty = translate_pdf(pdf, code, out, report)
            events.put(("done", out, empty))
        except Exception as exc:
            events.put(("error", str(exc)))

    def start():
        if not pdf_var.get():
            messagebox.showwarning("Hinweis", "Bitte zuerst eine PDF-Datei auswählen.")
            return
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
            pass
        root.after(100, poll)

    root.after(100, poll)
    root.mainloop()


def main() -> None:
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
