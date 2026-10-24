/* PyOS desktop: window manager, day ruler, and apps. Talks to the Python server at /api. */
"use strict";

// ---- Helpers ---------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (value === false && !(key in node)) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";
function glyph(paths) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", d);
    svg.append(p);
  }
  return svg;
}
const GLYPHS = {
  close: ["M3.5 3.5l9 9", "M12.5 3.5l-9 9"],
  minimize: ["M3 12.5h10"],
  folder: ["M1.5 4.5v8.5h13V5.5H7.5L6 3.5H1.5z"],
  file: ["M3.5 1.5h6l3 3v10h-9z", "M9.5 1.5v3h3"],
};

// App icons on a 24px grid, stroked in ink like the rest of the desktop.
const ring = (cx, cy, r) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
const ICONS = {
  files: ["M3 6.5h6l2 2.5h10v10.5H3z", "M3 11.5h18"],
  notepad: ["M6 4.5h12v16H6z", "M9 3v3M12 3v3M15 3v3", "M9 10h6M9 13.5h6M9 17h3.5"],
  calculator: ["M6 3h12v18H6z", "M8.5 5.5h7v3.5h-7z",
    "M8.5 12.5h1.5M11.25 12.5h1.5M14 12.5h1.5M8.5 15.5h1.5M11.25 15.5h1.5M14 15.5h1.5M8.5 18.5h1.5M11.25 18.5h1.5M14 18.5h1.5"],
  browser: ["M3 5h18v14H3z", "M3 8.5h18", "M8 13.5c2.4 2 5.6 2 8 0", "M9.3 15.4l-.9 1.3M12 16.1v1.6M14.7 15.4l.9 1.3"],
  messages: ["M3.5 4.5h11v8h-6l-3 3v-3h-2z", "M17.5 8.5h3v8h-2v3l-3-3h-5v-1.5"],
  camera: ["M3 8h4l1.8-2.5h6.4L17 8h4v11H3z", ring(12, 13, 3.5)],
  terminal: ["M3 5h18v14H3z", "M7 10l3 2.5L7 15", "M12.5 15H17"],
  game: ["M8.5 17.2c0-2.6 1.6-4.7 3.5-4.7s3.5 2.1 3.5 4.7c0 1.8-1.6 2.3-3.5 2.3s-3.5-.5-3.5-2.3z",
    ring(6.3, 11.6, 1.6), ring(9.4, 7.4, 1.6), ring(14.6, 7.4, 1.6), ring(17.7, 11.6, 1.6)],
  settings: ["M4 6.5h3M11 6.5h9M4 12h9M17 12h3M4 17.5h1.5M9.5 17.5H20", ring(9, 6.5, 2), ring(15, 12, 2), ring(7.5, 17.5, 2)],
  image: ["M3 5h18v14H3z", "M3 16l5-5 4 4 2.5-2.5L21 18", ring(16, 9, 1.5)],
};

