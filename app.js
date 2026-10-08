// Browser port of Projectos.py so the prototype can be served as a static site (e.g. on Vercel).

// ==== Storage helpers (localStorage may be unavailable in private mode) ====
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch { /* ignore */ }
  },
};

// ==== Window manager ====
let zTop = 10;
let openCount = 0;
const tasks = document.getElementById("tasks");

function createWindow(title, onClose) {
  const win = document.createElement("section");
  win.className = "window";
  const offset = (openCount++ % 6) * 28;
  win.style.left = Math.min(60 + offset, window.innerWidth - 300) + "px";
  win.style.top = 40 + offset + "px";
  win.style.zIndex = ++zTop;

  const bar = document.createElement("div");
  bar.className = "titlebar";
  bar.innerHTML = `<span></span><button aria-label="Close">&times;</button>`;
  bar.querySelector("span").textContent = title;

  const body = document.createElement("div");
  body.className = "body";
  win.append(bar, body);
  document.getElementById("desktop").append(win);

  const taskBtn = document.createElement("button");
  taskBtn.textContent = title;
  taskBtn.onclick = () => { win.style.zIndex = ++zTop; };
  tasks.append(taskBtn);

  win.addEventListener("pointerdown", () => { win.style.zIndex = ++zTop; });

  bar.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    const startX = e.clientX - win.offsetLeft;
    const startY = e.clientY - win.offsetTop;
    bar.setPointerCapture(e.pointerId);
    const move = (ev) => {
      win.style.left = Math.max(0, ev.clientX - startX) + "px";
      win.style.top = Math.max(0, ev.clientY - startY) + "px";
    };
    const up = () => {
      bar.removeEventListener("pointermove", move);
      bar.removeEventListener("pointerup", up);
    };
    bar.addEventListener("pointermove", move);
    bar.addEventListener("pointerup", up);
  });

  bar.querySelector("button").onclick = () => {
    if (onClose) onClose();
    win.remove();
    taskBtn.remove();
  };

  return body;
}

function button(label, onClick) {
  const b = document.createElement("button");
  b.className = "btn";
  b.textContent = label;
  b.onclick = onClick;
  return b;
}

// ==== File Explorer ====
function openFileExplorer() {
  const body = createWindow("File Explorer");
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.hidden = true;

  const list = document.createElement("ul");
  list.className = "files";
  const preview = document.createElement("div");
  preview.className = "preview";
  const hint = document.createElement("p");
  hint.className = "muted";
  hint.textContent = "Files are opened locally in your browser and never uploaded.";

  input.onchange = () => {
    list.innerHTML = "";
    preview.innerHTML = "";
    for (const file of input.files) {
      const li = document.createElement("li");
      li.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      li.onclick = () => showPreview(file, preview);
      list.append(li);
    }
  };

  body.append(button("Browse Files", () => input.click()), input, hint, list, preview);
}

function showPreview(file, target) {
  target.innerHTML = "";
  if (file.type.startsWith("image/")) {
    const img = document.createElement("img");
    img.src = URL.createObjectURL(file);
    img.onload = () => URL.revokeObjectURL(img.src);
    target.append(img);
  } else if (file.type.startsWith("text/") || file.size < 200 * 1024) {
    file.text().then((text) => {
      const pre = document.createElement("pre");
      pre.textContent = text.slice(0, 20000);
      target.append(pre);
    });
  } else {
    target.textContent = "No preview available.";
  }
}

// ==== Camera ====
function openCamera() {
  let stream = null;
  const body = createWindow("Camera", () => stream && stream.getTracks().forEach((t) => t.stop()));
  const video = document.createElement("video");
  video.autoplay = true;
  video.playsInline = true;
  video.muted = true;
  const status = document.createElement("p");
  status.className = "muted";
  status.textContent = "Requesting camera access…";
  const shots = document.createElement("div");

  const snap = button("Take Photo", () => {
    if (!video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = "photo.png";
    link.textContent = "Download photo";
    shots.replaceChildren(canvas, link);
  });

  body.append(status, video, snap, shots);

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    status.textContent = "Camera is not supported in this browser (HTTPS is required).";
    return;
  }
  navigator.mediaDevices.getUserMedia({ video: true })
    .then((s) => {
      stream = s;
      if (!body.isConnected) { s.getTracks().forEach((t) => t.stop()); return; }
      video.srcObject = s;
      status.remove();
    })
    .catch((err) => { status.textContent = "Could not open camera: " + err.message; });
}

// ==== Messaging App ====
function openMessaging() {
  const body = createWindow("Messenger");
  const chat = document.createElement("div");
  chat.className = "chat";
  const row = document.createElement("form");
  row.className = "row";
  const entry = document.createElement("input");
  entry.type = "text";
  entry.placeholder = "Type a message";
  entry.style.flex = "1";

  row.onsubmit = (e) => {
    e.preventDefault();
    const text = entry.value;
    if (text) {
      chat.append("You: " + text + "\n");
      chat.scrollTop = chat.scrollHeight;
      entry.value = "";
    }
  };
  const send = button("Send");
  send.type = "submit";
  row.append(entry, send);
  body.append(chat, row);
  entry.focus();
}

// ==== Notes App ====
function openNotes() {
  const body = createWindow("Notes");
  const area = document.createElement("textarea");
  area.value = store.get("note.txt", "");
  const status = document.createElement("span");
  status.className = "muted";

  const save = button("Save", () => {
    store.set("note.txt", area.value);
    status.textContent = "Note saved in this browser.";
  });
  const download = button("Download note.txt", () => {
    const blob = new Blob([area.value], { type: "text/plain" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "note.txt";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });

  const row = document.createElement("div");
  row.className = "row";
  row.append(save, download, status);
  body.append(area, row);
}

// ==== Settings App ====
function applyTheme(dark) {
  document.body.classList.toggle("dark", dark);
  store.set("dark_mode", dark ? "1" : "0");
}

function openSettings() {
  const body = createWindow("Settings");
  body.append(button("Toggle Dark Mode", () => applyTheme(!document.body.classList.contains("dark"))));
}

// ==== Desktop ====
const apps = [
  ["File Explorer", openFileExplorer],
  ["Camera", openCamera],
  ["Messaging", openMessaging],
  ["Notes", openNotes],
  ["Settings", openSettings],
];

const icons = document.getElementById("icons");
for (const [label, cmd] of apps) {
  const b = document.createElement("button");
  b.className = "icon";
  b.textContent = label;
  b.onclick = cmd;
  icons.append(b);
}

applyTheme(store.get("dark_mode", "0") === "1");

const clock = document.getElementById("clock");
const tick = () => { clock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
tick();
setInterval(tick, 10000);
