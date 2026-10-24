/* Off My Lawn, by elijahthinks: https://github.com/elijahthinks/off-my-lawn */
"use strict";

function openGame() {
  openWindow({
    key: "game", title: "Off My Lawn", width: 880, height: 560,
    build(win) {
      const frame = el("iframe", {
        class: "game-frame", title: "Off My Lawn game",
        src: "games/off-my-lawn/index.html",
        allow: "fullscreen; autoplay",
      });
      const fullscreen = el("button", {
        class: "btn", type: "button",
        onclick: () => frame.requestFullscreen?.().catch(() => notice("Full screen isn't available in this browser.", true)),
      }, "Full screen");
      win.body.append(
        el("div", { class: "toolbar" }, fullscreen,
          el("span", { class: "status" }, "Drag to aim Biscuit, let go to pounce, tap mid-air to bark. Esc pauses."),
          el("span", { class: "grow" })),
        frame,
      );
      // Keyboard controls go to the game whenever its window is in front.
      win.node.addEventListener("pointerdown", (e) => { if (!e.target.closest("button")) frame.focus(); });
      frame.addEventListener("load", () => frame.focus());
    },
  });
}
