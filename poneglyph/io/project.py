"""Project persistence — SQLite with JSON blobs per element."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta     (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS elements (type TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                                     PRIMARY KEY (type, id));
CREATE TABLE IF NOT EXISTS drawings (name TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS volt_colours (kv REAL PRIMARY KEY, colour TEXT NOT NULL);
"""

TABLES = [
    "buses", "connections", "transformers", "sources", "loads",
    "cts", "vts", "cttbs", "testblocks", "breakers", "disconnects",
    "relays", "relay_wires",
]


def sanitize_name(name: str) -> str:
    """Strip characters that are illegal in Windows/macOS/Linux folder names."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = name.strip('. ')
    return name or "Untitled"


def drawing_subdir(drawings_dir: Path, drawing_name: str) -> Path:
    """
    Map XXXX-YZZ-NNNNN-N → drawings_dir/XXXX/YZZ/NNNNN/
    Names that don't match fall back to drawings_dir directly.
    """
    parts = drawing_name.split("-")
    if len(parts) >= 3:
        return drawings_dir / parts[0] / parts[1] / parts[2]
    return drawings_dir


def archive_existing(dest_dir: Path, drawing_name: str) -> None:
    """Move any existing file whose stem starts with drawing_name into .../Archive/."""
    archive = dest_dir / "Archive"
    for f in dest_dir.iterdir() if dest_dir.exists() else []:
        if f.is_file() and f.stem.startswith(drawing_name):
            archive.mkdir(exist_ok=True)
            f.rename(archive / f.name)


def create_project_folders(project_folder: Path) -> None:
    """Create the standard substation project folder tree."""
    for sub in [
        "Drawings",
        "Relay Settings",
        "Tailboards/Completed",
    ]:
        (project_folder / sub).mkdir(parents=True, exist_ok=True)


def save(diagram, filepath: str | Path, project_name: str) -> None:
    """Save diagram to a SQLite .poneglyph file."""
    filepath = Path(filepath)
    data = diagram.to_dict()

    con = sqlite3.connect(filepath)
    try:
        con.executescript(SCHEMA)
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", ("project_name", project_name))

        # Clear existing elements then bulk-insert
        con.execute("DELETE FROM elements")
        for table in TABLES:
            for eid, edata in data.get(table, {}).items():
                con.execute(
                    "INSERT INTO elements (type, id, data) VALUES (?, ?, ?)",
                    (table, eid, json.dumps(edata)),
                )

        con.execute("DELETE FROM drawings")
        for name, ddata in data.get("drawings", {}).items():
            con.execute("INSERT INTO drawings VALUES (?, ?)", (name, json.dumps(ddata)))

        con.execute("DELETE FROM volt_colours")
        for kv, colour in data.get("volt_colours", {}).items():
            con.execute("INSERT INTO volt_colours VALUES (?, ?)", (float(kv), colour))

        con.commit()
    finally:
        con.close()


def load(diagram, filepath: str | Path) -> str:
    """Load diagram from a SQLite .poneglyph file. Returns project_name."""
    filepath = Path(filepath)
    con = sqlite3.connect(filepath)
    try:
        data: dict = {t: {} for t in TABLES}
        data["drawings"]     = {}
        data["volt_colours"] = {}

        for table, eid, edata in con.execute("SELECT type, id, data FROM elements"):
            if table in data:
                data[table][eid] = json.loads(edata)

        for name, ddata in con.execute("SELECT name, data FROM drawings"):
            data["drawings"][name] = json.loads(ddata)

        for kv, colour in con.execute("SELECT kv, colour FROM volt_colours"):
            data["volt_colours"][str(kv)] = colour

        project_name = con.execute(
            "SELECT value FROM meta WHERE key='project_name'"
        ).fetchone()
        project_name = project_name[0] if project_name else "Untitled"
    finally:
        con.close()

    diagram.load_dict(data)
    return project_name
