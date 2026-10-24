"""Private browser: fetches pages on the server and hands back a cleaned-up copy.

Sites only ever see the PyOS server, never the person browsing: no cookies are sent or
kept, there's no Referer, and every image and stylesheet is fetched through here too.
Pages come back with scripts, frames, trackers and event handlers removed, and the
browser enforces that with a Content-Security-Policy on top.

The fetcher refuses to reach private networks (localhost, 10.x, 192.168.x, cloud metadata
addresses and so on), so a page can't be used to poke at the machine PyOS runs on.
"""

import gzip
import html
import http.client
import ipaddress
import re
import socket
import ssl
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import getproxies, proxy_bypass

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_ASSET_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = 12
SEARCH_URL = "https://html.duckduckgo.com/html/?q="

PAGE_ENDPOINT = "/api/browse/page"
ASSET_ENDPOINT = "/api/browse/asset"

# Applied to every page the browser shows. No scripts at all, and nothing may load
# from anywhere but this server (which is where all images and styles are routed).
PAGE_CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; form-action 'self'; base-uri 'none'; frame-ancestors 'self'; "
    "sandbox allow-same-origin allow-forms"
)
ASSET_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"

ASSET_TYPES = ("image/", "text/css", "font/", "application/font", "application/x-font", "application/vnd.ms-fontobject")


class BrowseError(Exception):
    """Something the person can understand went wrong while loading a page."""


@dataclass
class Response:
    url: str
    status: int
    content_type: str
    charset: str | None
    body: bytes


# ---- Address checks ------------------------------------------------------------

def _is_public(ip):
    address = ipaddress.ip_address(ip)
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def check_url(url):
    """Return (scheme, host, port) for a URL the browser may fetch, or raise BrowseError."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BrowseError("The private browser only opens http and https addresses.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BrowseError("That address is missing a website name.")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise BrowseError("The private browser can't open addresses on this computer or local network.")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
        if re.fullmatch(r"[0-9a-fx.]+", host):
            # Shorthand IPv4 like 2130706433, 0x7f000001 or 127.1 all mean 127.0.0.1.
            try:
                literal = ipaddress.IPv4Address(socket.inet_aton(host))
            except OSError:
                pass
    if literal is not None and not _is_public(str(literal)):
        raise BrowseError("The private browser can't open addresses on this computer or local network.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise BrowseError("That address has an invalid port number.")
    return parts.scheme, host, port


def resolve_public(host, port):
    """Look up a host and return one public IP to connect to."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise BrowseError(f"Couldn't find a website called {host}. Check the spelling.")
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(_is_public(a) for a in addresses):
        raise BrowseError("The private browser can't open addresses on this computer or local network.")
    return addresses[0]


# ---- Connections -------------------------------------------------------------
# These connect to an IP that was already checked, so a DNS answer can't change
# between the check and the connection.

class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, **kwargs):
        super().__init__(host, port, **kwargs)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, **kwargs):
        super().__init__(host, port, context=ssl.create_default_context(), **kwargs)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _proxy_for(scheme, host):
    proxies = getproxies()
    proxy = proxies.get(scheme) or (proxies.get("https") if scheme == "http" else None)
    if not proxy or proxy_bypass(host):
        return None
    parts = urlsplit(proxy if "://" in proxy else f"http://{proxy}")
    return parts.hostname, parts.port or 8080


