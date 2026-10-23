# How PyOS is built

PyOS is two halves that talk over HTTP on your own computer.

```
browser                                   python (standard library only)
┌───────────────────────────┐   fetch    ┌──────────────────────────────┐
│ src/frontend              │ ─────────► │ src/backend/pyos/server.py   │
│  index.html  app.css      │   JSON     │  routes /api/* to handlers   │
│  app.js                   │ ◄───────── │                              │
│   window manager          │            │ storage.py                   │
│   day ruler (taskbar)     │            │  home folder sandbox         │
│   Files, Notes, Messages, │            │  SQLite: settings, notes,    │
│   Camera, Terminal,       │            │          messages            │
│   Settings                │            │ terminal.py                  │
└───────────────────────────┘            │  shell commands, safe calc   │
                                         └──────────────────────────────┘
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
| Apps | One `openX()` function per app |

Windows snap to the 40px mat grid when dropped or resized (Settings can turn this off).
Below 720px wide, windows become full-screen sheets.

## Design notes

The desktop is a cutting mat, windows are paper, and the taskbar is a ruler that measures the
day. Colors are defined once as CSS custom properties in `app.css`; the mat colors and the
light/dark paper are switched with `data-mat` and `data-theme` on `<html>`.
