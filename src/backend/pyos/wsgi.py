"""WSGI adapter, so PyOS can run on hosts like Vercel or under gunicorn.

The request handler in server.py is written for http.server. Rather than keep a
second copy of the routing, this feeds each WSGI request through that handler
using in-memory streams and turns what it writes back into a WSGI response.
"""

import io
from email.message import Message
from types import SimpleNamespace

from .server import FRONTEND_DIR, make_handler


def _request_headers(environ):
    headers = Message()
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            headers[key[5:].replace("_", "-").title()] = value
    if environ.get("CONTENT_TYPE"):
        headers["Content-Type"] = environ["CONTENT_TYPE"]
    if environ.get("CONTENT_LENGTH"):
        headers["Content-Length"] = environ["CONTENT_LENGTH"]
    return headers


def make_wsgi_app(data_dir, frontend_dir=FRONTEND_DIR):
    handler_class = make_handler(data_dir, frontend_dir)
    quiet_server = SimpleNamespace(quiet=True)

    def app(environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        path = environ.get("PATH_INFO") or "/"
        if environ.get("QUERY_STRING"):
            path += "?" + environ["QUERY_STRING"]

        # Build a handler without a socket; _dispatch only needs these attributes.
        handler = handler_class.__new__(handler_class)
        handler.server = quiet_server
        handler.client_address = (environ.get("REMOTE_ADDR", ""), 0)
        handler.command = environ["REQUEST_METHOD"].upper()
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"{handler.command} {path} HTTP/1.1"
        handler.headers = _request_headers(environ)
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler._dispatch(handler.command)

        raw = handler.wfile.getvalue()
        head, _, payload = raw.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        status = status_line.split(" ", 1)[1]
        headers = [tuple(line.split(": ", 1)) for line in header_lines
                   if not line.lower().startswith(("server:", "date:"))]
        start_response(status, headers)
        return [payload]

    return app
