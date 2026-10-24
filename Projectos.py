

This is a thin launcher so the project still runs the way it always has.
The code lives in src/backend/pyos (server) and src/frontend (desktop UI).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "backend"))

from pyos.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
