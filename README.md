# OS-Project
This project is a basic operating system developed entirely in Python using the Tkinter library for the graphical user interface (GUI). It provides a platform to mimic various functionalities typically found in an operating system environment, such as accessing storage, using a camera, messaging, taking notes, and customizing settings.

## Web version (Vercel)

`Projectos.py` is a Tkinter desktop app and cannot run on Vercel, which has no display or webcam access on the server. `index.html`, `style.css` and `app.js` are a browser port with the same apps (File Explorer, Camera, Messaging, Notes, Settings) that runs entirely client-side.

- **Deploy:** import this repo in Vercel (Framework Preset: *Other*, Output Directory left empty). The site is served from the repo root with no build step. Or run `npx vercel` from the repo root.
- **Run locally:** `python3 -m http.server 8000` and open http://localhost:8000.
- **Desktop version:** `pip install opencv-python pillow` then `python3 Projectos.py`.