function appIcon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "app-icon");
  svg.setAttribute("aria-hidden", "true");
  for (const d of ICONS[name] || []) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body instanceof Blob || body instanceof ArrayBuffer) {
    options.body = body;
    options.headers["Content-Type"] = "application/octet-stream";
  } else if (body !== undefined) {
    options.body = JSON.stringify(body);
    options.headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("PyOS can't reach its server. Check that Projectos.py is still running.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `The server answered ${response.status}.`);
  return data;
}

const q = (params) => new URLSearchParams(params).toString();

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function formatWhen(seconds) {
  const date = new Date(seconds * 1000);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

function debounce(fn, ms) {
  let timer;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.flush = (...args) => { clearTimeout(timer); fn(...args); };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

let noticeTimer;
function notice(message, isError = false) {
  const box = document.getElementById("notice");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.classList.add("shown");
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => box.classList.remove("shown"), isError ? 6000 : 3000);
}

const isSmallScreen = () => window.matchMedia("(max-width: 720px)").matches;

// ---- Settings --------------------------------------------------------------

const settings = { user_name: "Guest", mat: "green", theme: "system", snap_to_grid: true };
const settingsListeners = new Set();

function applySettings() {
  document.documentElement.dataset.mat = settings.mat;
  document.documentElement.dataset.theme = settings.theme;
  settingsListeners.forEach((fn) => fn(settings));
}

async function saveSettings(changes) {
  Object.assign(settings, await api("PUT", "/api/settings", changes));
  applySettings();
}

// ---- Window manager --------------------------------------------------------

const CELL = 40;
const windows = new Map();
let zTop = 10;
let cascade = 0;

function snap(value) {
  return settings.snap_to_grid ? Math.round(value / CELL) * CELL : Math.round(value);
}

function desktopBounds() {
  return document.getElementById("desk").getBoundingClientRect();
}

function openWindow({ key, title, icon, width = 560, height = 400, build }) {
  if (windows.has(key)) {
    const existing = windows.get(key);
    existing.restore();
    return existing;
  }

  const bounds = desktopBounds();
  const w = Math.min(width, bounds.width - CELL);
  const h = Math.min(height, bounds.height - CELL);
  const offset = (cascade++ % 6) * CELL;
  // Start right of the two launcher columns.
  const left = snap(Math.min(CELL * 11 + offset, Math.max(0, bounds.width - w)));
  const top = snap(Math.min(CELL + offset, Math.max(0, bounds.height - h)));

  const titleEl = el("h2", {}, title);
  const body = el("div", { class: "window-body" });
  const minBtn = el("button", { class: "win-btn", type: "button", "aria-label": "Minimize", title: "Minimize" }, glyph(GLYPHS.minimize));
  const closeBtn = el("button", { class: "win-btn", type: "button", "aria-label": "Close", title: "Close" }, glyph(GLYPHS.close));
  const titlebar = el("div", { class: "titlebar" }, icon && appIcon(icon), titleEl, minBtn, closeBtn);
  const grip = el("div", { class: "resize-grip", "aria-hidden": "true" });
  const node = el("section", { class: "window", role: "dialog", "aria-label": title }, titlebar, body, grip);
  Object.assign(node.style, { left: `${left}px`, top: `${top}px`, width: `${w}px`, height: `${h}px` });

  const tabLabel = el("span", { class: "tab-label" }, title);
  const tab = el("button", { class: "tab", type: "button", title }, icon && appIcon(icon), tabLabel);
  const cleanups = [];

  const win = {
    key, node, body, tab,
    onCleanup(fn) { cleanups.push(fn); },
    // An app can set confirmClose to a function that returns false to keep the window open,
    // for example to ask about unsaved changes first.
    confirmClose: null,
    requestClose() {
      if (win.confirmClose && win.confirmClose() === false) return;
      win.close();
    },
    setTitle(text) {
      titleEl.textContent = text;
      tabLabel.textContent = text;
      tab.title = text;
      node.setAttribute("aria-label", text);
    },
    focus() {
      node.style.zIndex = ++zTop;
      for (const other of windows.values()) {
        const isMe = other === win;
        other.node.classList.toggle("focused", isMe);
        other.tab.setAttribute("aria-pressed", String(isMe));
      }
    },
    minimize() {
      node.classList.add("minimized");
      tab.classList.add("is-min");
      node.classList.remove("focused");
      tab.setAttribute("aria-pressed", "false");
    },
    restore() {
      node.classList.remove("minimized");
      tab.classList.remove("is-min");
      win.focus();
    },
    close() {
      cleanups.forEach((fn) => fn());
      node.remove();
      tab.remove();
      windows.delete(key);
      const next = [...windows.values()].filter((x) => !x.node.classList.contains("minimized"))
        .sort((a, b) => b.node.style.zIndex - a.node.style.zIndex)[0];
      if (next) next.focus();
    },
  };

  minBtn.addEventListener("click", (e) => { e.stopPropagation(); win.minimize(); });
  closeBtn.addEventListener("click", (e) => { e.stopPropagation(); win.requestClose(); });
  node.addEventListener("pointerdown", () => win.focus());
  tab.addEventListener("click", () => {
    if (node.classList.contains("minimized")) win.restore();
    else if (node.classList.contains("focused")) win.minimize();
    else win.focus();
  });

  dragBehavior(titlebar, node, "move");
  dragBehavior(grip, node, "resize");

  windows.set(key, win);
  document.getElementById("windows").append(node);
  document.getElementById("tabs").append(tab);
  build(win);
  win.focus();
  return win;
}

function dragBehavior(handle, node, mode) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || isSmallScreen() || event.target.closest(".win-btn")) return;
    event.preventDefault();
    const start = { x: event.clientX, y: event.clientY, rect: node.getBoundingClientRect() };
    const desk = desktopBounds();
    handle.setPointerCapture(event.pointerId);
    node.classList.add("dragging");

    const move = (e) => {
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      if (mode === "move") {
        const left = Math.max(-start.rect.width + 80, Math.min(desk.width - 80, start.rect.left - desk.left + dx));
        const top = Math.max(0, Math.min(desk.height - 38, start.rect.top - desk.top + dy));
        node.style.left = `${left}px`;
        node.style.top = `${top}px`;
      } else {
        node.style.width = `${Math.max(280, start.rect.width + dx)}px`;
        node.style.height = `${Math.max(200, start.rect.height + dy)}px`;
      }
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      node.classList.remove("dragging");
      // Drop onto the mat grid.
      node.classList.add("settling");
      if (mode === "move") {
        node.style.left = `${snap(parseFloat(node.style.left))}px`;
        node.style.top = `${Math.max(0, snap(parseFloat(node.style.top)))}px`;
      } else {
        node.style.width = `${Math.max(280, snap(parseFloat(node.style.width)))}px`;
        node.style.height = `${Math.max(200, snap(parseFloat(node.style.height)))}px`;
      }
      setTimeout(() => node.classList.remove("settling"), 140);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end, { once: true });
    handle.addEventListener("pointercancel", end, { once: true });
  });
}

