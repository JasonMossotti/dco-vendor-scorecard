const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/app/", virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const t = () => d.getElementById("doc").textContent;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const D = JSON.parse(d.getElementById("data").textContent);
const S = D.datasets[0];
const nav = h => { w.location.hash = h; w.dispatchEvent(new w.HashChangeEvent("hashchange")); };
const change = (el, v) => { if (typeof v === "boolean") el.checked = v; else el.value = v; el.dispatchEvent(new w.Event("change", { bubbles: true })); };
const shown = sel => [...d.querySelectorAll(sel)].filter(x => !x.hidden);

ok(errors.length === 0, "no script errors " + errors.join(";"));
ok(!html.includes("stlite.js") && d.querySelector('a[href="lab/"]'), "no Python runtime on this page; Try another month links to the lab");
ok(d.querySelectorAll("#views button").length === 6 && d.querySelector("#views button.on").dataset.view === "site", "six views, opening on the site summary");
ok(t().includes("Quality audit: the Customer walked down 20 closed records") && d.querySelector('#doc a[href="#audit"]'), "the site summary points to the quality audit");
ok(t().includes("three partners, one set of records") && d.querySelectorAll(".card").length === 3, "the site summary with a card per partner");
ok(t().includes("$307,176"), "the three partners' credits added up ($188,700 + $106,200 + $12,276)");
ok(t().includes("Rack A07 went dark for 3.4 hours") && d.querySelector("#doc b"), "the crossing outage, in bold where the app had it");

d.querySelector('#views button[data-view="it"]').click();
nav("#it");
ok(d.querySelector("#views button.on").dataset.view === "it" && t().includes("IT Partner scorecard"), "IT Partner view");
ok(t().includes("$188,700") && t().includes("17 of 17") && t().includes("0 false positives"), "IT headline numbers equal the reports");
ok(d.querySelectorAll(".subtabs a").length === 6 && d.querySelector(".subtabs a.on").dataset.sub === "overview", "six sections, Overview first");
ok(d.querySelectorAll(".gapbar").length === S.it.reported.filter(r => r["Gap (pts)"] != null).length, "a gap bar per reported service level");

nav("#it/levels");
ok(d.querySelectorAll("#csl tbody tr").length === S.it.csl.length && d.querySelectorAll("#csl tr.default").length === 4, "every CSL, the four defaults marked");
ok(d.querySelectorAll("#csl .flag.bad").length >= 4 && t().includes("Minimum default"), "default flags");
ok(d.querySelectorAll("svg polyline").length === 4 && d.querySelectorAll("svg circle").length === S.it.gaps.length * 4, "weekly gap chart: four series, a point per week");
const th = d.querySelector("#csl th:nth-child(1)");
th.click(); th.click();
ok(d.querySelector("#csl tbody tr").cells[0].textContent === "CSL-12" && th.getAttribute("aria-sort") === "descending", "click a heading to sort, again to reverse");

nav("#it/findings");
ok(shown("#flist details").length === S.it.findings.length && d.getElementById("fcount").textContent === `${S.it.findings.length} of ${S.it.findings.length} findings`, "every finding listed");
change(d.getElementById("fsev"), "S1");
ok(shown("#flist details").length === S.it.findings.filter(f => f.severity === "S1").length, "filter by severity");
change(d.getElementById("fsev"), "");
const q = d.getElementById("fq");
q.value = "INC3100068"; q.dispatchEvent(new w.Event("input"));
ok(shown("#flist details").length >= 1 && shown("#flist details").every(x => x.textContent.includes("INC3100068")), "search by ticket");
q.value = ""; q.dispatchEvent(new w.Event("input"));
ok(t().includes("not by itself proof of intent"), "a finding is framed as records that do not reconcile");
nav("#it/findings/F-008");
ok(d.getElementById("f-F-008").open, "a finding's deep link opens it");

nav("#it/incidents");
const all = S.it.incidents.length, late = S.it.incidents.filter(r => !r["Within target"]).length;
ok(shown("#inc tbody tr").length === all, "every Ticket of Record");
change(d.getElementById("ilate"), true);
ok(shown("#inc tbody tr").length === late && late > 0 && d.getElementById("icount").textContent === `${late} of ${all} incidents`, "only incidents past their restore target");
change(d.getElementById("ilate"), false);
change(d.getElementById("ipri"), "P1");
ok(shown("#inc tbody tr").length === S.it.incidents.filter(r => r.Priority === "P1").length, "filter by priority");
ok(d.querySelector('#inc [data-loc="A06"]'), "racks carry a location pin");

nav("#it/actions");
ok(t().includes("CAP-001") && t().includes("Severity log"), "corrective action plans and the severity log");

nav("#landlord/levels");
ok(t().includes("Landlord scorecard") && t().includes("$106,200") && d.querySelectorAll("#csl tr.default").length === 4, "Landlord: $106,200, four defaults");
nav("#landlord/events");
const ev = S.landlord.events;
change(d.getElementById("edis"), true);
ok(shown("#events tbody tr").length === ev.filter(r => r.Agrees === "No").length, "facility events where the work order disagrees");
nav("#landlord");
ok(t().includes("8 of 8"), "Landlord self-check 8 of 8");

