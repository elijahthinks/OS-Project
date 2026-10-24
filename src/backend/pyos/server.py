"""HTTP server for PyOS: serves the desktop UI and a JSON API, using only the standard library."""

import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import ai, browser, mathhelp
from .storage import SandboxError, Storage
from .terminal import Terminal

# Some systems (notably Windows) map these to the wrong types, and browsers refuse
# module scripts and fonts served as text/plain.
for _type, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("font/woff2", ".woff2"),
                    ("font/woff", ".woff"), ("image/svg+xml", ".svg")):
    mimetypes.add_type(_type, _ext)

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
        # The private browser's addresses are never written to the log.
        if "api/browse" in getattr(self, "path", "") or "api%2Fbrowse" in getattr(self, "path", ""):
            return
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
        self.query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        path = unquote(url.path)
        if "__path" in self.query:
            # On Vercel every request is routed to one function, with the original path
            # passed along in __path (see vercel.json).
            path = "/" + self.query.pop("__path").lstrip("/")
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

    def send_bytes(self, data, content_type, status=HTTPStatus.OK, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

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


@route("GET", "/api/files/text-files")
def list_text_files(h):
    return h.storage.find_text_files()


# ---- Calculator -----------------------------------------------------------

@route("GET", "/api/math/guide")
def math_guide(h):
    return mathhelp.guide()


@route("POST", "/api/math")
def calculate(h):
    body = h.json_body()
    variables = body.get("variables") or {}
    if not isinstance(variables, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, "variables must be an object.")
    try:
        return mathhelp.calculate(str(body.get("expression", "")), body.get("angle", "deg"), variables)
    except mathhelp.MathError as exc:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))


# ---- Notepad AI -----------------------------------------------------------

@route("GET", "/api/ai")
def ai_status(h):
    return ai.status()


@route("POST", "/api/ai/assist")
def ai_assist(h):
    body = h.json_body()
    try:
        return ai.assist(str(body.get("action", "")), str(body.get("text", "")), str(body.get("question", "")))
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, str(exc))
    except ai.AIUnavailable as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))


# ---- Private browser ------------------------------------------------------

PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


def _browser_allowed(h):
    if os.environ.get("PYOS_DISABLE_BROWSER") == "1":
        return False, "The private browser is turned off on this server."
    # Other websites can't load pages or images through this PyOS.
    if h.headers.get("Sec-Fetch-Site") == "cross-site":
        return False, "The private browser only works from inside PyOS."
    return True, ""


@route("GET", "/api/browse/page")
def browse_page(h):
    allowed, reason = _browser_allowed(h)
    if not allowed:
        return send_page(h, browser.message_page("Private browser unavailable", reason), "")
    params = dict(h.query)
    if "__form" in params:
        url = browser.form_target(params)
    elif params.get("input"):
        try:
            url = browser.to_url(params["input"])
        except browser.BrowseError as exc:
            return send_page(h, browser.message_page("Nothing to open", str(exc)), "")
    elif params.get("url"):
        url = params["url"]
    else:
        return send_page(h, browser.start_page(), "")
    _, body, final = h.browser.page(url)
    send_page(h, body, final)


def send_page(h, markup, final_url):
    # The frame reads this to show the real address after redirects and form submissions.
    markup += f'<meta name="pyos-url" content="{browser.html.escape(final_url, quote=True)}">'
    h.send_bytes(markup.encode("utf-8"), "text/html; charset=utf-8",
                 headers={**PRIVATE_HEADERS, "Content-Security-Policy": browser.PAGE_CSP})


@route("GET", "/api/browse/asset")
def browse_asset(h):
    url = h.query.get("url", "")
    if not _browser_allowed(h)[0]:
        return h.send_bytes(b"", "text/plain", HTTPStatus.FORBIDDEN, PRIVATE_HEADERS)
    try:
        content_type, data = h.browser.asset(url)
    except browser.BrowseError:
        return h.send_bytes(b"", "text/plain", HTTPStatus.NOT_FOUND, PRIVATE_HEADERS)
    h.send_bytes(data, content_type, headers={
        **PRIVATE_HEADERS, "Cache-Control": "private, max-age=600", "Content-Security-Policy": browser.ASSET_CSP})


def make_handler(data_dir, frontend_dir=FRONTEND_DIR):
    """Build a request handler class bound to one data folder."""
    storage = Storage(data_dir)
    return type("PyOSHandler", (Handler,), {
        "storage": storage,
        "terminal": Terminal(storage),
        "browser": browser.Browser(),
        "frontend_dir": Path(frontend_dir).resolve(),
    })


class PyOSServer(ThreadingHTTPServer):
    def server_close(self):
        super().server_close()
        self.RequestHandlerClass.storage.close()


def make_server(data_dir, host="127.0.0.1", port=8080, quiet=False, frontend_dir=FRONTEND_DIR):
    server = PyOSServer((host, port), make_handler(data_dir, frontend_dir))
    server.quiet = quiet
    return server