// ---- Day ruler -------------------------------------------------------------

function buildRuler() {
  const labels = document.querySelector(".ruler-labels");
  for (let hour = 0; hour <= 24; hour += 3) {
    labels.append(el("span", { style: `left: ${(hour / 24) * 100}%` }, hour));
  }
  const now = document.querySelector(".ruler-now");
  const time = document.querySelector(".ruler-now-time");
  const ruler = document.getElementById("day-ruler");

  function tick() {
    const d = new Date();
    const minutes = d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
    // Ticks are inset by 12px on each side of the ruler.
    now.style.left = `calc(12px + (100% - 24px) * ${minutes / 1440})`;
    time.textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    ruler.setAttribute("aria-label", `Time: ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`);
    ruler.title = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  }
  tick();
  setInterval(tick, 15000);
}

function buildMatScale() {
  const scale = document.getElementById("mat-scale");
  const draw = () => {
    scale.replaceChildren();
    const count = Math.floor(window.innerWidth / CELL);
    for (let i = 1; i <= count; i++) {
      scale.append(el("span", { style: `left: ${i * CELL}px` }, i));
    }
  };
  draw();
  window.addEventListener("resize", debounce(draw, 150));
}

// ---- Files -----------------------------------------------------------------

const TEXT_TYPES = /\.(txt|md|py|js|css|html|json|csv|log|ini|cfg|toml|yaml|yml|xml|sh)$/i;
const IMAGE_TYPES = /\.(png|jpe?g|gif|webp|svg|bmp)$/i;