class Fetcher:
    def __init__(self, allow_private=False):
        # allow_private exists for tests that serve a site on localhost. Never enable it in the app.
        self.allow_private = allow_private

    def _check(self, url):
        if not self.allow_private:
            return check_url(url)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise BrowseError("The private browser only opens http and https addresses.")
        return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)

    def _connection(self, scheme, host, port):
        """Return (connection, sends_absolute_url)."""
        proxy = _proxy_for(scheme, host)
        if proxy:
            # Through a proxy the proxy does the DNS lookup. Private names and IPs were
            # already refused by check_url, and the proxy can't be pinned to an address.
            if scheme == "https":
                conn = http.client.HTTPSConnection(*proxy, timeout=TIMEOUT, context=ssl.create_default_context())
                conn.set_tunnel(host, port)
                return conn, False
            return http.client.HTTPConnection(*proxy, timeout=TIMEOUT), True
        if self.allow_private:
            ip = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0]
        else:
            ip = resolve_public(host, port)
        cls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP
        return cls(host, port, ip, timeout=TIMEOUT), False

    def fetch(self, url, max_bytes, accept="*/*"):
        for _ in range(MAX_REDIRECTS + 1):
            scheme, host, port = self._check(url)
            parts = urlsplit(url)
            conn, absolute = self._connection(scheme, host, port)
            target = parts._replace(fragment="").geturl() if absolute else \
                (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            try:
                conn.request("GET", target, headers={
                    "Host": parts.netloc.rsplit("@", 1)[-1],
                    "User-Agent": USER_AGENT,
                    "Accept": accept,
                    "Accept-Language": "en-US,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "DNT": "1",
                    "Sec-GPC": "1",
                })
                resp = conn.getresponse()
                location = resp.getheader("Location")
                if resp.status in (301, 302, 303, 307, 308) and location:
                    url = urljoin(url, location)
                    continue
                raw = resp.read(max_bytes + 1)
            except BrowseError:
                raise
            except (OSError, http.client.HTTPException):
                raise BrowseError(f"Couldn't connect to {host}. The site may be down, or the address may be wrong.")
            finally:
                conn.close()
            if len(raw) > max_bytes:
                raise BrowseError("That's too large for the private browser.")
            body = _decode_body(raw, resp.getheader("Content-Encoding", ""))
            ctype_header = resp.getheader("Content-Type", "")
            match = re.search(r"charset=\"?([\w-]+)", ctype_header, re.I)
            return Response(url, resp.status, ctype_header.split(";")[0].strip().lower(),
                            match.group(1) if match else None, body)
        raise BrowseError("That site redirected too many times.")


def _decode_body(raw, encoding):
    encoding = encoding.lower()
    try:
        if encoding == "gzip":
            return gzip.decompress(raw)
        if encoding == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except (OSError, zlib.error):
        raise BrowseError("The site sent a page PyOS couldn't unpack.")
    return raw


# ---- Address bar ---------------------------------------------------------------

def to_url(text):
    """Turn what someone typed in the address bar into a URL: a web address or a search."""
    text = (text or "").strip()
    if not text:
        raise BrowseError("Type a web address or something to search for.")
    if re.match(r"^https?://", text, re.I):
        return text
    if " " not in text and re.match(r"^[\w-]+(\.[\w-]+)+(:\d+)?(/.*)?$", text):
        return "https://" + text
    return SEARCH_URL + quote(text)


def unwrap_redirect(url):
    """Skip search-engine click trackers like duckduckgo.com/l/?uddg=<real url>."""
    parts = urlsplit(url)
    if parts.hostname and parts.hostname.endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg")
        if target:
            return target[0]
    return url


# ---- Rewriting ---------------------------------------------------------------

def page_link(url):
    return f"{PAGE_ENDPOINT}?{urlencode({'url': url})}"


def asset_link(url):
    return f"{ASSET_ENDPOINT}?{urlencode({'url': url})}"


CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.I | re.S)
CSS_IMPORT = re.compile(r"""@import\s+(['"])(.*?)\1""", re.I)


def rewrite_css(css, base):
    def fix(raw):
        raw = raw.strip()
        if raw.startswith("data:"):
            return raw
        absolute = urljoin(base, html.unescape(raw))
        return asset_link(absolute) if absolute.startswith(("http://", "https://")) else ""

    css = CSS_URL.sub(lambda m: f'url("{fix(m.group(2))}")', css)
    css = CSS_IMPORT.sub(lambda m: f'@import "{fix(m.group(2))}"', css)
    # Old IE behaviors and expressions can run code; drop them.
    return re.sub(r"(expression\s*\(|behavior\s*:|-moz-binding)", "/*removed*/(", css, flags=re.I)


