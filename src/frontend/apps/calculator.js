/* Calculator: type math the way you'd write it, see every step, solve equations. */
"use strict";

let mathGuide = null;

function openCalculator() {
  openWindow({
    key: "calculator", title: "Calculator", width: 760, height: 600,
    build(win) {
      let angle = "deg";
      const saved = {};          // letters the person has saved, plus ans
      const history = [];

      const input = el("input", {
        class: "calc-input", "aria-label": "Math to work out", autocomplete: "off", spellcheck: false,
        placeholder: "Try 15% of 80, sqrt(144), or 2x + 3 = 11",
      });
      const angleBtn = el("button", { class: "btn", type: "button", title: "Switch between degrees and radians for sin, cos and tan" });
      const guideBtn = el("button", { class: "btn", type: "button", "aria-pressed": "true" }, "Guide");
      const result = el("output", { class: "calc-result", "aria-live": "polite" });
      const steps = el("ol", { class: "calc-steps" });
      const stepsHead = el("h3", { class: "calc-subhead" }, "How it works");
      const savedRow = el("div", { class: "calc-saved" });
      const historyList = el("ul", { class: "calc-history", "aria-label": "Earlier calculations" });
      const guide = el("aside", { class: "calc-guide", "aria-label": "Guide" });

      const keys = el("div", { class: "calc-keys" });
      const workArea = el("div", { class: "calc-work" }, result, stepsHead, steps, savedRow, historyList);
      const main = el("div", { class: "calc-main" },
        el("div", { class: "calc-entry" }, input,
          el("button", { class: "btn primary", type: "button", onclick: () => run() }, "Work it out")),
        el("div", { class: "toolbar calc-bar" }, angleBtn, guideBtn, el("span", { class: "grow" }),
          el("button", { class: "btn", type: "button", onclick: () => { input.value = ""; showIdle(); input.focus(); } }, "Clear")),
        workArea, keys);
      win.body.append(el("div", { class: "calc" }, main, guide));

      function renderAngle() {
        angleBtn.textContent = angle === "deg" ? "Angles: degrees" : "Angles: radians";
      }
      angleBtn.addEventListener("click", () => {
        angle = angle === "deg" ? "rad" : "deg";
        renderAngle();
        if (input.value.trim()) run();
      });
      renderAngle();

      guideBtn.addEventListener("click", () => {
        const open = guideBtn.getAttribute("aria-pressed") !== "true";
        guideBtn.setAttribute("aria-pressed", String(open));
        guide.hidden = !open;
      });

      function insert(text) {
        const start = input.selectionStart ?? input.value.length;
        const end = input.selectionEnd ?? input.value.length;
        input.value = input.value.slice(0, start) + text + input.value.slice(end);
        const caret = start + text.length - (text.endsWith("()") ? 1 : 0);
        input.focus();
        input.setSelectionRange(caret, caret);
      }

      // Functions on the left, a standard number pad on the right.
      const FUNCTION_KEYS = [
        ["sin", "sin("], ["cos", "cos("], ["tan", "tan("], ["√", "sqrt("],
        ["log", "log("], ["ln", "ln("], ["n!", "!"], ["xʸ", "^"],
        ["(", "("], [")", ")"], ["%", "%"], ["π", "π"],
        ["x", "x"], ["ans", "ans"], ["=", " = "], ["⌫", null],
      ];
      const NUMBER_KEYS = [
        ["7", "7"], ["8", "8"], ["9", "9"], ["÷", "÷"],
        ["4", "4"], ["5", "5"], ["6", "6"], ["×", "×"],
        ["1", "1"], ["2", "2"], ["3", "3"], ["−", "−"],
        ["0", "0"], [".", "."], ["Go", "run"], ["+", "+"],
      ];
      const KEY_NAMES = { "⌫": "Delete", "xʸ": "Power", "√": "Square root", "n!": "Factorial", "Go": "Work it out" };

      function backspace() {
        const pos = input.selectionStart ?? input.value.length;
        if (pos > 0) {
          input.value = input.value.slice(0, pos - 1) + input.value.slice(pos);
          input.setSelectionRange(pos - 1, pos - 1);
        }
        input.focus();
      }

      const pad = (list, kind) => el("div", { class: `calc-pad ${kind}` }, ...list.map(([label, value]) =>
        el("button", {
          class: `calc-key${value === "run" ? " primary" : ""}${/^[0-9.]$/.test(label) ? " digit" : ""}`,
          type: "button", "aria-label": KEY_NAMES[label], title: KEY_NAMES[label],
          onclick: () => (value === "run" ? run() : value === null ? backspace() : insert(value)),
        }, label)));
      keys.append(pad(FUNCTION_KEYS, "functions"), pad(NUMBER_KEYS, "numbers"));

      function showIdle() {
        result.className = "calc-result idle";
        result.textContent = "Type some math and press Enter.";
        steps.replaceChildren();
        stepsHead.hidden = true;
      }

      async function run(text = input.value) {
        if (!text.trim()) return showIdle();
        try {
          const res = await api("POST", "/api/math", { expression: text, angle, variables: saved });
          result.className = "calc-result";
          result.textContent = res.result;
          steps.replaceChildren(...res.steps.map((s) => el("li", {}, s)));
          stepsHead.hidden = !res.steps.length;
          if (res.kind === "assign") saved[res.variable] = res.value;
          if (res.kind === "value") saved.ans = res.value;
          if (res.kind === "solve" && res.solutions.length === 1) saved.ans = res.solutions[0];
          remember(text, res.result);
          renderSaved();
        } catch (err) {
          result.className = "calc-result error";
          result.textContent = err.message;
          steps.replaceChildren();
          stepsHead.hidden = true;
        }
      }

      function remember(text, answer) {
        if (history[0]?.text === text) return;
        history.unshift({ text, answer });
        history.length = Math.min(history.length, 12);
        historyList.replaceChildren(...history.map((h) => el("li", {},
          el("button", {
            type: "button", title: "Use this again",
            onclick: () => { input.value = h.text; run(); },
          }, el("span", {}, h.text), el("span", { class: "calc-history-answer" }, h.answer)))));
      }

      function renderSaved() {
        const names = Object.keys(saved);
        savedRow.replaceChildren(...(names.length ? [el("span", { class: "status" }, "Saved:")] : []),
          ...names.map((name) => el("button", {
            class: "chip", type: "button", title: `Insert ${name}`, onclick: () => insert(name),
          }, `${name} = ${formatNumber(saved[name])}`)));
      }

      async function renderGuide() {
        try {
          mathGuide ??= await api("GET", "/api/math/guide");
        } catch (err) {
          guide.replaceChildren(el("p", { class: "status error" }, err.message));
          return;
        }
        const groups = new Map();
        for (const entry of mathGuide) {
          if (!groups.has(entry.group)) groups.set(entry.group, []);
          groups.get(entry.group).push(entry);
        }
        guide.replaceChildren(
          el("div", { class: "panel-head" },
            el("h3", { class: "calc-subhead" }, "Guide"),
            el("button", { class: "link-btn", type: "button", onclick: () => guideBtn.click() }, "Hide")),
          el("p", { class: "calc-guide-intro" }, "Pick an example to try it. Every answer shows its steps."),
          ...[...groups].map(([group, entries]) => el("details", { open: group === "Basics" || group === "Equations" },
            el("summary", {}, group),
            el("dl", {}, ...entries.flatMap((e) => [
              el("dt", {}, e.name),
              el("dd", {}, e.about, " ",
                el("button", {
                  class: "link-btn", type: "button",
                  onclick: () => { input.value = e.example; run(); },
                }, `Try ${e.example}`)),
            ])))));
      }

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); run(); }
      });

      if (isSmallScreen()) {
        guideBtn.setAttribute("aria-pressed", "false");
        guide.hidden = true;
      }
      showIdle();
      renderGuide();
      setTimeout(() => input.focus(), 0);
    },
  });
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(10)));
}
