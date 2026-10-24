# How PyOS is built

PyOS is two halves that talk over HTTP on your own computer.

```
browser                                   python (standard library only)
┌───────────────────────────┐   fetch    ┌──────────────────────────────┐
│ src/frontend              │ ─────────► │ src/backend/pyos/server.py   │
│  index.html  app.css      │   JSON     │  routes /api/* to handlers   │
│  app.js                   │ ◄───────── │                              │
│   window manager, icons   │            │ storage.py                   │
│   day ruler (taskbar)     │            │  home folder sandbox         │
│   Files, Messages,        │            │  SQLite: settings, messages  │
│   Camera, Terminal,       │            │ terminal.py                  │
│   Settings                │            │  shell commands, safe calc   │
│  apps/                    │            │ mathhelp.py  browser.py      │
│   Calculator, Notepad,    │            │ ai.py        wsgi.py         │
│   Browser, Off My Lawn    │            │                              │
└───────────────────────────┘            └──────────────────────────────┘
                                                      │
                                         ~/.pyos/home/   ~/.pyos/pyos.db
```

## Backend

- **`server.py`** uses `http.server.ThreadingHTTPServer`. Routes are registered with a small
  `@route(method, regex)` decorator. Handlers return a dict or list, which is sent as JSON.
  `SandboxError` becomes a 400 and `KeyError` a 404, so handlers stay short.
- **`storage.py`** owns everything on disk. Every user-supplied path goes through
  `Storage.resolve()`, which resolves symlinks and refuses anything outside the home folder.
  SQLite access is serialized with a lock because the server is threaded.
- **`wsgi.py`** wraps the same handler as a WSGI app for hosts that don't run a long-lived
  server. Vercel uses it through `api/index.py`; `vercel.json` routes every request there and
  passes the original path as `__path`.
- **`mathhelp.py`** powers the Calculator. It rewrites friendly notation (`×`, `15% of`, `2x`,
  `5!`) into Python syntax, parses it with `ast`, and walks the tree itself, recording each
  operation as a plain-language step. Equations are classified by sampling: straight-line and
  quadratic ones are solved exactly with their method shown, anything else by a bracketed
  numeric search.
- **`browser.py`** powers the private Browser. `Fetcher` refuses non-public addresses (checking
  the DNS answer and then connecting to that exact IP, so a lookup can't change in between),
  follows redirects itself and caps sizes. `sanitize()` rebuilds each page from an allowlist of
  tags and attributes and routes every link, image, stylesheet and form back through PyOS.
  Pages are served with a Content-Security-Policy that forbids scripts and outside requests.
- **`ai.py`** defines Notepad's AI actions. `CONNECTED` is `False`, so requests return 503 with
  an explanation; implementing `_run_model()` is all that's needed to connect a model.
- **`terminal.py`** parses a command line with `shlex` and runs it against `Storage`, so the
  terminal follows the same sandbox rules as the Files app. `calc` walks a Python AST and
  only allows numbers, arithmetic operators and a whitelist of `math` functions. It never calls `eval`.

## Frontend

Plain JavaScript, no build step. `app.js` is split into sections:

| Section | What it does |
| --- | --- |
| Helpers | `el()` builds DOM nodes (text is always inserted as text, never HTML), `api()` wraps `fetch` |
| Window manager | `openWindow()` creates a draggable, resizable window and its taskbar tab; one window per key |
| Day ruler | Places the highlighter marker at the current time on a 0 to 24 hour scale |
| Icons | `ICONS` holds each app's line drawing on a 24px grid; `appIcon(name)` draws it for launchers, title bars and tabs |
| Apps | One `openX()` function per app; newer apps live in `apps/` (calculator, notepad, browser, game) |

Off My Lawn is a separate React project. Its production build is copied into
`src/frontend/games/off-my-lawn/` by `.build/update-off-my-lawn.sh` and runs in an iframe.

Windows snap to the 40px mat grid when dropped or resized (Settings can turn this off).
Below 720px wide, windows become full-screen sheets.

## Design notes

The desktop is a cutting mat, windows are paper, and the taskbar is a ruler that measures the
day. Colors are defined once as CSS custom properties in `app.css`; the mat colors and the
light/dark paper are switched with `data-mat` and `data-theme` on `<html>`.