ALLOWED_TAGS = {
    "a", "abbr", "address", "article", "aside", "b", "bdi", "bdo", "blockquote", "body", "br", "button",
    "caption", "center", "cite", "code", "col", "colgroup", "dd", "del", "details", "dfn", "div", "dl", "dt",
    "em", "fieldset", "figcaption", "figure", "font", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "head", "header", "hgroup", "hr", "html", "i", "img", "input", "ins", "kbd", "label", "legend", "li",
    "link", "main", "mark", "meta", "nav", "ol", "optgroup", "option", "p", "pre", "q", "s", "samp",
    "section", "select", "small", "span", "strike", "strong", "style", "sub", "summary", "sup", "table",
    "tbody", "td", "textarea", "tfoot", "th", "thead", "time", "title", "tr", "tt", "u", "ul", "var", "wbr",
}
# Tags whose content is dropped along with the tag.
DROP_WITH_CONTENT = {"script", "iframe", "frame", "frameset", "object", "embed", "applet", "svg", "math",
                     "template", "canvas", "audio", "video", "noembed", "portal", "dialog"}
VOID_TAGS = {"br", "col", "hr", "img", "input", "link", "meta", "wbr"}

ALLOWED_ATTRS = {
    "href", "src", "alt", "title", "width", "height", "class", "id", "style", "colspan", "rowspan", "lang",
    "dir", "name", "value", "type", "placeholder", "checked", "selected", "disabled", "for", "action",
    "method", "datetime", "open", "start", "reversed", "align", "valign", "bgcolor", "color", "face", "size",
    "border", "cellpadding", "cellspacing", "rel", "multiple", "maxlength", "rows", "cols", "readonly",
    "role", "hidden", "summary", "scope", "headers", "cite", "label", "media", "charset", "content",
}
INPUT_TYPES = {"text", "search", "hidden", "submit", "checkbox", "radio", "number", "email", "url", "tel",
               "date", "month", "week", "time", "color", "range", "reset", "button", "image"}