nav("#security/levels");
ok(t().includes("Security Partner scorecard") && t().includes("$12,276") && d.querySelectorAll("#csl tr.default").length === 2, "Security Partner: $12,276, two defaults");

nav("#credits");
ok(t().includes("In one sentence") && t().includes("price adjustment") && t().includes("not a fine"), "credits explained in plain words");
ok(t().includes("$1,850,000") && t().includes("$222,000") && t().includes("250%"), "the IT contract's numbers come from the SLA");
ok(t().includes("Below Expected, above Minimum") && t().includes("root cause"), "the three bands");
ok(t().includes("doubles") && t().includes("earned back") && t().includes("Safety (EHS) credits are separate"), "doubling, earnback, and EHS");
ok(d.querySelectorAll(".potbar").length === 3 && t().includes("$118,000") && t().includes("$22,320"), "this month per partner, with each at-risk amount");
ok(d.getElementById("cpay").textContent === "$188,700", "the calculator opens on this month's IT defaults");
const box = cid => d.querySelector(`#ct tr[data-csl="${cid}"]`);
const set = (cid, cls, v) => { const el = box(cid).querySelector(cls); if (typeof v === "boolean") el.checked = v; else el.value = v; el.dispatchEvent(new w.Event("change", { bubbles: true })); };
set("CSL-07", ".cm", "3");
ok(d.getElementById("cpay").textContent === "$222,000" && t().includes("capped from $244,200"), "a third month in a row doubles CSL-07 and the cap holds the total");
ok(box("CSL-11").querySelector(".ca").checked && d.getElementById("cres").textContent.includes("final"), "CSL-11 involved a record integrity finding, so it is final");
d.getElementById("cnone").click();
ok(d.getElementById("cpay").textContent === "$0", "clear: nothing comes off");
change(d.getElementById("cp"), "landlord");
ok(d.getElementById("cpay").textContent === "$106,200" && d.querySelectorAll("#ct tbody tr").length === D.terms.landlord.csl.length, "switch partner: the Landlord's service levels and this month's credit");
nav("#credits/security");
ok(d.getElementById("cp").value === "security" && d.getElementById("cpay").textContent === "$12,276", "deep link to one partner's credits");

nav("#audit");
const A = S.audit;
ok(d.querySelector("#views button.on").dataset.view === "audit" && t().includes("Quality audit") && d.querySelectorAll(".subtabs a").length === 4, "Quality audit view, four sections");
ok(t().includes("7 of 10") && t().includes("9 of 10") && t().includes("target 95%") && d.querySelectorAll(".tile.bad").length === 3, "workmanship by partner against the contract's target, both missed, and the findings tile");
ok(d.querySelectorAll('#doc a[href^="#audit/findings/QA-"]').length === 4 && t().includes("CSL-06") && t().includes("KM-18"), "the four findings and the engine's quality measures");
ok(t().includes("does not count them again") && t().includes("monthly service review"), "engine findings are not counted twice; actions go to the monthly review");

nav("#audit/sample");
ok(shown("#qlist details").length === 20 && d.getElementById("qcount").textContent === "20 of 20 records", "every sampled record");
change(d.getElementById("qr"), "failed");
ok(shown("#qlist details").length === 4 && shown("#qlist details").every(x => x.dataset.res === "failed"), "filter to the records that failed workmanship");
change(d.getElementById("qr"), "");
change(d.getElementById("qp"), "landlord");
ok(shown("#qlist details").length === 10 && shown("#qlist details").every(x => x.dataset.partner === "landlord"), "filter by partner");
change(d.getElementById("qp"), "");
const qq = d.getElementById("qq");
qq.value = "PUYJNR5UBT"; qq.dispatchEvent(new w.Event("input"));
ok(shown("#qlist details").length === 1, "search by serial");
qq.value = ""; qq.dispatchEvent(new w.Event("input"));

const fail = A.findings.find(f => f.kind === "custody");
nav("#audit/sample/" + fail.record);
const rec = d.getElementById("qa-" + fail.record);
ok(rec.open && rec.querySelectorAll(".qa-items tbody tr").length === A.records.find(x => x.id === fail.record).items.length, "a record's deep link opens its checklist");
ok(rec.querySelector("tr.default .flag.bad") && rec.textContent.includes("RMA cage shelf") && rec.querySelectorAll(".qa-ev li").length >= 3, "the failed item, and the trail through the Customer's systems");
const withEng = A.records.find(x => x.engine.length);
nav("#audit/sample/" + withEng.id);
ok(d.querySelector(`#qa-${withEng.id} a[href="#${withEng.partner}/findings/${withEng.engine[0].id}"]`), "an engine finding on a sampled record links to that scorecard's finding");

nav("#audit/findings/QA-4");
ok(d.getElementById("qf-QA-4").open && t().includes("Corrective action") && t().includes("not by itself proof of intent"), "a finding's deep link, its action, and the framing");

nav("#audit/how");
ok(t().includes(`--sample ${A.seed}`) && t().includes("publishes") && d.querySelectorAll("table").length === 3, "how the sample is drawn, both checklists, and the agreements");

nav("#it/levels");
ok(d.querySelector('a[href="#credits/it"]'), "each scorecard links to how its credits are worked out");
ok(errors.length === 0, "still no script errors " + errors.join(";"));
