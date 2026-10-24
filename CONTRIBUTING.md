# Contributing to PyOS

Thanks for helping out. PyOS is small on purpose, so changes are easy to review.

## Get set up

You need Python 3.12 or newer. There is nothing to install.

```sh
git clone https://github.com/elijahthinks/OS-Project.git
cd OS-Project
python Projectos.py --data-dir ./pyos-data
```

Using `--data-dir` keeps your test files out of your real `~/.pyos` folder.

## Before you open a pull request

1. Run the tests: `python -m unittest discover -s test`
2. Try your change in the browser, including at phone width (720px or less).
3. Add a line to `CHANGELOG.md` under an `Unreleased` heading.

## Guidelines

- **No new dependencies** unless there is no reasonable standard-library option. Zero setup is
  a feature.
- **Every path from the browser goes through `Storage.resolve()`.** Add a test when you add a
  new file operation.
- **Insert user content as text.** In `app.js`, build nodes with `el()`; don't use `innerHTML`.
- **Keep the look consistent.** Use the CSS custom properties in `app.css` rather than new
  colors. Write interface text in sentence case and say what a button does ("Save note",
  not "Submit").
- **Adding an app?** Put an `openYourApp()` function that calls `openWindow()` in
  `src/frontend/apps/your-app.js`, load it from `index.html`, and add it to `APPS` at the bottom
  of `app.js` with an icon: add its line drawing to `ICONS` in `app.js` (24px grid, strokes
  only) and pass `icon` to `openWindow()`. Put its logic in its own module under
  `src/backend/pyos/`, its API routes in `server.py`, and its tests in `test/`.

## Reporting bugs and ideas

Use the issue templates. For security problems, follow [SECURITY.md](SECURITY.md) instead.

By contributing you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
