# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 2.x | Yes |
| 1.x (Tkinter) | No |

## How PyOS is meant to run

PyOS is a personal desktop with **no login**. By default it listens on `127.0.0.1`, so only
your own computer can reach it. If you start it with `--host 0.0.0.0`, anyone on your network
can read, change and delete the files in your PyOS home folder. Only do that on a network
you trust.

Built-in protections:
- Every file path is resolved and checked so it can't leave the home folder, including
  through `..` or symlinks.
- Files opened from the home folder are served with a sandboxing Content-Security-Policy, so
  an uploaded HTML file can't run scripts against the API.
- Requests that change data are refused when they come from another website, so a page you
  visit can't drive the PyOS API behind your back.
- The terminal never runs real shell commands, and `calc` never calls Python's `eval`.
- Uploads are limited to 25 MB and JSON bodies to 2 MB.

### Private browser

- It won't fetch localhost, private networks (10.x, 172.16-31.x, 192.168.x), link-local or
  cloud metadata addresses, including shorthand forms like `2130706433`. DNS answers are
  checked, and the connection goes to the exact address that was checked.
- Pages are rebuilt from an allowlist of tags and attributes and served with a
  Content-Security-Policy and iframe sandbox that block scripts, pop-ups and any request that
  doesn't go through PyOS.
- PyOS never logs the addresses you visit. Your host may: Vercel, for example, records
  request paths in its function logs.
- On a public deployment anyone with the link can browse through your server. Set
  `PYOS_DISABLE_BROWSER=1` to turn the browser off.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through
[GitHub security advisories](https://github.com/elijahthinks/OS-Project/security/advisories/new).
Include the steps to reproduce it and the version you tested. You should hear back within a week.
