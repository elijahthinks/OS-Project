import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))

from pyos.server import make_server  # noqa: E402
from pyos.storage import SandboxError, Storage  # noqa: E402
from pyos.terminal import Terminal, safe_eval  # noqa: E402


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_seeds_home(self):
        names = [e["name"] for e in self.storage.list_dir("")["entries"]]
        self.assertEqual(names, ["Documents", "Downloads", "Pictures"])

    def test_paths_cannot_escape_home(self):
        for bad in ("..", "../..", "Documents/../../etc", "/../secret"):
            with self.assertRaises(SandboxError, msg=bad):
                self.storage.resolve(bad)

    def test_symlink_out_of_home_is_rejected(self):
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("secret")
        (self.storage.home / "link.txt").symlink_to(outside)
        with self.assertRaises(SandboxError):
            self.storage.read_text("link.txt")

    def test_names_cannot_contain_slashes(self):
        with self.assertRaises(SandboxError):
            self.storage.make_folder("", "a/b")
        with self.assertRaises(SandboxError):
            self.storage.rename("Documents", "../escape")

    def test_upload_never_overwrites(self):
        first = self.storage.write_file("Pictures", "a.png", b"1")
        second = self.storage.write_file("Pictures", "a.png", b"2")
        self.assertEqual(first, "Pictures/a.png")
        self.assertEqual(second, "Pictures/a (2).png")

    def test_home_cannot_be_deleted(self):
        with self.assertRaises(SandboxError):
            self.storage.delete("")

    def test_settings_validate(self):
        self.assertEqual(self.storage.update_settings({"mat": "slate"})["mat"], "slate")
        with self.assertRaises(SandboxError):
            self.storage.update_settings({"mat": "purple"})
        with self.assertRaises(SandboxError):
            self.storage.update_settings({"is_admin": True})

    def test_notes_round_trip(self):
        note = self.storage.create_note("Shopping", "eggs")
        self.storage.update_note(note["id"], "Shopping", "eggs\nmilk")
        self.assertEqual(self.storage.list_notes()[0]["body"], "eggs\nmilk")
        self.storage.delete_note(note["id"])
        self.assertEqual(self.storage.list_notes(), [])
        with self.assertRaises(KeyError):
            self.storage.delete_note(note["id"])

    def test_messages_by_channel(self):
        self.storage.post_message("general", "Ada", "hello")
        last = self.storage.post_message("Side Project", "Ada", "plans")
        self.assertEqual(last["channel"], "side-project")
        self.assertEqual(self.storage.list_channels(), ["side-project", "general"])
        self.assertEqual(self.storage.list_messages("general", after=0)[0]["body"], "hello")
        self.assertEqual(self.storage.list_messages("side-project", after=last["id"]), [])
        with self.assertRaises(SandboxError):
            self.storage.post_message("general", "Ada", "   ")


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.term = Terminal(Storage(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def run_line(self, line, cwd=""):
        return self.term.run(cwd, line, "Ada")

    def test_navigation(self):
        _, cwd, _ = self.run_line("cd Documents")
        self.assertEqual(cwd, "Documents")
        self.assertEqual(self.run_line("pwd", cwd)[0], "~/Documents")
        _, cwd, _ = self.run_line("cd ../../..", cwd)
        self.assertEqual(cwd, "")
        self.assertIn("isn't a folder", self.run_line("cd nowhere")[0])

    def test_files(self):
        self.run_line("mkdir code")
        self.run_line('echo "print(1)" > code/hello.py')
        self.assertEqual(self.run_line("cat code/hello.py")[0], "print(1)")
        self.run_line("mv code/hello.py main.py")
        self.assertEqual(self.run_line("ls code")[0], "main.py")
        self.run_line("rm code")
        self.assertNotIn("code/", self.run_line("ls")[0])

    def test_calc_is_safe(self):
        self.assertEqual(self.run_line("calc 2 + 3 * 4")[0], "14")
        self.assertEqual(self.run_line("calc sqrt(16)")[0], "4")
        self.assertIn("calc:", self.run_line("calc __import__('os')")[0])
        self.assertIn("calc:", self.run_line("calc 1/0")[0])
        with self.assertRaises(ValueError):
            safe_eval("9 ** 99999")

    def test_unknown_command(self):
        self.assertIn("isn't a command", self.run_line("sudo rm -rf /")[0])


class VercelEntryTests(unittest.TestCase):
    def test_entry_exposes_handler(self):
        import importlib.util
        import os
        from http.server import BaseHTTPRequestHandler

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PYOS_DATA_DIR"] = tmp
            try:
                path = Path(__file__).resolve().parents[1] / "api" / "index.py"
                spec = importlib.util.spec_from_file_location("vercel_entry", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finally:
                del os.environ["PYOS_DATA_DIR"]
            self.assertTrue(issubclass(module.handler, BaseHTTPRequestHandler))
            self.assertTrue((module.handler.frontend_dir / "index.html").is_file())


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = make_server(cls.tmp.name, port=0, quiet=True)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, raw=None, content_type="application/json", origin=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", content_type)
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def json_call(self, *args, **kwargs):
        status, body = self.call(*args, **kwargs)
        return status, json.loads(body)

    def test_serves_desktop(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>PyOS</title>", body)

    def test_static_cannot_escape_frontend(self):
        status, _ = self.call("GET", "/../backend/pyos/server.py")
        self.assertEqual(status, 404)

    def test_file_flow(self):
        status, _ = self.json_call("POST", "/api/files/folder", {"parent": "", "name": "Projects"})
        self.assertEqual(status, 200)
        status, res = self.json_call("PUT", "/api/files/text", {"path": "Projects/todo.md", "content": "- ship"})
        self.assertEqual(res["path"], "Projects/todo.md")
        _, res = self.json_call("GET", "/api/files/text?path=Projects/todo.md")
        self.assertEqual(res["content"], "- ship")
        status, raw = self.call("GET", "/api/files/raw?path=Projects/todo.md&download=1")
        self.assertEqual((status, raw), (200, b"- ship"))
        _, res = self.json_call("POST", "/api/files/upload?parent=Projects&name=blob.bin", raw=b"\x00\x01",
                                content_type="application/octet-stream")
        self.assertEqual(res["path"], "Projects/blob.bin")
        status, res = self.json_call("GET", "/api/files/text?path=Projects/blob.bin")
        self.assertEqual(status, 400)
        status, _ = self.json_call("DELETE", "/api/files?path=Projects")
        self.assertEqual(status, 200)

    def test_traversal_is_rejected(self):
        status, res = self.json_call("GET", "/api/files?path=../")
        self.assertEqual(status, 400)
        self.assertIn("outside your home folder", res["error"])

    def test_notes_api(self):
        _, note = self.json_call("POST", "/api/notes", {"title": "Idea"})
        _, note = self.json_call("PUT", f"/api/notes/{note['id']}", {"title": "Idea", "body": "draft"})
        self.assertEqual(note["body"], "draft")
        status, _ = self.json_call("DELETE", f"/api/notes/{note['id']}")
        self.assertEqual(status, 200)
        status, _ = self.json_call("DELETE", f"/api/notes/{note['id']}")
        self.assertEqual(status, 404)

    def test_messages_api(self):
        _, msg = self.json_call("POST", "/api/messages", {"channel": "general", "author": "Ada", "body": "hi"})
        _, messages = self.json_call("GET", "/api/messages?channel=general&after=0")
        self.assertIn(msg, messages)
        status, _ = self.json_call("POST", "/api/messages", {"channel": "general", "author": "Ada", "body": ""})
        self.assertEqual(status, 400)

    def test_terminal_api(self):
        _, res = self.json_call("POST", "/api/terminal", {"cwd": "", "line": "calc 6*7"})
        self.assertEqual(res["output"], "42")

    def test_cross_site_writes_are_blocked(self):
        line = {"cwd": "", "line": "mkdir pwned"}
        status, _ = self.json_call("POST", "/api/terminal", line, origin="https://evil.example")
        self.assertEqual(status, 403)
        # A form or text/plain post skips the CORS preflight, so it must be refused too.
        status, _ = self.json_call("POST", "/api/terminal", line, content_type="text/plain")
        self.assertEqual(status, 415)
        status, _ = self.json_call("POST", "/api/files/upload?parent=&name=x.html", raw=b"<script>",
                                   content_type="text/plain")
        self.assertEqual(status, 415)
        _, listing = self.json_call("GET", "/api/files?path=")
        self.assertNotIn("pwned", [e["name"] for e in listing["entries"]])
        same = f"http://127.0.0.1:{self.server.server_address[1]}"
        status, _ = self.json_call("POST", "/api/terminal", {"cwd": "", "line": "pwd"}, origin=same)
        self.assertEqual(status, 200)

    def test_uploaded_html_is_sandboxed(self):
        self.call("POST", "/api/files/upload?parent=&name=page.html", raw=b"<script>alert(1)</script>",
                  content_type="application/octet-stream")
        with urllib.request.urlopen(self.base + "/api/files/raw?path=page.html") as res:
            self.assertIn("sandbox", res.headers["Content-Security-Policy"])

    def test_vercel_rewritten_paths(self):
        # vercel.json rewrites /api/<path> to /api/index?__path=<path>, keeping the query string.
        _, note = self.json_call("POST", "/api/index?__path=notes", {"title": "From Vercel"})
        status, res = self.json_call("PUT", f"/api/index?__path=notes%2F{note['id']}", {"title": "x", "body": "y"})
        self.assertEqual((status, res["body"]), (200, "y"))
        _, listing = self.json_call("GET", "/api/index?__path=files&path=Documents")
        self.assertEqual(listing["path"], "Documents")

    def test_bad_json(self):
        status, res = self.json_call("PUT", "/api/settings", raw=b"{nope")
        self.assertEqual(status, 400)
        self.assertIn("valid JSON", res["error"])


if __name__ == "__main__":
    unittest.main()