function openFiles(startPath = "") {
  openWindow({
    key: "files", title: "Files", icon: "files", width: 640, height: 440,
    build(win) {
      let path = startPath;
      let entries = [];
      let selected = null;

      const crumbs = el("div", { class: "crumbs" });
      const upload = el("input", { type: "file", multiple: true, hidden: true });
      const toolbar = el("div", { class: "toolbar" },
        crumbs, el("span", { class: "grow" }),
        el("button", { class: "btn", type: "button", onclick: () => askNewFolder() }, "New folder"),
        el("button", { class: "btn", type: "button", onclick: () => upload.click() }, "Upload"),
        upload,
      );
      const list = el("ul", { class: "file-list", role: "listbox", "aria-label": "Files", tabindex: "0" });
      const actions = el("div", { class: "action-bar" });
      win.body.append(toolbar, list, actions);

      async function load(nextPath = path) {
        try {
          const data = await api("GET", `/api/files?${q({ path: nextPath })}`);
          path = data.path;
          entries = data.entries;
          if (selected && !entries.some((e) => e.path === selected.path)) selected = null;
          render();
        } catch (err) {
          notice(err.message, true);
          if (nextPath !== "") load("");
        }
      }
      win.reload = load;

      function render() {
        const parts = path ? path.split("/") : [];
        crumbs.replaceChildren(
          el("button", { type: "button", "aria-current": parts.length ? null : "location", onclick: () => go("") }, "Home"),
          ...parts.flatMap((part, i) => [
            el("span", { class: "sep", "aria-hidden": "true" }, "/"),
            el("button", {
              type: "button",
              "aria-current": i === parts.length - 1 ? "location" : null,
              onclick: () => go(parts.slice(0, i + 1).join("/")),
            }, part),
          ]),
        );
        win.setTitle(path ? `Files: ${parts[parts.length - 1]}` : "Files");

        if (!entries.length) {
          list.replaceChildren(el("li", { class: "empty" },
            el("p", {}, "This folder is empty."),
            el("p", {}, "Drop files here, or use Upload."),
          ));
        } else {
          list.replaceChildren(...entries.map((entry) => el("li", {
            class: `file-row${entry.is_dir ? " is-dir" : ""}`,
            role: "option",
            "aria-selected": String(selected?.path === entry.path),
            onclick: () => { selected = entry; render(); },
            ondblclick: () => openEntry(entry),
          },
            glyph(entry.is_dir ? GLYPHS.folder : GLYPHS.file),
            el("span", { class: "name", title: entry.name }, entry.name),
            el("span", { class: "size" }, entry.is_dir ? "" : formatSize(entry.size)),
            el("span", { class: "when" }, formatWhen(entry.modified)),
          )));
        }
        renderActions();
      }

      function renderActions() {
        if (!selected) {
          const folders = entries.filter((e) => e.is_dir).length;
          const files = entries.length - folders;
          actions.replaceChildren(el("span", { class: "status" },
            `${folders} ${folders === 1 ? "folder" : "folders"}, ${files} ${files === 1 ? "file" : "files"}. Double-click to open.`));
          return;
        }
        const item = selected;
        actions.replaceChildren(
          el("button", { class: "btn primary", type: "button", onclick: () => openEntry(item) }, "Open"),
          !item.is_dir && el("a", {
            class: "btn", href: `/api/files/raw?${q({ path: item.path, download: 1 })}`,
            download: item.name, style: "display:inline-flex;align-items:center;text-decoration:none",
          }, "Download"),
          el("button", { class: "btn", type: "button", onclick: () => askRename(item) }, "Rename"),
          el("button", { class: "btn danger", type: "button", onclick: () => askDelete(item) }, "Delete"),
        );
      }

      function ask(label, initial, confirmText, onConfirm) {
        const input = el("input", { class: "field", value: initial, "aria-label": label, placeholder: label });
        const submit = async () => {
          try {
            await onConfirm(input.value);
            await load();
          } catch (err) {
            notice(err.message, true);
          }
        };
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") renderActions();
        });
        actions.replaceChildren(
          input,
          el("button", { class: "btn primary", type: "button", onclick: submit }, confirmText),
          el("button", { class: "btn", type: "button", onclick: renderActions }, "Cancel"),
        );
        input.focus();
        input.select();
      }

      function askNewFolder() {
        ask("Folder name", "New folder", "Make folder", (name) =>
          api("POST", "/api/files/folder", { parent: path, name }));
      }

      function askRename(item) {
        ask("New name", item.name, "Rename", async (name) => {
          const res = await api("POST", "/api/files/rename", { path: item.path, name });
          selected = { ...item, path: res.path, name };
        });
      }

      function askDelete(item) {
        actions.replaceChildren(
          el("span", { class: "status" }, `Delete ${item.name}${item.is_dir ? " and everything in it" : ""}? This can't be undone.`),
          el("span", { class: "grow", style: "flex:1" }),
          el("button", {
            class: "btn danger", type: "button",
            onclick: async () => {
              try {
                await api("DELETE", `/api/files?${q({ path: item.path })}`);
                notice(`Deleted ${item.name}.`);
                selected = null;
                load();
              } catch (err) { notice(err.message, true); }
            },
          }, "Delete"),
          el("button", { class: "btn", type: "button", onclick: renderActions }, "Keep it"),
        );
      }

      function go(nextPath) {
        selected = null;
        load(nextPath);
      }

      function openEntry(entry) {
        if (entry.is_dir) go(entry.path);
        else if (IMAGE_TYPES.test(entry.name)) openViewer(entry.path);
        else if (TEXT_TYPES.test(entry.name) || entry.size === 0) openNotepad(entry.path);
        else window.open(`/api/files/raw?${q({ path: entry.path })}`, "_blank", "noopener");
      }

      async function uploadFiles(fileList) {
        const files = [...fileList];
        for (const file of files) {
          try {
            await api("POST", `/api/files/upload?${q({ parent: path, name: file.name })}`, file);
          } catch (err) {
            notice(`${file.name}: ${err.message}`, true);
          }
        }
        if (files.length) notice(`Uploaded ${files.length} ${files.length === 1 ? "file" : "files"} to ${path || "Home"}.`);
        load();
      }

      upload.addEventListener("change", () => { uploadFiles(upload.files); upload.value = ""; });
      list.addEventListener("dragover", (e) => { e.preventDefault(); list.classList.add("drop-target"); });
      list.addEventListener("dragleave", () => list.classList.remove("drop-target"));
      list.addEventListener("drop", (e) => {
        e.preventDefault();
        list.classList.remove("drop-target");
        uploadFiles(e.dataTransfer.files);
      });
      list.addEventListener("keydown", (e) => {
        const index = entries.findIndex((x) => x.path === selected?.path);
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          const next = entries[Math.max(0, Math.min(entries.length - 1, index + (e.key === "ArrowDown" ? 1 : -1)))];
          if (next) { selected = next; render(); }
        } else if (e.key === "Enter" && selected) openEntry(selected);
        else if (e.key === "Backspace" && path) go(path.split("/").slice(0, -1).join("/"));
        else if (e.key === "Delete" && selected) askDelete(selected);
      });

      load();
    },
  });
  if (startPath) windows.get("files").reload(startPath);
}

