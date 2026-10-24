"""Tests for the Calculator, private Browser, Notepad AI and game apps."""

import gzip
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))

from pyos import ai, browser  # noqa: E402
from pyos.browser import BrowseError, Browser, Fetcher, check_url, form_target, sanitize, to_url  # noqa: E402
from pyos.mathhelp import MathError, calculate, normalize  # noqa: E402
from pyos.server import make_server  # noqa: E402


class MathTests(unittest.TestCase):
    def result(self, expr, angle="deg", variables=None):
        return calculate(expr, angle, variables)["result"]

    def test_everyday_math(self):
        self.assertEqual(self.result("2 + 3 × 4"), "14")
        self.assertEqual(self.result("15% of 80"), "12")
        self.assertEqual(self.result("17 mod 5"), "2")
        self.assertEqual(self.result("2(3 + 4)"), "14")
        self.assertEqual(self.result("0.1 + 0.2"), "0.3")

    def test_functions_and_constants(self):
        self.assertEqual(self.result("sqrt(144)"), "12")
        self.assertEqual(self.result("5!"), "120")
        self.assertEqual(self.result("(2+3)!"), "120")
        self.assertEqual(self.result("log2(1024)"), "10")
        self.assertEqual(self.result("nCr(10, 3)"), "120")
        self.assertEqual(self.result("mean(4, 8, 15)"), "9")
        self.assertEqual(self.result("pi r^2", variables={"r": 2}), "12.5663706144")

    def test_angles(self):
        self.assertEqual(self.result("sin(30)"), "0.5")
        self.assertEqual(self.result("cos(90)"), "0")
        self.assertEqual(self.result("cos(pi)", "rad"), "-1")
        with self.assertRaisesRegex(MathError, "undefined"):
            calculate("tan(90)", "deg")

    def test_steps_explain_the_work(self):
        steps = calculate("sqrt(16) * 3")["steps"]
        self.assertEqual(steps, ["√16 = 4, because 4 × 4 = 16", "4 × 3 = 12"])

    def test_solves_linear_and_quadratic(self):
        res = calculate("2x + 3 = 11")
        self.assertEqual((res["kind"], res["solutions"]), ("solve", [4.0]))
        self.assertIn("Add 8 to both sides: 2x = 8", res["steps"])
        res = calculate("x^2 - 5x + 6 = 0")
        self.assertEqual(res["solutions"], [2.0, 3.0])
        self.assertTrue(any("Discriminant" in s for s in res["steps"]))
        self.assertEqual(self.result("x^2 + 1 = 0"), "No real solution")

    def test_solves_other_equations_numerically(self):
        res = calculate("x^3 - 2x = 5")
        self.assertAlmostEqual(res["solutions"][0], 2.0945514815, places=8)
        self.assertIn("≈", res["result"])

    def test_saved_letters(self):
        res = calculate("r = 4")
        self.assertEqual((res["kind"], res["variable"], res["value"]), ("assign", "r", 4.0))
        # Typing an equation still solves for x even if x was saved earlier.
        self.assertEqual(calculate("2x + 3 = 11", variables={"x": 7})["solutions"], [4.0])

    def test_friendly_errors(self):
        cases = {
            "1/0": "Dividing by zero",
            "sqrt(-4)": "square root",
            "(2+3": r"missing \)",
            "2 +": "couldn't read",
            "foo(2)": "doesn't have a function",
            "y + 1": "doesn't know what y is",
            "9^99999": "too big",
            "200!": "too big",
        }
        for expr, message in cases.items():
            with self.assertRaisesRegex(MathError, message, msg=expr):
                calculate(expr)

    def test_nothing_runs_as_code(self):
        for expr in ("__import__('os').system('echo hi')", "().__class__", "[1, 2]", "lambda: 1", "'a' * 3"):
            with self.assertRaises(MathError, msg=expr):
                calculate(expr)

    def test_normalize_leaves_names_alone(self):
        self.assertEqual(normalize("log2(8)"), "log2(8)")
        self.assertEqual(normalize("2e5"), "2e5")
        self.assertEqual(normalize("2x"), "2*x")


