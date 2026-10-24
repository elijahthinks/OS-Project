/* Private browser: pages are fetched and cleaned by the PyOS server, then shown in a locked-down frame. */
"use strict";

const BROWSER_GLYPHS = {
  back: ["M10 3.5L5.5 8l4.5 4.5"],
  forward: ["M6 3.5L10.5 8 6 12.5"],
  reload: ["M12.5 8a4.5 4.5 0 1 1-1.3-3.2", "M12.5 3v2.5H10"],
};

let browserCount = 0;

function openBrowser(startInput = "") {
  openWindow({
    key: `browser:${++browserCount}`, title: "Browser", width: 940, height: 620,
    build(win) {
      // History lives only in this window and is gone when it closes.
      const history = [];
      let index = -1;
      let travelling = false;
      let typing = false;       // don't overwrite an address the person is in the middle of typing

      const iconBtn = (label, paths, onclick) =>
        el("button", { class: "btn icon-btn", type: "button", "aria-label": label, title: label, onclick }, glyph(paths));
      const back = iconBtn("Back", BROWSER_GLYPHS.back, () => travel(-1));
      const forward = iconBtn("Forward", BROWSER_GLYPHS.forward, () => travel(1));
      const reload = iconBtn("Reload", BROWSER_GLYPHS.reload, () => frame.contentWindow?.location.reload());
      const address = el("input", {
        class: "field browser-address", "aria-label": "Address or search", spellcheck: false, autocomplete: "off",
        placeholder: "Search privately or type an address",
      });
      const form = el("form", { class: "browser-form", onsubmit: (e) => { e.preventDefault(); go(address.value); } },
        address, el("button", { class: "btn primary", type: "submit" }, "Go"));
      const status = el("span", { class: "status" });
      const frame = el("iframe", {
        class: "browser-frame", title: "Web page",
        // Matches the policy the server sends: no scripts, no pop-ups.
        sandbox: "allow-same-origin allow-forms",
        referrerpolicy: "no-referrer",
      });

      win.body.append(
        el("div", { class: "toolbar browser-bar" }, back, forward, reload, form),
        frame,
        el("div", { class: "browser-foot" },
          el("span", { class: "status" }, "Private: sites see PyOS, not you. Nothing you visit is saved."),
          el("span", { class: "grow" }), status),
      );

      address.addEventListener("input", () => { typing = true; });

      function go(text) {
        if (!text.trim()) return;
        typing = false;
        load(`/api/browse/page?${q({ input: text.trim() })}`);
      }

      function load(src) {
        status.textContent = "Loading…";
        try {
          frame.contentWindow.location.replace(src);
        } catch {
          frame.src = src;
        }
      }

      function travel(step) {
        const next = index + step;
        if (next < 0 || next >= history.length) return;
        index = next;
        travelling = true;
        load(history[index]);
        renderButtons();
      }

      function renderButtons() {
        back.disabled = index <= 0;
        forward.disabled = index >= history.length - 1;
      }

      frame.addEventListener("load", () => {
        let doc;
        try {
          doc = frame.contentDocument;
        } catch {
          return;
        }
        if (!doc) return;
        const here = frame.contentWindow.location.pathname + frame.contentWindow.location.search;
        if (!here.startsWith("/api/browse/page")) return;
        if (!travelling && history[index] !== here) {
          history.splice(index + 1);
          history.push(here);
          index = history.length - 1;
        }
        travelling = false;
        renderButtons();

        const realUrl = doc.querySelector('meta[name="pyos-url"]')?.content || "";
        if (!typing) address.value = realUrl;
        const title = doc.title?.trim();
        win.setTitle(title ? `Browser: ${title}` : "Browser");
        status.textContent = realUrl ? new URL(realUrl).hostname : "";
      });

      renderButtons();
      load(startInput ? `/api/browse/page?${q({ input: startInput })}` : "/api/browse/page");
      setTimeout(() => address.focus(), 0);
    },
  });
}
