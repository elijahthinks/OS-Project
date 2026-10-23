"""HTTP server for PyOS: serves the desktop UI and a JSON API, using only the standard library."""

import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .storage import SandboxError, Storage
from .terminal import Terminal

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


ROUTES = []


def route(method, pattern):
    def register(func):
        ROUTES.append((method, re.compile(f"^{pattern}$"), func))
        return func
    return register


class Handler(BaseHTTPRequestHandler):
    server_version = "PyOS/2.0"
    storage: Storage
    terminal: Terminal
    frontend_dir: Path

    # ---- Plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        url = urlparse(self.path)
        self.query = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = unquote(url.path)
        if path == "/api/index" and "__path" in self.query:
            # On Vercel every /api request is rewritten to this one function (see vercel.json).
            path = "/api/" + self.query.pop("__path")
        if not path.startswith("/api/"):
            if method == "GET":
                return self._serve_static(path)
            return self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        if method != "GET" and not self._same_origin():
            return self._send_json({"error": "Requests from other sites aren't allowed."}, HTTPStatus.FORBIDDEN)
        for route_method, pattern, func in ROUTES:
            match = pattern.match(path)
            if match and route_method == method:
                try:
                    result = func(self, *match.groups())
                except ApiError as exc:
                    return self._send_json({"error": exc.message}, exc.status)
                except SandboxError as exc:
                    return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except KeyError:
                    return self._send_json({"error": "That item doesn't exist."}, HTTPStatus.NOT_FOUND)
                if result is not None:
                    self._send_json(result)
                return
        self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def _same_origin(self):
        """Block cross-site writes: another page in the browser must not drive this API."""
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def _require_type(self, expected):
        # Plain-text and form posts skip the browser's CORS preflight, so only accept
        # content types that a cross-site page can't send without one.
        actual = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if actual != expected:
            raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, f"Send this request as {expected}.")

    def upload_body(self):
        self._require_type("application/octet-stream")
        return self._body_bytes(MAX_UPLOAD_BYTES)

    def _body_bytes(self, limit):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                           f"That's over the {limit // (1024 * 1024)} MB limit.")
        return self.rfile.read(length) if length else b""

    def json_body(self):
        self._require_type("application/json")
        raw = self._body_bytes(MAX_JSON_BYTES)
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "The request body isn't valid JSON.")
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "The request body must be a JSON object.")
        return data

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, download=False):
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        disposition = "attachment" if download else "inline"
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(path.name)}")
        if not download:
            # Files from the home folder are user content: never let them run scripts.
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (self.frontend_dir / rel).resolve()
        if not target.is_relative_to(self.frontend_dir) or not target.is_file():
            return self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


# ---- Settings -------------------------------------------------------------

@route("GET", "/api/settings")
def get_settings(h):
    return h.storage.get_settings()


@route("PUT", "/api/settings")
def put_settings(h):
    return h.storage.update_settings(h.json_body())


# ---- Files ----------------------------------------------------------------

@route("GET", "/api/files")
def list_files(h):
    return h.storage.list_dir(h.query.get("path", ""))


@route("POST", "/api/files/folder")
def make_folder(h):
    body = h.json_body()
    return {"path": h.storage.make_folder(body.get("parent", ""), body.get("name"))}


@route("POST", "/api/files/upload")
def upload_file(h):
    data = h.upload_body()
    path = h.storage.write_file(h.query.get("parent", ""), h.query.get("name"), data)
    return {"path": path}


@route("GET", "/api/files/raw")
def raw_file(h):
    target = h.storage.resolve(h.query.get("path", ""))
    if not target.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "That file doesn't exist.")
    h.send_file(target, download=h.query.get("download") == "1")


@route("GET", "/api/files/text")
def read_text(h):
    path = h.query.get("path", "")
    return {"path": path, "content": h.storage.read_text(path)}


@route("PUT", "/api/files/text")
def save_text(h):
    body = h.json_body()
    content = body.get("content", "")
    if not isinstance(content, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "content must be text.")
    return {"path": h.storage.save_text(body.get("path", ""), content)}


@route("POST", "/api/files/rename")
def rename_file(h):
    body = h.json_body()
    return {"path": h.storage.rename(body.get("path", ""), body.get("name"))}


@route("DELETE", "/api/files")
def delete_file(h):
    h.storage.delete(h.query.get("path", ""))
    return {"deleted": True}


# ---- Notes ----------------------------------------------------------------

@route("GET", "/api/notes")
def list_notes(h):
    return h.storage.list_notes()


@route("POST", "/api/notes")
def create_note(h):
    body = h.json_body()
    return h.storage.create_note(str(body.get("title", "Untitled")), str(body.get("body", "")))


@route("PUT", r"/api/notes/(\d+)")
def update_note(h, note_id):
    body = h.json_body()
    return h.storage.update_note(int(note_id), str(body.get("title", "")), str(body.get("body", "")))


@route("DELETE", r"/api/notes/(\d+)")
def delete_note(h, note_id):
    h.storage.delete_note(int(note_id))
    return {"deleted": True}


# ---- Messages -------------------------------------------------------------

@route("GET", "/api/channels")
def list_channels(h):
    return h.storage.list_channels()


@route("GET", "/api/messages")
def list_messages(h):
    try:
        after = int(h.query.get("after", 0))
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, "after must be a number.")
    return h.storage.list_messages(h.query.get("channel", "general"), after)


@route("POST", "/api/messages")
def post_message(h):
    body = h.json_body()
    return h.storage.post_message(body.get("channel"), body.get("author"), body.get("body"))


# ---- Terminal -------------------------------------------------------------

@route("POST", "/api/terminal")
def run_terminal(h):
    body = h.json_body()
    user = h.storage.get_settings()["user_name"]
    output, cwd, clear = h.terminal.run(body.get("cwd", ""), str(body.get("line", "")), user)
    return {"output": output, "cwd": cwd, "clear": clear}


def make_handler(data_dir, frontend_dir=FRONTEND_DIR):
    """Build a request handler class bound to one data folder."""
    storage = Storage(data_dir)
    return type("PyOSHandler", (Handler,), {
        "storage": storage,
        "terminal": Terminal(storage),
        "frontend_dir": Path(frontend_dir).resolve(),
    })


def make_server(data_dir, host="127.0.0.1", port=8080, quiet=False, frontend_dir=FRONTEND_DIR):
    server = ThreadingHTTPServer((host, port), make_handler(data_dir, frontend_dir))
    server.quiet = quiet
    return server
