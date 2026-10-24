# API reference

All endpoints return JSON. Errors look like `{"error": "That folder doesn't exist."}` with a
4xx status. Request bodies must be sent as `application/json`, except uploads, which use
`application/octet-stream`. Requests that change data from another site's `Origin` are refused. Paths are relative to the home folder (`""` is home itself).

## Settings
| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/settings` | | settings object |
| PUT | `/api/settings` | any of `user_name`, `mat` (`green` `slate` `black`), `theme` (`system` `light` `dark`), `snap_to_grid` | settings object |

## Files
| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | `/api/files?path=` | | `{path, entries: [{name, path, is_dir, size, modified}]}` |
| POST | `/api/files/folder` | `{parent, name}` | `{path}` |
| POST | `/api/files/upload?parent=&name=` | raw file bytes (25 MB max) | `{path}`; never overwrites, adds ` (2)` |
| GET | `/api/files/raw?path=&download=1` | | the file itself |
| GET | `/api/files/text?path=` | | `{path, content}` (UTF-8 text only) |
| PUT | `/api/files/text` | `{path, content}` | `{path}` |
| POST | `/api/files/rename` | `{path, name}` | `{path}` |
| DELETE | `/api/files?path=` | | `{deleted: true}` |

## Notes
| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/notes` | | newest first `[{id, title, body, updated}]` |
| POST | `/api/notes` | `{title, body}` | note |
| PUT | `/api/notes/<id>` | `{title, body}` | note |
| DELETE | `/api/notes/<id>` | | `{deleted: true}` |

## Messages
| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | `/api/channels` | | channel names, most recently active first |
| GET | `/api/messages?channel=&after=` | `after` is the last message id you have | `[{id, channel, author, body, sent}]` |
| POST | `/api/messages` | `{channel, author, body}` | message |

Also `GET /api/files/text-files`: every text file in the home folder, newest first
(`[{path, name, modified}]`), for Notepad's open list.

## Calculator
| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/math/guide` | | `[{group, name, about, example}]` |
| POST | `/api/math` | `{expression, angle: "deg" or "rad", variables: {name: number}}` | `{kind: value / assign / solve / check, result, steps, value?, variable?, solutions?}`; 422 with a plain-language `error` |

## Notepad AI
| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/ai` | | `{connected, actions: [{id, label, about}]}` |
| POST | `/api/ai/assist` | `{action, text, question?}` | `{action, text}` once connected; until then 503 with an `error` explaining it isn't connected |

## Private browser
These return HTML or files, not JSON, and refuse requests marked `Sec-Fetch-Site: cross-site`.

| Method | Path | Query | Returns |
| --- | --- | --- | --- |
| GET | `/api/browse/page` | `input` (address or search), `url`, or a rewritten form's fields with `__form` | A cleaned page, or a start or error page |
| GET | `/api/browse/asset` | `url` | An image, stylesheet or font; 404 for anything else |

## Terminal
| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| POST | `/api/terminal` | `{cwd, line}` | `{output, cwd, clear}` |