function refreshFiles() {
  windows.get("files")?.reload();
}

function openViewer(path) {
  const name = path.split("/").pop();
  openWindow({
    key: `view:${path}`, title: name, icon: "image", width: 560, height: 460,
    build(win) {
      win.body.append(el("div", { class: "viewer" },
        el("img", { src: `/api/files/raw?${q({ path })}&t=${Date.now()}`, alt: name })));
    },
  });
}

// ---- Messages --------------------------------------------------------------

function openMessages() {
  openWindow({
    key: "messages", title: "Messages", icon: "messages", width: 660, height: 460,
    build(win) {
      let channel = "general";
      let lastId = 0;
      let channels = [];

      const channelList = el("ul", { class: "side-list", "aria-label": "Channels" });
      const newChannel = el("input", { class: "field", placeholder: "New channel", "aria-label": "New channel name", maxlength: 32 });
      const channelForm = el("form", { class: "channel-form" }, newChannel,
        el("button", { class: "btn", type: "submit" }, "Add"));
      const thread = el("div", { class: "thread", role: "log", "aria-live": "polite" });
      const input = el("input", { class: "field", placeholder: "Write a message", "aria-label": "Message", maxlength: 4000 });
      const composer = el("form", { class: "composer" }, input, el("button", { class: "btn primary", type: "submit" }, "Send"));
      const header = el("div", { class: "toolbar" });
      win.body.append(el("div", { class: "split" },
        el("div", { class: "split-side" }, channelForm, channelList),
        el("div", { class: "split-main" }, header, thread, composer),
      ));

      function renderHeader() {
        header.replaceChildren(
          el("strong", {}, `#${channel}`),
          el("span", { class: "grow" }),
          el("span", { class: "status" }, `Posting as ${settings.user_name}`),
        );
      }
      settingsListeners.add(renderHeader);
      win.onCleanup(() => settingsListeners.delete(renderHeader));

      function renderChannels() {
        const names = channels.includes(channel) ? channels : [channel, ...channels];
        channelList.replaceChildren(...names.map((name) => el("li", {},
          el("button", {
            type: "button",
            "aria-current": name === channel ? "true" : null,
            onclick: () => switchTo(name),
          }, `#${name}`))));
      }

      function addMessages(messages) {
        if (!messages.length) return;
        if (lastId === 0) thread.replaceChildren();
        const stick = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 40;
        for (const m of messages) {
          thread.append(el("article", { class: `msg${m.author === settings.user_name ? " mine" : ""}` },
            el("div", { class: "msg-head" },
              el("span", { class: "msg-author" }, m.author),
              el("time", { class: "msg-time", datetime: new Date(m.sent * 1000).toISOString() }, formatWhen(m.sent))),
            el("p", { class: "msg-body" }, m.body)));
          lastId = Math.max(lastId, m.id);
        }
        if (stick || messages.some((m) => m.author === settings.user_name)) thread.scrollTop = thread.scrollHeight;
      }

      let polling = false;
      async function poll() {
        if (polling) return;
        polling = true;
        try {
          const wanted = channel;
          const messages = await api("GET", `/api/messages?${q({ channel: wanted, after: lastId })}`);
          if (wanted === channel) addMessages(messages);
          channels = await api("GET", "/api/channels");
          renderChannels();
        } catch { /* The next poll retries. */ }
        polling = false;
      }

      function switchTo(name) {
        channel = name;
        lastId = 0;
        thread.replaceChildren(el("div", { class: "empty" },
          el("p", {}, `Nothing in #${name} yet.`),
          el("p", {}, "Anyone who opens PyOS on this server can read and post here."),
        ));
        renderHeader();
        renderChannels();
        poll();
        input.focus();
      }

      channelForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const name = newChannel.value.trim().toLowerCase().replace(/\s+/g, "-");
        if (!name) return;
        newChannel.value = "";
        switchTo(name);
      });

      composer.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        input.value = "";
        try {
          await api("POST", "/api/messages", { channel, author: settings.user_name, body: text });
          await poll();
        } catch (err) {
          input.value = text;
          notice(err.message, true);
        }
      });

      const timer = setInterval(poll, 2000);
      win.onCleanup(() => clearInterval(timer));
      switchTo("general");
    },
  });
}

