// Code popups on a static page: codes are wrapped, a click opens the card, Esc closes it,
// redrawn content is wrapped too, and the page's own text and behavior are unchanged.
// Usage: node glossary_popups.cjs PAGE.html URL EXPECTED_CODE [REDRAW_BUTTON_SELECTOR NEW_CODE]
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const [file, url, code, redraw, newCode] = process.argv.slice(2);
const html = fs.readFileSync(file, "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", url, pretendToBeVisual: true,
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tick = () => new Promise(r => w.setTimeout(r, 0));

(async () => {
  await tick();
  ok(errors.length === 0, "no script errors " + errors.join(";"));
  const spans = [...d.querySelectorAll("span.gl")];
  ok(spans.length > 0, `codes are wrapped (${spans.length})`);
  ok(d.querySelector("nav.usm .gl") === null, "the tab bar is left alone");
  ok([...d.querySelectorAll("h1 .gl, h2 .gl, h3 .gl, a .gl, button .gl, textarea .gl")].length === 0, "headings, links, and buttons are left alone");
  ok([...d.querySelectorAll("[data-gl-def] .gl")].every(s => s.textContent !== s.closest("[data-gl-def]").dataset.glDef), "a code is not underlined where it is defined");
  const target = spans.find(s => s.textContent === code);
  ok(!!target, `${code} is wrapped`);
  if (!target) return;
  ok(target.getAttribute("role") === "button" && target.tabIndex === 0, "a wrapped code is a keyboard-focusable button");
  target.click();
  let pop = d.querySelector(".gl-pop");
  ok(!!pop, "a click opens the card");
  ok(pop && pop.querySelector(".gl-h b").textContent === code, "the card names the code");
  ok(pop && pop.querySelector(".gl-s p, .gl-title") !== null, "the card has a meaning");
  ok(pop && [...pop.querySelectorAll("a:not(.gl-site):not(.gl-src)")].every(a => !a.target), "links stay in this window");
  ok(pop && [...pop.querySelectorAll("a.gl-src")].every(a => a.target === "_blank" && a.rel === "noopener" && /^https:\/\/docs\.nvidia\.com\//.test(a.href)),
     "an outside source opens in a new window");
  if (/^XID \d+$/.test(code)) ok(pop && pop.querySelector("a.gl-src") !== null, "an XID card links to NVIDIA's catalog");
  ok(pop && [...pop.querySelectorAll("a.gl-site")].every(a => a.target === "_blank" && /devices\/#/.test(a.href)), "only Site model opens a new window, on the Devices page");
  ok(pop && pop.querySelector('.gl-f a[href*="glossary/#"]') !== null, "the card links to the glossary entry");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(d.querySelector(".gl-pop") === null, "Esc closes the card");
  target.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  ok(d.querySelector(".gl-pop") !== null, "Enter opens the card");
  d.body.click();
  ok(d.querySelector(".gl-pop") === null, "a click elsewhere closes the card");
  // One card at a time.
  spans[0].click(); spans[1].click();
  ok(d.querySelectorAll(".gl-pop").length === 1, "only one card is open at a time");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  // Redrawn content is wrapped too.
  if (redraw) {
    const before = d.querySelector("span.gl");
    d.querySelector(redraw).click();
    await tick(); await tick();
    ok(!before.isConnected, "the page redrew its content");
    ok(d.querySelectorAll("span.gl").length > 5, "after a redraw, the new content's codes are wrapped");
    if (newCode) ok([...d.querySelectorAll("span.gl")].some(s => s.textContent === newCode), `after a redraw, ${newCode} is wrapped`);
  }
  ok(errors.length === 0, "still no script errors " + errors.join(";"));
})();