class SanitizerTests(unittest.TestCase):
    BASE = "https://example.org/dir/page.html"

    def clean(self, markup):
        return sanitize(markup, self.BASE)[0]

    def test_removes_scripts_and_handlers(self):
        out = self.clean(
            '<p onclick="steal()">hi</p><script>alert(1)</script><img src=x onerror=alert(1)>'
            '<a href="javascript:alert(1)">x</a><iframe src="https://evil"></iframe>'
            '<svg><script>alert(1)</script></svg><object data="x"></object>'
            '<SCRIPT>alert(2)</SCRIPT><div style="width:expression(alert(1))">y</div>'
            '<meta http-equiv="refresh" content="0;url=https://evil"><base href="https://evil/">')
        lowered = out.lower()
        for bad in ("script", "onclick", "onerror", "javascript:", "iframe", "<svg", "<object", "expression(", "refresh", "<base"):
            self.assertNotIn(bad, lowered, bad)
        self.assertIn("<p>hi</p>", out)

    def test_style_cannot_break_out(self):
        out = self.clean("<style>p{color:red}</style><script>alert(1)</script></style>")
        self.assertNotIn("<script", out)

    def test_links_and_images_go_through_pyos(self):
        out = self.clean('<a href="/about">a</a><a href="#top">t</a><img src="pic.png">'
                         '<img data-src="lazy.jpg" src="data:image/gif;base64,R0lGOD">'
                         '<img srcset="small.jpg 1x, big.jpg 2x">'
                         '<link rel="stylesheet" href="/s.css"><link rel="preload" href="/x.js">')
        self.assertIn('href="/api/browse/page?url=https%3A%2F%2Fexample.org%2Fabout"', out)
        self.assertIn('href="#top"', out)
        self.assertIn("/api/browse/asset?url=https%3A%2F%2Fexample.org%2Fdir%2Fpic.png", out)
        self.assertIn("lazy.jpg", out)
        self.assertIn("small.jpg", out)
        self.assertIn('<link rel="stylesheet" href="/api/browse/asset?url=https%3A%2F%2Fexample.org%2Fs.css"', out)
        self.assertNotIn("x.js", out)
        self.assertNotIn('"https://example.org', out)

    def test_css_urls_are_proxied(self):
        out = self.clean('<style>@import "theme.css"; body{background:url(bg.png)}</style>'
                         '<div style="background-image: url(\'/hero.jpg\')">x</div>')
        self.assertIn("/api/browse/asset?url=https%3A%2F%2Fexample.org%2Fdir%2Ftheme.css", out)
        self.assertIn("/api/browse/asset?url=https%3A%2F%2Fexample.org%2Fdir%2Fbg.png", out)
        self.assertIn("hero.jpg", out)
        self.assertNotIn("url(bg.png)", out)

    def test_forms_become_private_gets(self):
        out = self.clean('<form action="/search" method="post"><input name="q"><input type="file" name="f"></form>')
        self.assertIn('action="/api/browse/page" method="get"', out)
        self.assertIn('name="__form" value="https://example.org/search"', out)
        self.assertNotIn('type="file"', out)
        self.assertEqual(form_target({"__form": "https://example.org/search?old=1", "q": "cats"}),
                         "https://example.org/search?q=cats")

    def test_noscript_content_is_shown(self):
        self.assertIn("Enable JS", self.clean("<noscript><p>Enable JS</p></noscript>"))

    def test_search_click_trackers_are_skipped(self):
        out = self.clean('<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2F&rut=abc">py</a>')
        self.assertIn("url=https%3A%2F%2Fpython.org%2F", out)
        self.assertNotIn("duckduckgo", out)


class AddressTests(unittest.TestCase):
    def test_blocks_local_and_private_addresses(self):
        for url in ("http://localhost/", "http://127.0.0.1:8080/", "http://10.1.2.3/", "http://192.168.0.1/",
                    "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://2130706433/",
                    "http://0x7f000001/", "http://127.1/", "http://printer.local/", "file:///etc/passwd",
                    "ftp://example.org/"):
            with self.assertRaises(BrowseError, msg=url):
                check_url(url)
        self.assertEqual(check_url("https://example.org/a"), ("https", "example.org", 443))

    def test_default_fetcher_refuses_this_machine(self):
        with self.assertRaises(BrowseError):
            Fetcher().fetch("http://127.0.0.1:9/", 100)

    def test_dns_answers_are_checked(self):
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 80))]):
            with self.assertRaisesRegex(BrowseError, "local network"):
                browser.resolve_public("sneaky.example", 80)

    def test_address_bar(self):
        self.assertEqual(to_url("python.org"), "https://python.org")
        self.assertEqual(to_url("http://x.org/a"), "http://x.org/a")
        self.assertTrue(to_url("how do beagles bark").startswith(browser.SEARCH_URL))
        with self.assertRaises(BrowseError):
            to_url("  ")


class TestSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/old":
            self.send_response(301)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        if self.path == "/page":
            body = gzip.compress(b"<html><head><title>Test &amp; page</title><script>x()</script></head>"
                                 b"<body><a href='/next'>next</a><img src='/pic.png'></body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Encoding", "gzip")
        elif self.path == "/pic.png":
            body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
        elif self.path == "/script.js":
            body = b"alert(1)"
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript")
        else:
            body = b"nope"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BrowserFetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), TestSite)
        cls.base = f"http://127.0.0.1:{cls.site.server_address[1]}"
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        # Only tests may reach localhost: the real browser refuses it.
        cls.browser = Browser(Fetcher(allow_private=True))

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()
        cls.site.server_close()

    def test_follows_redirects_and_unzips(self):
        _, body, final = self.browser.page(self.base + "/old")
        self.assertEqual(final, self.base + "/page")
        self.assertIn("<title>Test &amp; page</title>", body)
        self.assertNotIn("x()", body)
        self.assertIn("/api/browse/page?url=", body)

    def test_assets(self):
        ctype, data = self.browser.asset(self.base + "/pic.png")
        self.assertEqual(ctype, "image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))
        with self.assertRaisesRegex(BrowseError, "Only images"):
            self.browser.asset(self.base + "/script.js")

    def test_errors_become_pages(self):
        _, body, _ = self.browser.page(self.base + "/missing")
        self.assertIn("error 404", body)

    def test_size_limit(self):
        with mock.patch.object(browser, "MAX_PAGE_BYTES", 10):
            _, body, _ = self.browser.page(self.base + "/page")
        self.assertIn("too large", body)


class AppApiTests(unittest.TestCase):
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

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_math(self):
        status, res = self.post("/api/math", {"expression": "r * 2 = 10", "angle": "deg", "variables": {"r": 1}})
        self.assertEqual((status, res["result"]), (200, "r = 5"))
        status, res = self.post("/api/math", {"expression": "1/0"})
        self.assertEqual(status, 422)
        self.assertIn("zero", res["error"])
        status, guide = self.get("/api/math/guide")[0], json.loads(self.get("/api/math/guide")[2])
        self.assertTrue(any(entry["group"] == "Equations" for entry in guide))

    def test_ai_is_wired_but_not_connected(self):
        _, _, raw = self.get("/api/ai")
        status = json.loads(raw)
        self.assertFalse(status["connected"])
        self.assertIn("summarize", [a["id"] for a in status["actions"]])
        code, res = self.post("/api/ai/assist", {"action": "summarize", "text": "Hello there"})
        self.assertEqual(code, 503)
        self.assertIn("isn't connected yet", res["error"])
        self.assertEqual(self.post("/api/ai/assist", {"action": "summarize", "text": " "})[0], 400)
        self.assertEqual(self.post("/api/ai/assist", {"action": "launch", "text": "x"})[0], 400)

    def test_ai_reply_reaches_notepad_when_connected(self):
        with mock.patch.object(ai, "CONNECTED", True), \
                mock.patch.object(ai, "_run_model", return_value="Short version."):
            code, res = self.post("/api/ai/assist", {"action": "shorten", "text": "A long note"})
        self.assertEqual((code, res["text"]), (200, "Short version."))

    def test_text_files_for_notepad(self):
        _, _, raw = self.get("/api/files/text-files")
        self.assertIn("Documents/welcome.txt", [f["path"] for f in json.loads(raw)])

    def test_browser_pages_are_locked_down(self):
        status, headers, body = self.get("/api/browse/page")
        self.assertEqual(status, 200)
        self.assertIn(b"Browse privately", body)
        csp = headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("sandbox", csp)
        self.assertNotIn("allow-scripts", csp)
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_browser_refuses_this_machine(self):
        _, _, body = self.get(f"/api/browse/page?input={self.base}/api/settings")
        self.assertIn(b"couldn&#x27;t open", body)
        self.assertNotIn(b"user_name", body)

    def test_other_sites_cannot_use_the_browser(self):
        _, _, body = self.get("/api/browse/page?input=example.org", {"Sec-Fetch-Site": "cross-site"})
        self.assertIn(b"only works from inside PyOS", body)
        status, _, _ = self.get("/api/browse/asset?url=https://example.org/a.png", {"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    def test_browser_can_be_turned_off(self):
        with mock.patch.dict("os.environ", {"PYOS_DISABLE_BROWSER": "1"}):
            _, _, body = self.get("/api/browse/page?input=example.org")
        self.assertIn(b"turned off", body)

    def test_browsing_is_not_logged(self):
        handler = self.server.RequestHandlerClass
        fake = handler.__new__(handler)
        fake.server = mock.Mock(quiet=False)
        fake.client_address = ("127.0.0.1", 0)
        fake.requestline = fake.path = "/api/browse/page?url=https://secret.example/"
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            fake.log_message("%s", fake.path)
        self.assertEqual(err.getvalue(), "")

    def test_game_is_served(self):
        status, headers, body = self.get("/games/off-my-lawn/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Off My Lawn</title>", body)
        script = body.split(b'src="./')[1].split(b'"')[0].decode()
        status, headers, _ = self.get(f"/games/off-my-lawn/{script}")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript"))


if __name__ == "__main__":
    unittest.main()