// ---- Camera ----------------------------------------------------------------

function openCamera() {
  openWindow({
    key: "camera", title: "Camera", icon: "camera", width: 600, height: 480,
    build(win) {
      const stage = el("div", { class: "camera-stage" });
      const shoot = el("button", { class: "btn primary", type: "button", disabled: true }, "Take photo");
      const status = el("span", { class: "status" });
      const thumbSlot = el("span");
      win.body.append(stage, el("div", { class: "toolbar" }, shoot, thumbSlot, el("span", { class: "grow" }), status));

      let stream = null;
      const video = el("video", { autoplay: true, playsinline: true, muted: true });
      win.onCleanup(() => stream?.getTracks().forEach((t) => t.stop()));

      async function start() {
        if (!navigator.mediaDevices?.getUserMedia) {
          stage.replaceChildren(el("div", { class: "empty" },
            el("p", {}, "This browser can't use a camera here. Open PyOS at http://localhost so the browser allows camera access.")));
          return;
        }
        stage.replaceChildren(el("div", { class: "empty" }, el("p", {}, "Waiting for camera permission…")));
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          if (!document.body.contains(win.node)) { stream.getTracks().forEach((t) => t.stop()); return; }
          video.srcObject = stream;
          stage.replaceChildren(video);
          shoot.disabled = false;
          status.textContent = "Photos save to Pictures.";
        } catch (err) {
          const denied = err.name === "NotAllowedError";
          stage.replaceChildren(el("div", { class: "empty" },
            el("p", {}, denied
              ? "Camera access is blocked. Allow it in your browser's site settings, then try again."
              : "No camera was found. Connect one, then try again."),
            el("button", { class: "btn", type: "button", onclick: start }, "Try again")));
        }
      }

      shoot.addEventListener("click", () => {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        stage.classList.remove("flash");
        void stage.offsetWidth;
        stage.classList.add("flash");
        canvas.toBlob(async (blob) => {
          const stamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, "").replace("T", "-");
          try {
            const res = await api("POST", `/api/files/upload?${q({ parent: "Pictures", name: `photo-${stamp}.png` })}`, blob);
            status.textContent = `Saved ${res.path.split("/").pop()} to Pictures.`;
            thumbSlot.replaceChildren(el("img", {
              class: "shot-thumb", src: URL.createObjectURL(blob), alt: "Open the last photo",
              title: "Open the last photo", onclick: () => openViewer(res.path),
            }));
            refreshFiles();
          } catch (err) { notice(err.message, true); }
        }, "image/png");
      });

      start();
    },
  });
}

