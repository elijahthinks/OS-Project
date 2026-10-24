/* Notepad: edit text files in the home folder, with an AI help panel (not connected yet). */
"use strict";

let untitledCount = 0;
let aiStatus = null;

function openNotepad(path = null) {
  const key = path ? `notepad:${path}` : `notepad:new-${++untitledCount}`;
  openWindow({
    key, title: path ? path.split("/").pop() : "Untitled", icon: "notepad", width: 780, height: 520,
    build(win) {
      let filePath = path;
      let savedText = "";

      const area = el("textarea", { class: "pad-area", spellcheck: true, "aria-label": "Text", placeholder: "Start typing" });
      const fileLabel = el("span", { class: "status pad-file" });
      const aiBtn = el("button", { class: "btn", type: "button", "aria-pressed": "true" }, "AI help");
      const counts = el("span", { class: "status" });
      const caret = el("span", { class: "status" });
      const footer = el("div", { class: "pad-foot" });
      const panel = el("aside", { class: "pad-ai", "aria-label": "AI help" });
      const drawer = el("div", { class: "pad-drawer", hidden: true });

      win.body.append(
        el("div", { class: "toolbar" },
          el("button", { class: "btn", type: "button", onclick: () => openNotepad() }, "New"),
          el("button", { class: "btn", type: "button", onclick: () => showOpen() }, "Open"),
          el("button", { class: "btn primary", type: "button", onclick: () => save() }, "Save"),
          el("button", { class: "btn", type: "button", onclick: () => showSaveAs() }, "Save as"),
          fileLabel, el("span", { class: "grow" }), aiBtn),
        drawer,
        el("div", { class: "pad-split" }, area, panel),
        footer,
      );

      const name = () => (filePath ? filePath.split("/").pop() : "Untitled");
      const dirty = () => area.value !== savedText;

      function update() {
        const text = area.value;
        const words = (text.match(/\S+/g) || []).length;
        counts.textContent = `${words} ${words === 1 ? "word" : "words"}, ${text.length} ${text.length === 1 ? "character" : "characters"}`;
        const before = text.slice(0, area.selectionStart);
        const line = before.split("\n").length;
        caret.textContent = `Line ${line}, column ${before.length - before.lastIndexOf("\n")}`;
        fileLabel.textContent = filePath ? `~/${filePath}${dirty() ? " (unsaved changes)" : ""}` : "Not saved yet";
        win.setTitle(`${name()}${dirty() ? " (edited)" : ""}`);
      }

      function showFooter(...content) {
        footer.replaceChildren(...(content.length ? content : [counts, el("span", { class: "grow" }), caret]));
      }

      async function save() {
        if (!filePath) return showSaveAs();
        try {
          await api("PUT", "/api/files/text", { path: filePath, content: area.value });
          savedText = area.value;
          update();
          refreshFiles();
          notice(`Saved ${name()}.`);
          return true;
        } catch (err) {
          notice(err.message, true);
          return false;
        }
      }

      function showSaveAs() {
        const field = el("input", { class: "field", value: filePath || "Documents/Untitled.txt", "aria-label": "Save as", spellcheck: false });
        const submit = async () => {
          let target = field.value.trim().replace(/^~?\/+/, "");
          if (!target) return;
          if (!/\.[\w]+$/.test(target)) target += ".txt";
          try {
            const list = await api("GET", `/api/files?${q({ path: target.split("/").slice(0, -1).join("/") })}`);
            if (list.entries.some((e) => e.path === target) && target !== filePath &&
                field.dataset.confirmed !== target) {
              field.dataset.confirmed = target;
              drawerStatus.textContent = `${target.split("/").pop()} already exists. Select Save again to replace it.`;
              return;
            }
            await api("PUT", "/api/files/text", { path: target, content: area.value });
            filePath = target;
            savedText = area.value;
            drawer.hidden = true;
            update();
            refreshFiles();
            notice(`Saved ${name()}.`);
          } catch (err) {
            drawerStatus.textContent = err.message;
          }
        };
        const drawerStatus = el("span", { class: "status error" });
        field.addEventListener("keydown", (e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") drawer.hidden = true;
        });
        drawer.replaceChildren(
          el("label", { class: "pad-drawer-label" }, "Save in your home folder as"),
          el("div", { class: "pad-drawer-row" }, field,
            el("button", { class: "btn primary", type: "button", onclick: submit }, "Save"),
            el("button", { class: "btn", type: "button", onclick: () => { drawer.hidden = true; area.focus(); } }, "Cancel")),
          drawerStatus);
        drawer.hidden = false;
        field.focus();
        field.setSelectionRange(field.value.lastIndexOf("/") + 1, field.value.lastIndexOf(".") > 0 ? field.value.lastIndexOf(".") : field.value.length);
      }

      async function showOpen() {
        drawer.replaceChildren(el("p", { class: "status" }, "Finding text files…"));
        drawer.hidden = false;
        try {
          const files = await api("GET", "/api/files/text-files");
          drawer.replaceChildren(
            el("div", { class: "pad-drawer-row" },
              el("span", { class: "pad-drawer-label" }, files.length ? "Open a text file" : "There are no text files in your home folder yet."),
              el("span", { class: "grow" }),
              el("button", { class: "btn", type: "button", onclick: () => { drawer.hidden = true; } }, "Cancel")),
            files.length ? el("ul", { class: "pad-open-list" }, ...files.map((f) => el("li", {},
              el("button", {
                type: "button",
                onclick: () => {
                  drawer.hidden = true;
                  if (!filePath && !area.value) win.close();
                  openNotepad(f.path);
                },
              }, el("span", {}, f.path), el("span", { class: "status" }, formatWhen(f.modified)))))) : null);
        } catch (err) {
          drawer.replaceChildren(el("p", { class: "status error" }, err.message));
        }
      }

      // ---- AI panel ----------------------------------------------------------

      const aiResult = el("div", { class: "pad-ai-result", role: "status", "aria-live": "polite" });
      const question = el("input", { class: "field", placeholder: "Ask a question about this note", "aria-label": "Question about this note" });

      function selectedText() {
        const { selectionStart: start, selectionEnd: end } = area;
        return start !== end ? { text: area.value.slice(start, end), start, end } : { text: area.value, start: 0, end: area.value.length };
      }

      async function runAI(action, label) {
        const target = selectedText();
        aiResult.replaceChildren(el("p", { class: "status" }, `${label}…`));
        try {
          const res = await api("POST", "/api/ai/assist", { action, text: target.text, question: question.value });
          // When an AI model is connected, its answer lands here with ways to use it.
          const useIt = (mode) => {
            const before = mode === "replace" ? area.value.slice(0, target.start) : `${area.value.slice(0, target.end)}\n\n`;
            area.value = before + res.text + area.value.slice(target.end);
            update();
            aiResult.replaceChildren();
          };
          aiResult.replaceChildren(
            el("p", { class: "pad-ai-answer" }, res.text),
            action === "ask" ? null : el("div", { class: "pad-ai-actions" },
              el("button", { class: "btn primary", type: "button", onclick: () => useIt("replace") }, "Replace"),
              el("button", { class: "btn", type: "button", onclick: () => useIt("insert") }, "Add below")));
        } catch (err) {
          aiResult.replaceChildren(el("p", { class: "pad-ai-note" }, err.message));
        }
        aiResult.scrollIntoView({ block: "nearest" });
      }

      async function renderAI() {
        try {
          aiStatus ??= await api("GET", "/api/ai");
        } catch (err) {
          panel.replaceChildren(el("p", { class: "status error" }, err.message));
          return;
        }
        const ask = aiStatus.actions.find((a) => a.id === "ask");
        panel.replaceChildren(
          el("div", { class: "panel-head" },
            el("h3", { class: "pad-ai-title" }, "AI help"),
            el("button", { class: "link-btn", type: "button", onclick: () => aiBtn.click() }, "Hide")),
          el("p", { class: "pad-ai-state" }, aiStatus.connected ? "Connected" : "Not connected yet"),
          el("p", { class: "status" }, "Works on the text you select, or the whole note if nothing is selected."),
          el("div", { class: "pad-ai-buttons" }, ...aiStatus.actions.filter((a) => a.id !== "ask").map((a) =>
            el("button", { class: "btn", type: "button", title: a.about, onclick: () => runAI(a.id, a.label) }, a.label))),
          ask && el("form", {
            class: "pad-ai-ask",
            onsubmit: (e) => { e.preventDefault(); runAI("ask", ask.label); },
          }, question, el("button", { class: "btn", type: "submit" }, "Ask")),
          aiResult,
        );
      }

      aiBtn.addEventListener("click", () => {
        const open = aiBtn.getAttribute("aria-pressed") !== "true";
        aiBtn.setAttribute("aria-pressed", String(open));
        panel.hidden = !open;
      });

      // ---- Closing with unsaved changes ----------------------------------------

      win.confirmClose = () => {
        if (!dirty()) return true;
        win.restore();
        showFooter(
          el("span", { class: "status" }, `Save changes to ${name()} before closing?`),
          el("span", { class: "grow" }),
          el("button", { class: "btn primary", type: "button", onclick: async () => { if (await save()) win.close(); } }, "Save"),
          el("button", { class: "btn danger", type: "button", onclick: () => win.close() }, "Don't save"),
          el("button", { class: "btn", type: "button", onclick: () => { showFooter(); area.focus(); } }, "Cancel"),
        );
        return false;
      };

      area.addEventListener("input", update);
      for (const evt of ["keyup", "click", "select"]) area.addEventListener(evt, update);
      win.node.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
      });

      if (isSmallScreen()) {
        aiBtn.setAttribute("aria-pressed", "false");
        panel.hidden = true;
      }
      showFooter();
      renderAI();
      if (filePath) {
        area.disabled = true;
        api("GET", `/api/files/text?${q({ path: filePath })}`)
          .then((data) => { area.value = savedText = data.content; })
          .catch((err) => { notice(err.message, true); filePath = null; })
          .finally(() => { area.disabled = false; update(); area.focus(); });
      } else {
        update();
        setTimeout(() => area.focus(), 0);
      }
    },
  });
}