class _Sanitizer(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=False)
        self.base = base
        self.out = []
        self.skip_depth = 0
        self.skip_tag = None
        self.in_style = False
        self.title = ""
        self.in_title = False
        self.open_forms = 0

    def _abs(self, value):
        return urljoin(self.base, value.strip())

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, closed=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, closed=True)

    def _start(self, tag, attrs, closed):
        if self.skip_depth:
            if tag == self.skip_tag and not closed:
                self.skip_depth += 1
            return
        if tag in DROP_WITH_CONTENT:
            if not closed and tag not in VOID_TAGS:
                self.skip_tag, self.skip_depth = tag, 1
            return
        if tag == "noscript":
            return  # Scripts never run here, so show what's inside noscript.
        if tag not in ALLOWED_TAGS:
            return
        if tag == "base":
            return
        attrs = dict(attrs)
        if tag == "meta" and not ("charset" in attrs or attrs.get("name", "").lower() == "viewport"):
            return
        if tag == "link":
            rel = (attrs.get("rel") or "").lower()
            if "stylesheet" not in rel or not attrs.get("href"):
                return
            attrs = {"rel": "stylesheet", "href": asset_link(self._abs(attrs["href"])), "media": attrs.get("media")}
        elif tag == "img":
            attrs = self._image(attrs)
        elif tag == "a":
            attrs = self._link(attrs)
        elif tag == "form":
            attrs, hidden = self._form(attrs)
        elif tag == "input" and (attrs.get("type") or "text").lower() not in INPUT_TYPES:
            return
        kept = []
        for name, value in attrs.items():
            name = name.lower()
            if value is None and name not in ("checked", "selected", "disabled", "multiple", "readonly", "hidden", "open", "reversed"):
                continue
            if name not in ALLOWED_ATTRS:
                continue
            if name in ("href", "src", "action", "cite") and tag not in ("a", "img", "link", "form"):
                continue
            if name == "style":
                value = rewrite_css(value, self.base)
            kept.append(name if value is None else f'{name}="{html.escape(value, quote=True)}"')
        self.out.append(f"<{tag}{' ' if kept else ''}{' '.join(kept)}{' /' if closed and tag in VOID_TAGS else ''}>")
        if tag == "form":
            self.out.append(hidden)
            self.open_forms += 1
        if tag == "head":
            self.out.append('<meta name="referrer" content="no-referrer">')
        if tag == "style":
            self.in_style = True
        if tag == "title":
            self.in_title = True

    def _image(self, attrs):
        src = attrs.get("src") or ""
        # Lazy-loading sites keep the real image in data-src or srcset until a script swaps it in.
        if not src or src.startswith("data:image/gif") or src.startswith("data:image/svg"):
            src = attrs.get("data-src") or attrs.get("data-lazy-src") or attrs.get("data-original") or src
        if not src and attrs.get("srcset"):
            src = attrs["srcset"].split(",")[0].strip().split(" ")[0]
        if src and not src.startswith("data:"):
            src = asset_link(self._abs(src))
        keep = {k: v for k, v in attrs.items() if k in ("alt", "title", "width", "height", "class", "id", "style", "align", "border")}
        if src:
            keep["src"] = src
        return keep

    def _link(self, attrs):
        href = (attrs.get("href") or "").strip()
        keep = {k: v for k, v in attrs.items() if k not in ("href", "target", "ping")}
        if href.startswith("#"):
            keep["href"] = href
        elif href:
            absolute = unwrap_redirect(self._abs(href))
            if absolute.startswith(("http://", "https://")):
                keep["href"] = page_link(absolute)
        return keep

    def _form(self, attrs):
        # Every form becomes a GET to the private browser, carrying its real target along.
        target = self._abs(attrs.get("action") or self.base)
        keep = {k: v for k, v in attrs.items() if k in ("class", "id", "style", "name")}
        keep.update(action=PAGE_ENDPOINT, method="get")
        hidden = f'<input type="hidden" name="__form" value="{html.escape(target, quote=True)}">'
        return keep, hidden

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth -= 1
            return
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS and tag != "noscript":
            if tag == "form":
                if not self.open_forms:
                    return
                self.open_forms -= 1
            self.out.append(f"</{tag}>")
        if tag == "style":
            self.in_style = False
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_style:
            self.out.append(rewrite_css(data, self.base).replace("</", "<\\/"))
            return
        if self.in_title:
            self.title += data
        self.out.append(data.replace("<", "&lt;"))

    def handle_entityref(self, name):
        if not self.skip_depth:
            self.out.append(f"&{name};")
            if self.in_title:
                self.title += html.unescape(f"&{name};")

    def handle_charref(self, name):
        if not self.skip_depth:
            self.out.append(f"&#{name};")
            if self.in_title:
                self.title += html.unescape(f"&#{name};")

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype") and not self.skip_depth:
            self.out.append(f"<!{decl}>")

    def unknown_decl(self, data):
        pass

    def handle_pi(self, data):
        pass


def sanitize(markup, base):
    """Return (clean_html, title) for a page that was fetched from base."""
    parser = _Sanitizer(base)
    parser.feed(markup)
    parser.close()
    return "".join(parser.out), html.unescape(parser.title).strip()


def _sniff_charset(body):
    match = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", body[:4096], re.I)
    return match.group(1).decode("ascii", "ignore") if match else None


