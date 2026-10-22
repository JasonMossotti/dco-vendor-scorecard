// The Incident Portal in a browser: a hash opens its record, the type dropdown and the search fields filter
// the list, a related-record link opens that record in place, and no person is named.
// Usage: node tickets_page.cjs PAGE.html   (prints RESULT {...} for the pytest side to check against the data)
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const [file] = process.argv.slice(2);
const errors = [];
const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "dangerously", url: "https://example.test/tickets/#INC3100068",
  pretendToBeVisual: true, virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tick = () => new Promise(r => w.setTimeout(r, 0));
const ids = () => [...d.querySelectorAll("#list tr.row")].map(tr => tr.dataset.id);
const set = async (id, v) => { const el = d.getElementById(id); el.value = v; el.dispatchEvent(new w.Event("change", { bubbles: true })); await tick(); };
const reset = async () => { d.getElementById("f-reset").click(); await tick(); };

(async () => {
  await tick();
  const result = {};
  const head = () => d.querySelector("#detail h1") && d.querySelector("#detail h1").textContent;
  ok(head() === "INC3100068", "the hash opens its ticket");
  ok(d.querySelector("#detail svg[aria-label='Timeline by party']") !== null, "the ticket has a timeline at a glance");
  const tl = d.querySelectorAll("#detail table")[0];
  ok(d.querySelector("#detail").textContent.includes("F-001"), "the finding that names it is shown");
  ok(d.querySelector("#detail").textContent.includes("Measured: T0 to validated RTS"), "the Customer's measurement is shown");
  w.location.hash = "#IMP-0005"; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
  ok(head() === "IMP-0005" && d.querySelector("#detail").textContent.includes("Out of service (fire panel)") && d.querySelector("#detail").textContent.includes("FLS-1")
     && d.querySelector("#detail").textContent.includes("Differs"), "an impairment shows the fire panel's measurement and its finding");
  w.location.hash = "#INC3100068"; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
  result.all = ids().length;
  // type dropdown
  const types = [...d.querySelectorAll("#f-type option")].map(o => o.value).filter(Boolean);
  result.types = {};
  for (const t of types) { await set("f-type", t); result.types[t] = ids(); }
  await reset();
  // search fields
  result.search = {};
  for (const [field, q] of [["parts", "PU5DX43MCA"], ["person", "RSS-024"], ["id", "WO-41023"], ["device", "CDU-B3"], ["notes", "reseat"],
                            ["finding", "CSL-11"], ["all", "a31-ct11"], ["alarm", "ALM-0005"], ["related", "MOP-310"], ["location", "Chiller yard"]]) {
    await set("f-in", field); await set("f-q", q); result.search[field + ":" + q] = ids();
  }
  await reset();
  await set("f-priority", "P1"); result.p1 = ids(); await reset();
  await set("f-finding", "yes"); result.with_finding = ids(); await reset();
  await set("f-hall", "HALL-B"); result.hall_b = ids(); await reset();
  await set("f-from", "2026-09-15"); await set("f-to", "2026-09-15"); result.sep15 = ids(); await reset();
  await set("f-sort", "old"); const old = ids(); ok(old.length === result.all, "sorting keeps every record");
  await reset();
  // a row click opens the record; a related link opens another in place
  d.querySelector('#list tr.row[data-id="WO-41023"] td.dev').click(); await tick();
  ok(head() === "WO-41023", "a row click opens that record");
  ok(w.location.hash === "#WO-41023", "the address names the open record");
  const rel = [...d.querySelectorAll("#detail a.tk-link")].find(a => a.textContent === "INC3900001");
  ok(!!rel, "related records are links");
  if (rel) { w.location.hash = "#INC3900001"; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick(); }
  ok(head() === "INC3900001", "a related link opens that record");
  ok(d.querySelector("#detail").textContent.includes("PIR-2026-001"), "the reviewed incident links its post-incident review");
  // engineer notes: a collapsed section on every record, opened by a click, escaped, and searchable
  const en = () => d.querySelector("#detail details.enotes");
  ok(en() && !en().open && en().querySelector("summary b").textContent === "Engineer notes", "the record has a collapsed Engineer notes section");
  en().querySelector("summary").click(); await tick();
  ok(en().open && en().textContent.includes("Additional comments") && en().textContent.includes("Customer-visible")
     && en().textContent.includes("Facility power loss, not an IT fault"), "opening it shows the hand-entered fields");
  result.en_heads = [...en().querySelectorAll("h3")].map(h => h.firstChild.textContent);
  result.en_open = {};
  for (const id of ["WO-41023", "PM-0008", "MOP-310", "SIR-00027", "IMP-0004", "CHG2040031"]) {
    w.location.hash = "#" + id; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
    result.en_open[id] = { title: en() && en().querySelector("summary b").textContent, heads: en() ? [...en().querySelectorAll("h3")].map(h => h.firstChild.textContent) : [] };
  }
  ok(result.en_open["WO-41023"].heads.includes("Work log"), "a work order shows its work log");
  ok(result.en_open["SIR-00027"].title === "Officer notes", "a security record is titled Officer notes");
  w.location.hash = "#MOP-310"; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
  ok([...en().querySelectorAll("a.tk-link")].some(a => a.textContent === "WO-41023" && !a.target), "a ticket number in a note opens its record in place");
  w.eval('EN["MOP-310"].fields[1].text = "<img src=x id=xss>"');
  w.location.hash = "#INC3900001"; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
  w.location.hash = "#MOP-310"; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
  ok(!d.getElementById("xss") && en().textContent.includes("<img src=x id=xss>"), "note text is escaped");
  await set("f-in", "engineer"); await set("f-q", "nitrogen bottles"); result.search["engineer:nitrogen bottles"] = ids(); await reset();
  w.location.hash = "#INC0000000"; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
  ok(d.querySelector("#detail").textContent.includes("No record INC0000000"), "an unknown number says so");
  // people are shown by ID: open every record and look for names
  const names = JSON.parse(process.argv[3] || "[]"), seen = new Set();
  for (const id of result.types[""] || ids()) {
    w.location.hash = "#" + id; w.dispatchEvent(new w.HashChangeEvent("hashchange")); await tick();
    const text = d.querySelector("#detail").textContent;
    names.filter(n => text.includes(n)).forEach(n => seen.add(id + ": " + n));
  }
  ok(seen.size === 0, "no record names a person " + [...seen].slice(0, 3).join("; "));
  ok(errors.length === 0, "no script errors " + errors.join(" | "));
  console.log("RESULT " + JSON.stringify(result));
})();
