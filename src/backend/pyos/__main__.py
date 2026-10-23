"""Command-line entry point: python -m pyos"""

import argparse
import os
import threading
import webbrowser

from . import __version__
from .server import make_server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pyos", description="Start the PyOS desktop.")
    parser.add_argument("--host", default=os.environ.get("PYOS_HOST", "127.0.0.1"),
                        help="address to listen on; use 0.0.0.0 to share Messages on your network")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PYOS_PORT", 8080)))
    parser.add_argument("--data-dir", default=os.environ.get("PYOS_DATA_DIR", "~/.pyos"),
                        help="where the home folder and database live (default: ~/.pyos)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    parser.add_argument("--quiet", action="store_true", help="don't log each request")
    args = parser.parse_args(argv)

    server = make_server(args.data_dir, args.host, args.port, quiet=args.quiet)
    shown_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    url = f"http://{shown_host}:{server.server_address[1]}/"
    print(f"PyOS {__version__} is running at {url}")
    print(f"Home folder: {server.RequestHandlerClass.storage.home}")
    print("Press Ctrl+C to shut down.")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