// ---- Terminal --------------------------------------------------------------

function openTerminal() {
  openWindow({
    key: "terminal", title: "Terminal", icon: "terminal", width: 620, height: 380,
    build(win) {
      let cwd = "";
      const history = [];
      let historyIndex = 0;

      const screen = el("div", { class: "term" });
      const promptLabel = el("span", { class: "prompt" });
      const input = el("input", { "aria-label": "Command", autocomplete: "off", spellcheck: false, autocapitalize: "off" });
      const line = el("div", { class: "term-line" }, promptLabel, input);
      screen.append(el("pre", { class: "dim" }, "PyOS terminal. Type help to see the commands."), line);
      win.body.append(screen);
      screen.addEventListener("click", () => { if (!window.getSelection().toString()) input.focus(); });

      const prompt = () => `${settings.user_name.toLowerCase().replace(/\s+/g, "")} ~/${cwd}$`;
      const renderPrompt = () => { promptLabel.textContent = prompt(); };
      settingsListeners.add(renderPrompt);
      win.onCleanup(() => settingsListeners.delete(renderPrompt));
      renderPrompt();

      input.addEventListener("keydown", async (e) => {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault();
          historyIndex = Math.max(0, Math.min(history.length, historyIndex + (e.key === "ArrowUp" ? -1 : 1)));
          input.value = history[historyIndex] ?? "";
          return;
        }
        if (e.key === "l" && e.ctrlKey) {
          e.preventDefault();
          screen.querySelectorAll("pre").forEach((p) => p.remove());
          return;
        }
        if (e.key !== "Enter") return;
        const text = input.value;
        input.value = "";
        if (text.trim()) history.push(text);
        historyIndex = history.length;
        line.before(el("pre", {}, el("span", { class: "prompt" }, prompt()), ` ${text}`));
        if (!text.trim()) return;
        input.disabled = true;
        try {
          const res = await api("POST", "/api/terminal", { cwd, line: text });
          if (res.clear) screen.querySelectorAll("pre").forEach((p) => p.remove());
          else if (res.output) line.before(el("pre", {}, res.output));
          cwd = res.cwd;
          renderPrompt();
          if (/^\s*(mkdir|touch|rm|mv|echo)\b/.test(text)) refreshFiles();
        } catch (err) {
          line.before(el("pre", { class: "dim" }, err.message));
        }
        input.disabled = false;
        input.focus();
        screen.scrollTop = screen.scrollHeight;
      });
      setTimeout(() => input.focus(), 0);
    },
  });
}

