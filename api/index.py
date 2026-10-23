"""Vercel entry point.

Vercel sends every request here (see vercel.json). This WSGI app serves both
the desktop in src/frontend and the API. Vercel only allows writing to /tmp,
which is wiped whenever the function restarts, so files, notes and messages on
a Vercel deployment are temporary. Use the Dockerfile on a host with a disk to
keep them.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "backend"))

from pyos.wsgi import make_wsgi_app  # noqa: E402

app = make_wsgi_app(os.environ.get("PYOS_DATA_DIR", "/tmp/pyos"))