def decode_text(response):
    charset = response.charset or _sniff_charset(response.body) or "utf-8"
    try:
        return response.body.decode(charset, errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


# ---- Pages shown to the person -----------------------------------------------

def message_page(title, text, url=""):
    """A small page in the private browser's own style, for errors and non-HTML content."""
    link = f'<p class="url">{html.escape(url)}</p>' if url else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><meta name='referrer' content='no-referrer'>"
        f"<title>{html.escape(title)}</title><style>"
        "body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:12vh auto;padding:0 20px;color:#1E2522;background:#FAFAF7}"
        "h1{font-size:1.4rem}.url{color:#55605B;overflow-wrap:anywhere}"
        "@media (prefers-color-scheme:dark){body{color:#ECEDE8;background:#2A2E2C}.url{color:#A9B0AB}}"
        f"</style></head><body><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p>{link}</body></html>"
    )


def start_page():
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>New tab</title><style>"
        "body{font:16px/1.55 system-ui,sans-serif;max-width:36rem;margin:10vh auto;padding:0 20px;color:#1E2522;background:#FAFAF7}"
        "h1{font-size:1.5rem;margin:0 0 8px}ul{padding-left:1.2rem}li{margin:4px 0}"
        "@media (prefers-color-scheme:dark){body{color:#ECEDE8;background:#2A2E2C}}"
        "</style></head><body><h1>Browse privately</h1>"
        "<p>Type an address or a search in the bar above. Pages load through PyOS, so:</p>"
        "<ul><li>Sites see the PyOS server, not you.</li>"
        "<li>No cookies are sent or saved, and nothing you visit is stored.</li>"
        "<li>Scripts, trackers, ads frames and pop-ups are removed.</li></ul>"
        "<p>Some sites need scripts to work, so they may look plain or not load at all.</p>"
        "</body></html>"
    )


class Browser:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or Fetcher()

    def page(self, url):
        """Return (status, html, final_url) for the page at url. Never raises BrowseError."""
        try:
            url = unwrap_redirect(url)
            response = self.fetcher.fetch(url, MAX_PAGE_BYTES, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5")
        except BrowseError as exc:
            return 200, message_page("This page couldn't open", str(exc), url), url
        final = response.url
        if response.status >= 400 and response.content_type not in ("text/html", "application/xhtml+xml"):
            return 200, message_page(f"The site answered with error {response.status}",
                                     "The page may have moved, need a login, or block visitors like this browser.", final), final
        if response.content_type in ("text/html", "application/xhtml+xml", ""):
            body, _ = sanitize(decode_text(response), final)
            if response.status >= 400:
                body = message_page(f"The site answered with error {response.status}",
                                    "The page may have moved, or the address may be wrong.", final) if len(body) < 200 else body
            return 200, body, final
        if response.content_type.startswith("image/"):
            img = html.escape(asset_link(final), quote=True)
            return 200, f"<!doctype html><title>Image</title><body style='margin:0;display:grid;place-items:center;min-height:100vh'><img src=\"{img}\" style='max-width:100%'></body>", final
        if response.content_type.startswith("text/"):
            text = html.escape(decode_text(response))
            return 200, f"<!doctype html><title>Text file</title><pre style='white-space:pre-wrap;padding:16px;font:14px/1.5 monospace'>{text}</pre>", final
        return 200, message_page("This file can't be shown here",
                                 f"It's a {response.content_type or 'file'} file, and the private browser only shows web pages, images and text.", final), final

    def asset(self, url):
        """Return (content_type, bytes) for an image, stylesheet or font. Raises BrowseError."""
        response = self.fetcher.fetch(url, MAX_ASSET_BYTES)
        ctype = response.content_type
        if not ctype.startswith(ASSET_TYPES):
            raise BrowseError("Only images, stylesheets and fonts load through the private browser.")
        body = response.body
        if ctype == "text/css":
            body = rewrite_css(decode_text(response), response.url).encode("utf-8")
            ctype = "text/css; charset=utf-8"
        return ctype, body


def form_target(params):
    """Rebuild the URL a rewritten form was really meant for. GET forms replace the query string."""
    target = params.pop("__form")
    return urlsplit(target)._replace(query=urlencode(list(params.items())), fragment="").geturl()