// ---- Settings --------------------------------------------------------------

function openSettings() {
  openWindow({
    key: "settings", title: "Settings", icon: "settings", width: 520, height: 480,
    build(win) {
      const status = el("span", { class: "status" }, "Changes save right away.");
      const done = (promise) => promise
        .then(() => { status.textContent = "Saved"; status.classList.remove("error"); })
        .catch((err) => { status.textContent = err.message; status.classList.add("error"); });

      const name = el("input", { class: "field", id: "set-name", value: settings.user_name, maxlength: 40, style: "width:100%;max-width:320px" });
      name.addEventListener("change", () => {
        if (!name.value.trim()) { name.value = settings.user_name; return; }
        done(saveSettings({ user_name: name.value }));
      });

      const radios = (group, options) => el("div", { class: "choices" }, options.map(([value, label, swatch]) =>
        el("label", { class: "choice" },
          el("input", {
            type: "radio", name: group, value, checked: settings[group] === value,
            onchange: () => done(saveSettings({ [group]: value })),
          }),
          swatch && el("span", { class: "swatch", style: `background:${swatch}` }),
          label)));

      const snapBox = el("input", {
        type: "checkbox", checked: settings.snap_to_grid,
        onchange: () => done(saveSettings({ snap_to_grid: snapBox.checked })),
      });

      win.body.append(
        el("div", { class: "settings" },
          el("div", { class: "setting" },
            el("label", { for: "set-name" }, "Your name"),
            name,
            el("p", { class: "hint" }, "Shown on your messages and in the terminal prompt.")),
          el("fieldset", { class: "setting" },
            el("legend", {}, "Mat color"),
            radios("mat", [["green", "Green", "#2F5D4E"], ["slate", "Slate", "#3B4859"], ["black", "Black", "#1D211F"]])),
          el("fieldset", { class: "setting" },
            el("legend", {}, "Windows"),
            radios("theme", [["system", "Match my device"], ["light", "Light"], ["dark", "Dark"]])),
          el("div", { class: "setting" },
            el("label", { class: "toggle" }, snapBox, "Snap windows to the mat grid"),
            el("p", { class: "hint" }, "When you drop or resize a window, it lines up with the grid squares.")),
        ),
        el("div", { class: "toolbar" }, status),
      );
    },
  });
}

// ---- Boot ------------------------------------------------------------------

// Apps in src/frontend/apps/ load after this file, so look them up when clicked.
const APPS = [
  ["Files", "files", () => openFiles()],
  ["Notepad", "notepad", () => openNotepad()],
  ["Calculator", "calculator", () => openCalculator()],
  ["Browser", "browser", () => openBrowser()],
  ["Messages", "messages", () => openMessages()],
  ["Camera", "camera", () => openCamera()],
  ["Terminal", "terminal", () => openTerminal()],
  ["Off My Lawn", "game", () => openGame()],
  ["Settings", "settings", () => openSettings()],
];

async function boot() {
  const launchers = document.getElementById("launchers");
  for (const [label, icon, open] of APPS) {
    launchers.append(el("button", { class: "launcher", type: "button", onclick: open }, appIcon(icon), label));
  }
  buildMatScale();
  buildRuler();
  try {
    Object.assign(settings, await api("GET", "/api/settings"));
  } catch (err) {
    notice(err.message, true);
  }
  applySettings();
}

document.addEventListener("DOMContentLoaded", boot);
