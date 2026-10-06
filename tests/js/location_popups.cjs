// Location pins on a static page: only marked fields get a pin, each pin names what the field names,
// a click opens the drawing with the item outlined and an arrow, sheets switch, Esc closes, and the
// field's own text (and its code popups) is unchanged.
// Usage: node location_popups.cjs SITE_DIR PAGE_PATH EXPECTED_NAME [REDRAW_BUTTON_SELECTOR]
// Prints one line "FIELDS {json}" with every field's value and what its pin opens, for the Python test.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const path = require("path");
const [siteDir, page, expected, redraw] = process.argv.slice(2);
const html = fs.readFileSync(path.join(siteDir, page, "index.html"), "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/" + page, pretendToBeVisual: true,
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))),
  beforeParse(w) {   // the drawings come from the built site, as they would from GitHub Pages
    w.fetch = url => {
      const rel = new w.URL(url, w.location.href).pathname.slice(1);
      const f = path.join(siteDir, rel);
      return Promise.resolve(fs.existsSync(f) ? { ok: true, text: () => Promise.resolve(fs.readFileSync(f, "utf8")) }
                                               : { ok: false, status: 404, text: () => Promise.resolve("") });
    };
  } });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tick = (ms = 0) => new Promise(r => w.setTimeout(r, ms));

(async () => {
  await tick(); await tick();
  ok(errors.length === 0, "no script errors " + errors.join(";"));
  const pins = [...d.querySelectorAll(".loc-pin")];
  ok(pins.length > 0, `fields with a location have pins (${pins.length})`);
  ok(pins.every(p => p.parentElement.hasAttribute("data-loc")), "every pin sits in a marked field, never in prose");
  ok([...d.querySelectorAll("[data-loc]")].every(f => f.querySelectorAll(":scope > .loc-pin").length <= 1), "one pin per field");
  ok(pins.every(p => p.getAttribute("aria-label").startsWith("Show ")), "pins have an accessible name");
  const fields = {};
  for (const f of d.querySelectorAll("[data-loc]")) fields[f.dataset.loc] = w.LOCATIONS.field(f.dataset.loc);
  console.log("FIELDS " + JSON.stringify(fields));
  for (const f of d.querySelectorAll("[data-loc]")) {
    const has = !!f.querySelector(":scope > .loc-pin");
    if (has !== !!fields[f.dataset.loc]) { ok(false, `pin present exactly when the field resolves: ${f.dataset.loc}`); break; }
  }
  const pin = pins.find(p => p.dataset.locName === expected);
  ok(!!pin, `${expected} has a pin`);
  if (!pin) return;
  const field = pin.parentElement, before = field.textContent;
  pin.click();
  let bg = d.querySelector(".loc-bg");
  ok(!!bg, "a click opens the drawing card");
  ok(bg && bg.querySelector('[role="dialog"]') !== null, "the card is a dialog");
  ok(bg && bg.querySelector(".loc-h b").textContent.includes(expected.replace(/^HALL-/, "Hall ")), "the card names the item");
  await tick(); await tick(); await tick();
  let svg = bg.querySelector(".loc-fig svg");
  ok(!!svg, "the drawing loads into the card");
  ok(svg && svg.querySelectorAll(".loc-hl rect[stroke='#d62728']").length >= 1, "the item is outlined in red");
  ok(svg && svg.querySelector(".loc-hl polygon") !== null && svg.querySelector(".loc-hl text").textContent.length > 0, "an arrow with a label points at it");
  const vb1 = svg && svg.getAttribute("viewBox");
  bg.querySelector(".loc-full").click();
  await tick(); await tick(); await tick();
  svg = bg.querySelector(".loc-fig svg");
  ok(svg && svg.getAttribute("viewBox") !== vb1 && svg.getAttribute("viewBox").startsWith("0.0 0.0"), "Full sheet shows the whole drawing");
  const chips = [...bg.querySelectorAll(".loc-chips button")];
  if (chips.length > 1) {
    chips[1].click();
    await tick(); await tick(); await tick();
    ok(chips[1].classList.contains("on") && bg.querySelector(".loc-fig svg .loc-hl") !== null, "another sheet opens with its own highlight");
  }
  ok(/site\/[A-Z]-\d{3}_[\w]+\.svg$/.test(bg.querySelector(".loc-open").getAttribute("href")), "the card links to the drawing");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(d.querySelector(".loc-bg") === null, "Esc closes the card");
  ok(field.textContent === before, "the field's text is unchanged");
  pin.click();
  bg = d.querySelector(".loc-bg");
  bg.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  ok(d.querySelector(".loc-bg") === null, "a click on the backdrop closes the card");
  if (redraw) {
    d.querySelector(redraw).click();
    await tick(); await tick();
    ok(d.querySelectorAll(".loc-pin").length > 0, "after a redraw, the new fields get pins");
  }
  await tick(50);
  ok(errors.length === 0, "still no script errors " + errors.join(";"));
  w.close();
})();
