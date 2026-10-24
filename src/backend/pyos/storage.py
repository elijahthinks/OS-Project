"""Persistent state for PyOS: a sandboxed home folder plus a small SQLite store."""

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_SETTINGS = {
    "user_name": "Guest",
    "mat": "green",          # green | slate | black
    "theme": "system",       # system | light | dark
    "snap_to_grid": True,
}

STARTER_FOLDERS = ("Documents", "Pictures", "Downloads")


class SandboxError(ValueError):
    """Raised when a path or request falls outside what the home folder allows."""


class Storage:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.home = self.data_dir / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        first_run = not any(self.home.iterdir())
        if first_run:
            self._seed_home()

        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.data_dir / "pyos.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                author TEXT NOT NULL,
                body TEXT NOT NULL,
                sent REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_channel ON messages (channel, id);
            """
        )
        self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def _seed_home(self):
        for name in STARTER_FOLDERS:
            (self.home / name).mkdir(exist_ok=True)
        (self.home / "Documents" / "welcome.txt").write_text(
            "This is your home folder. Everything you save in PyOS lives here,\n"
            f"on disk at {self.home}.\n\n"
            "Open the terminal and type help to see what it can do.\n"
        )

    # ---- Paths -------------------------------------------------------------

    def resolve(self, rel_path):
        """Turn a home-relative path like 'Documents/a.txt' into a safe absolute path."""
        rel = (rel_path or "").strip().lstrip("/")
        target = (self.home / rel).resolve()
        if target != self.home and not target.is_relative_to(self.home):
            raise SandboxError("That path is outside your home folder.")
        return target

    def relative(self, path):
        rel = path.relative_to(self.home).as_posix()
        return "" if rel == "." else rel

    @staticmethod
    def check_name(name):
        name = (name or "").strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise SandboxError("Names can't be empty or contain slashes.")
        return name

    # ---- Files -------------------------------------------------------------

    def list_dir(self, rel_path):
        folder = self.resolve(rel_path)
        if not folder.is_dir():
            raise SandboxError("That folder doesn't exist.")
        entries = []
        for child in folder.iterdir():
            if child.name.startswith("."):
                continue
            stat = child.stat()
            entries.append({
                "name": child.name,
                "path": self.relative(child),
                "is_dir": child.is_dir(),
                "size": 0 if child.is_dir() else stat.st_size,
                "modified": stat.st_mtime,
            })
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return {"path": self.relative(folder), "entries": entries}

    def make_folder(self, parent, name):
        target = self.resolve(parent) / self.check_name(name)
        if target.exists():
            raise SandboxError(f"{target.name} already exists here.")
        target.mkdir()
        return self.relative(target)

    def write_file(self, parent, name, data, overwrite=False):
        folder = self.resolve(parent)
        if not folder.is_dir():
            raise SandboxError("That folder doesn't exist.")
        target = folder / self.check_name(name)
        if target.exists() and not overwrite:
            stem, suffix, n = target.stem, target.suffix, 2
            while target.exists():
                target = folder / f"{stem} ({n}){suffix}"
                n += 1
        target.write_bytes(data)
        return self.relative(target)

    TEXT_SUFFIXES = {".txt", ".md", ".py", ".js", ".css", ".html", ".json", ".csv", ".log", ".ini",
                     ".cfg", ".toml", ".yaml", ".yml", ".xml", ".sh"}

    def find_text_files(self, limit=300):
        """Every text file in the home folder, newest first, for Notepad's open list."""
        found = []
        for path in self.home.rglob("*"):
            if path.is_file() and path.suffix.lower() in self.TEXT_SUFFIXES and \
                    not any(part.startswith(".") for part in path.relative_to(self.home).parts):
                found.append({"path": self.relative(path), "name": path.name, "modified": path.stat().st_mtime})
        found.sort(key=lambda f: f["modified"], reverse=True)
        return found[:limit]

    def read_text(self, rel_path):
        target = self.resolve(rel_path)
        if not target.is_file():
            raise SandboxError("That file doesn't exist.")
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = "\x00"
        if "\x00" in text:
            raise SandboxError("That file isn't plain text, so it can't open here.")
        return text

    def save_text(self, rel_path, content):
        target = self.resolve(rel_path)
        if target.is_dir():
            raise SandboxError("That's a folder, not a file.")
        if not target.parent.is_dir():
            raise SandboxError("The folder for that file doesn't exist.")
        target.write_text(content, encoding="utf-8")
        return self.relative(target)

    def rename(self, rel_path, new_name):
        source = self.resolve(rel_path)
        if source == self.home or not source.exists():
            raise SandboxError("That item doesn't exist.")
        target = source.parent / self.check_name(new_name)
        if target.exists():
            raise SandboxError(f"{target.name} already exists here.")
        source.rename(target)
        return self.relative(target)

    def delete(self, rel_path):
        target = self.resolve(rel_path)
        if target == self.home:
            raise SandboxError("Your home folder can't be deleted.")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            raise SandboxError("That item doesn't exist.")

    # ---- Settings ----------------------------------------------------------

    def get_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        with self._lock:
            rows = self._db.execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            if row["key"] in settings:
                settings[row["key"]] = json.loads(row["value"])
        return settings

    def update_settings(self, changes):
        allowed = {
            "user_name": lambda v: isinstance(v, str) and 0 < len(v.strip()) <= 40,
            "mat": lambda v: v in ("green", "slate", "black"),
            "theme": lambda v: v in ("system", "light", "dark"),
            "snap_to_grid": lambda v: isinstance(v, bool),
        }
        for key, value in changes.items():
            if key not in allowed or not allowed[key](value):
                raise SandboxError(f"{key} can't be set to {value!r}.")
        with self._lock, self._db:
            for key, value in changes.items():
                if key == "user_name":
                    value = value.strip()
                self._db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
        return self.get_settings()

    # ---- Notes -------------------------------------------------------------

    def list_notes(self):
        with self._lock:
            rows = self._db.execute(
                "SELECT id, title, body, updated FROM notes ORDER BY updated DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_note(self, title="Untitled", body=""):
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO notes (title, body, updated) VALUES (?, ?, ?)",
                (title or "Untitled", body, time.time()),
            )
        return self.get_note(cur.lastrowid)

    def get_note(self, note_id):
        with self._lock:
            row = self._db.execute(
                "SELECT id, title, body, updated FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
        if row is None:
            raise KeyError(note_id)
        return dict(row)

    def update_note(self, note_id, title, body):
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE notes SET title = ?, body = ?, updated = ? WHERE id = ?",
                (title or "Untitled", body, time.time(), note_id),
            )
        if cur.rowcount == 0:
            raise KeyError(note_id)
        return self.get_note(note_id)

    def delete_note(self, note_id):
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        if cur.rowcount == 0:
            raise KeyError(note_id)

    # ---- Messages ----------------------------------------------------------

    def list_channels(self):
        with self._lock:
            rows = self._db.execute(
                "SELECT channel, MAX(id) AS last FROM messages GROUP BY channel ORDER BY last DESC"
            ).fetchall()
        names = [r["channel"] for r in rows]
        return names if "general" in names else ["general", *names]

    def list_messages(self, channel, after=0, limit=200):
        with self._lock:
            rows = self._db.execute(
                "SELECT id, channel, author, body, sent FROM messages "
                "WHERE channel = ? AND id > ? ORDER BY id DESC LIMIT ?",
                (channel, after, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def post_message(self, channel, author, body):
        channel = (channel or "").strip().lower().replace(" ", "-")
        body = (body or "").strip()
        author = (author or "").strip()
        if not channel or len(channel) > 32:
            raise SandboxError("Channel names need 1 to 32 characters.")
        if not body:
            raise SandboxError("Type a message before sending.")
        if len(body) > 4000:
            raise SandboxError("Messages can be up to 4000 characters.")
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO messages (channel, author, body, sent) VALUES (?, ?, ?, ?)",
                (channel, author or "Guest", body, time.time()),
            )
            row = self._db.execute(
                "SELECT id, channel, author, body, sent FROM messages WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        return dict(row)
