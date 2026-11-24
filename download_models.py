import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
ARGOS_DIR = MODELS / "argos"

os.environ["ARGOS_PACKAGES_DIR"] = str(ARGOS_DIR)
ARGOS_DIR.mkdir(parents=True, exist_ok=True)


def download_argos() -> None:
    import argostranslate.package as pkg

    pkg.update_package_index()
    available = pkg.get_available_packages()
    installed = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
    print(f"Argos-Pakete im Index: {len(available)}")
    failed = []
    for i, p in enumerate(available, 1):
        key = (p.from_code, p.to_code)
        if key in installed:
            continue
        print(f"[{i}/{len(available)}] {p.from_code} -> {p.to_code}")
        try:
            pkg.install_from_path(p.download())
            installed.add(key)
        except Exception as exc:
            failed.append((key, str(exc)))
    print(f"Fehlgeschlagen: {len(failed)}")
    for key, err in failed:
        print("  ", key, err)


if __name__ == "__main__":
    download_argos()
    print("fertig")
