// Device cards: a device name in a code popup shows its description and connections; a connection opens
// that device's card in place, Back returns, and Site model opens the Devices page in a new window.
// Usage: node device_popups.cjs PAGE.html URL DEVICE CONNECTION [REDRAW_BUTTON_SELECTOR]
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const [file, url, device, conn, redraw] = process.argv.slice(2);
const errors = [];
const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "dangerously", url, pretendToBeVisual: true,
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tick = () => new Promise(r => w.setTimeout(r, 0));

(async () => {
  await tick();
  if (redraw) { d.querySelector(redraw).click(); await tick(); await tick(); }
  const target = [...d.querySelectorAll("span.gl")].find(s => s.textContent === device);
  ok(!!target, `${device} is underlined`);
  if (!target) return;
  target.click();
  let pop = d.querySelector(".gl-pop");
  ok(pop && pop.querySelector(".gl-h b").textContent === device, "the card names the device");
  ok(pop && pop.querySelector(".gl-s:not(.gl-dev) .gl-title") !== null, "the card keeps the glossary meaning");
  ok(pop && pop.querySelector(".gl-dev p").textContent.length > 20, "the card describes this device");
  const rows = pop ? [...pop.querySelectorAll(".gl-conn tr")] : [];
  ok(rows.length > 0, `the card lists connections (${rows.length})`);
  const site = pop && pop.querySelector("a.gl-site");
  ok(site && site.target === "_blank" && site.href.includes("devices/#"), "Site model opens the Devices page in a new window");
  const link = pop && [...pop.querySelectorAll(".gl-conn span.gl")].find(s => s.textContent === conn);
  ok(!!link, `${conn} is a link in the connections`);
  if (!link) return;
  link.click();
  pop = d.querySelector(".gl-pop");
  ok(d.querySelectorAll(".gl-pop").length === 1, "one card at a time");
  ok(pop && pop.querySelector(".gl-h b").textContent === conn, "the connection opens its own card in place");
  ok(pop && pop.querySelector(".gl-dev") !== null, "with its own description and connections");
  const back = pop && pop.querySelector(".gl-back");
  ok(back && back.textContent.includes(device), "Back names the card it returns to");
  if (back) back.click();
  pop = d.querySelector(".gl-pop");
  ok(pop && pop.querySelector(".gl-h b").textContent === device, "Back returns to the first card");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(d.querySelector(".gl-pop") === null, "Esc closes the card");
  const dev = JSON.parse(d.getElementById("gl-data").textContent).dev;
  console.log("DEV " + JSON.stringify(Object.keys(dev)));
  ok(errors.length === 0, "no script errors " + errors.join(";"));
})();
