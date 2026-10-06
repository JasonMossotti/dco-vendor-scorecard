// The Glossary tab: A to Z and by-type views, type chips, search, and deep links to one entry.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const load = url => {
  const errors = [];
  const dom = new JSDOM(html, { runScripts: "dangerously", url, pretendToBeVisual: true,
    virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
  return { dom, d: dom.window.document, errors };
};
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };

const { dom, d, errors } = load("https://example.test/glossary/");
ok(errors.length === 0, "no script errors " + errors.join(";"));
const total = d.querySelectorAll(".entry").length;
ok(total > 300, `every entry is listed (${total})`);
ok(d.getElementById("count").textContent === `${total} of ${total} entries`, "the count shows all");
const groups = [...d.querySelectorAll("h2.group")].map(h => h.textContent);
ok(groups[0] === "A" && groups.includes("C") && groups.includes("T"), "A to Z groups by first letter");
const letters = [...d.querySelectorAll("#az a")].map(a => a.textContent);
ok(letters.includes("C") && !letters.includes("J"), "the letter bar links only letters that have entries");
ok(d.getElementById("CSL-07") && d.getElementById("CSL-07").textContent.includes("Validated Return to Service"), "CSL-07 has its contract title");
ok(d.querySelector('#CSL-07 a[href="../agreements/it-partner-sla/#CSL-07"]') !== null, "CSL-07 links to its clause");
ok(d.querySelector('#INC .meta') && d.getElementById("INC").textContent.includes("INC3100816"), "a record family shows its format and an example");

d.getElementById("v-type").click();
const tgroups = [...d.querySelectorAll("h2.group")].map(h => h.textContent);
ok(tgroups[0] === "Acronyms" && tgroups.includes("Service levels") && tgroups.includes("Records and documents"), "by type groups by type");
const chip = d.querySelector('#chips button[data-type="service_level"]');
chip.click();
const sl = [...d.querySelectorAll(".entry")].filter(e => e.isConnected);
ok(sl.length > 10 && sl.every(e => e.dataset.type === "service_level"), "a type chip shows only that type");
ok(d.getElementById("count").textContent.startsWith(`${sl.length} of`), "the count follows the filter");
d.querySelector('#chips button[data-type=""]').click();

const q = d.getElementById("q");
q.value = "coolant distribution"; q.dispatchEvent(new dom.window.Event("input"));
const hits = [...d.querySelectorAll("#list .entry")];
ok(hits.some(e => e.id === "CDU") && hits.some(e => e.id === "EQ-CDU") && hits.length < 20, "search finds meanings, not just codes");
q.value = "zzzz-nothing"; q.dispatchEvent(new dom.window.Event("input"));
ok(d.querySelector(".empty") !== null, "a search with no match says so");
ok(errors.length === 0, "still no script errors " + errors.join(";"));

// A popup's "Glossary entry" link lands on the entry whatever the filters were.
const deep = load("https://example.test/glossary/#TR-1");
ok(deep.errors.length === 0, "no script errors on a deep link");
ok(deep.d.getElementById("TR-1").classList.contains("flash"), "#TR-1 highlights the entry");
ok(deep.d.getElementById("TR-1").querySelectorAll(".sense").length === 2, "TR-1 shows each partner SLA's wording");
ok(deep.d.querySelector("nav.usm a.on").dataset.tab === "glossary", "site tab bar marks Glossary");
