// The Deployments page: the tree of gates, steps, waves, and racks; a step's procedure and sign-off chain;
// a rack's reported and measured milestones; the calculation sheet; permits, inspections, and the sign-off matrix.
// Usage: node deployments_page.cjs PAGE.html
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const [file] = process.argv.slice(2);
const errors = [];
const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "dangerously", url: "https://example.test/deployments/",
  pretendToBeVisual: true, beforeParse(w) { w.fetch = () => Promise.reject(new Error("offline")); w.scrollTo = () => {}; },
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tick = () => new Promise(r => w.setTimeout(r, 0));
const go = async h => { w.location.hash = h; await tick(); await tick(); };
const h1 = () => d.querySelector("#main h1").textContent;

(async () => {
  await tick(); await tick();
  const main = d.getElementById("main"), tree = d.getElementById("tree");
  ok(h1() === "Hall B GB300 NVL72 rollout", "opens on the program");
  ok(d.querySelector('nav.usm a.on').textContent === "Deployments", "the Deployments tab is marked");
  ok(main.textContent.includes("13 of 32") && main.textContent.includes("racks at Validated Handoff"), "13 of 32 racks handed off (measured)");
  ok(tree.querySelectorAll("details").length === 4 + 4, "the tree has 4 gates and 4 waves");
  ok(tree.querySelectorAll('a[href^="#rack/"]').length === 32, "and all 32 racks");
  await go("#step/G1-07");
  ok(h1() === "G1-07 Integrated systems test (L5)", "a step by its link");
  ok(main.querySelectorAll("ol.proc li").length === 3, "with its procedure");
  ok(main.querySelector(".chain").textContent.startsWith("Commissioning agent"), "and its sign-off chain in order");
  ok(tree.querySelector("a.on").getAttribute("href") === "#step/G1-07" && tree.querySelector("a.on").closest("details").open, "the tree marks and opens it");
  await go("#rack/B02");
  ok(h1().startsWith("Rack B02") && main.querySelector(".tag.bad").textContent === "handed off late", "rack B02 was handed off late");
  const rows = [...main.querySelectorAll("tbody tr")].map(r => r.textContent);
  ok(rows.length === 8, "a rack shows the 8 rack steps");
  ok(rows[7].includes("2026-09-14 04:57 UTC (scheduler)"), "M7 measured from the scheduler");
  ok(rows[6].includes("24-hour burn-in passed"), "M6 measured from the health checks");
  ok(main.querySelector('a[href="../devices/#B02"]') !== null, "the rack links to its device card");
  await go("#wave/2");
  ok(h1() === "Wave 2" && main.querySelectorAll("tbody tr").length === 8, "a wave lists its 8 racks");
  await go("#calc");
  const txt = main.textContent;
  ok(txt.includes("Hall at reported peak") && txt.includes("Rack power limit set at or below 132 kW"), "peak checks name the power-limit control");
  ok(txt.includes("4,561.9 LPM"), "flow is formatted");
  await go("#permits");
  ok(main.textContent.includes("Unincorporated Williamson County") && main.textContent.includes("AHJ-FM-COC"), "permits for the county profile");
  await go("#inspections");
  ok(main.textContent.includes("Williamson County Fire Marshal") && !main.textContent.includes("City building inspections"), "only the profile's authority inspects");
  await go("#signoff");
  ok(main.querySelectorAll("tbody tr").length > 27, "the sign-off matrix lists every step");
  await go("#nothing/here");
  ok(h1() === "Hall B GB300 NVL72 rollout", "an unknown link falls back to the program");
  ok(errors.length === 0, "no script errors" + (errors.length ? ": " + errors.join("; ") : ""));
})();
