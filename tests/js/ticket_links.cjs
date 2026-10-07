// Every ticket, change, and work order number on a page links to the Incident Portal, which opens that record.
// Usage: node ticket_links.cjs PAGE.html URL [REDRAW_BUTTON_SELECTOR]   (prints LINKS [...] with each link's number)
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const [file, url, redraw] = process.argv.slice(2);
const errors = [];
const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "dangerously", url, pretendToBeVisual: true,
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tick = () => new Promise(r => w.setTimeout(r, 0));

(async () => {
  await tick();
  if (redraw) { d.querySelector(redraw).click(); await tick(); await tick(); }
  const G = JSON.parse(d.getElementById("gl-data").textContent);
  const known = new Set(G.tk), re = new RegExp("\\b(?:" + G.tk_re + ")\\b", "g");
  const links = [...d.querySelectorAll("a.tk-link")];
  ok(links.length > 0, `numbers are links (${links.length})`);
  const root = new w.URL(G.root, url).href;
  ok(links.every(a => a.href === root + "tickets/#" + a.textContent && known.has(a.textContent)), "each link opens its own record on the portal");
  // Any number left as plain text sits where a link cannot go (a button, a form field, a drawing, a heading's summary).
  const SKIP = "script,style,textarea,input,select,option,button,a,svg,summary,label,nav.usm,.gl-pop,[data-gl-skip],[data-tk-skip],[contenteditable]";
  const plain = [];
  const walker = d.createTreeWalker(d.body, w.NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (n.parentElement.closest(SKIP)) continue;
    for (const m of n.nodeValue.matchAll(re)) if (known.has(m[0])) plain.push(m[0]);
  }
  ok(plain.length === 0, "no portal number is left unlinked " + plain.slice(0, 5).join(", "));
  // The glossary popups still work beside the links.
  ok(d.querySelectorAll("span.gl").length > 0, "codes keep their popups");
  ok(errors.length === 0, "no script errors " + errors.join(" | "));
  console.log("LINKS " + JSON.stringify([...new Set(links.map(a => a.textContent))].sort()));
})();
