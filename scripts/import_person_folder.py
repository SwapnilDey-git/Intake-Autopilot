"""Backfill importer: post ONE person's folder to /api/intake/case as a single
case bound to that person (client_name = folder name, all files walked
recursively). For local backfill / testing of the person-centric model --
live intake comes through n8n, not this.

The backend classifies, files, and binds each doc to a (client, year); named
primaries are extracted in the background (the vision model reads them, not this
script). This script prints only counts and the backend's JSON reply -- never
file contents (client PII stays local).

    python3 scripts/import_person_folder.py "<person-folder>" ["Client Name"]
"""
import os
import sys
import json
import base64
import urllib.request

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8080")

# Mirror classify.py's junk rules so we don't even upload detritus.
_JUNK_EXACT = {"desktop.ini", "thumbs.db", ".ds_store"}
_JUNK_EXT = {".ini", ".db", ".lnk", ".tmp"}
_JUNK_PREFIXES = (".~lock", "~$")


def _is_junk(name: str) -> bool:
    low = name.lower()
    if low in _JUNK_EXACT or low.startswith(_JUNK_PREFIXES):
        return True
    return os.path.splitext(low)[1] in _JUNK_EXT


def collect(folder: str) -> list[dict]:
    files = []
    for root, _dirs, names in os.walk(folder):
        for f in names:
            if _is_junk(f):
                continue
            try:
                with open(os.path.join(root, f), "rb") as fh:
                    content = fh.read()
            except OSError:
                continue
            files.append({
                "filename": f,
                "content_base64": base64.b64encode(content).decode("ascii"),
            })
    return files


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    folder = sys.argv[1].rstrip("/")
    client_name = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(folder)
    files = collect(folder)
    if not files:
        print("no importable files found in", folder)
        return
    payload = {
        "source": "folder-import",
        "external_ref": f"folder::{client_name}",  # idempotent re-import guard
        "client_name": client_name,
        "subject": f"Backfill import: {client_name}",
        "files": files,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BACKEND + "/api/intake/case", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        print(f"uploaded {len(files)} files for '{client_name}' ->", r.read().decode("utf-8"))


if __name__ == "__main__":
    main()
