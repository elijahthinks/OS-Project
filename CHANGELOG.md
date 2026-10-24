# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Vercel support: `vercel.json` builds `api/index.py` with Vercel's Python builder and routes
  every request to it; that one function serves both the desktop and the API.

### Fixed
- Deploying the repository to Vercel showed a 404 page because there was no `index.html` at
  the project root.
- The first Vercel config failed with `unused_function` because Vercel didn't detect
  `api/index.py`; the build is now declared explicitly.

## [2.0.0] - 2026-10-23

PyOS now runs in your browser, backed by a Python server that uses only the standard library.

### Added
- Files: browse, open, upload (button or drag and drop), download, rename and delete files
  in a sandboxed home folder (`~/.pyos/home`).
- Text editor for any text file, with Ctrl+S to save.
- Image viewer.
- Notes that save as you type and can be copied into Documents as text files.
- Messages with channels, shared between everyone using the same PyOS server.
- Camera that saves photos to Pictures.
- Terminal with `ls`, `cd`, `cat`, `mkdir`, `touch`, `rm`, `mv`, `echo`, `calc` and more.
- Settings for your name, mat color, light or dark windows, and grid snapping.
- Draggable, resizable windows with a taskbar, and a day ruler as the clock.
- Test suite, GitHub Actions CI, Dockerfile, and project documentation.

### Changed
- The project layout now separates `src/backend`, `src/frontend` and `test`.
- `Projectos.py` is now a launcher for the web desktop.

### Removed
- The Tkinter interface and the `opencv-python` and `Pillow` dependencies.

### Fixed
- A broken `import cv2` line that stopped the program from starting.

## [1.0.0]

- First Tkinter prototype with File Explorer, Camera, Messaging, Notes and Settings buttons.
