const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/training/", virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const t = () => d.getElementById("doc").textContent;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const R = JSON.parse(d.getElementById("data").textContent).certs;
const go = h => { w.location.hash = h; w.dispatchEvent(new w.HashChangeEvent("hashchange")); };

ok(errors.length === 0, "no script errors " + errors.join(";"));
// Certifications (the opening view)
ok(t().includes("Certifications") && d.querySelector(".views a.on").dataset.view === "certs", "opens on Certifications");
ok(R.findings.length === 6 && R.findings.every(f => t().includes(f.id)), "every finding listed");
ok(t().includes(R.km15.actual.toFixed(1) + "%") && t().includes("target 100%"), "KM-15 tile");
ok(R.staffing.length === 3 && R.staffing.every(s => t().includes(s.csl)) && t().includes("the published scorecards and credits do not change"), "staffing with the qualification rule, beside the published value");
ok(R.reported.length === 3 && [...d.querySelectorAll(".flag.bad")].some(x => x.textContent === "No"), "the IT Partner's report does not agree");
// a finding
const lapsed = R.findings.find(f => f.kind === "lapsed" && f.records.length);
go("finding/" + lapsed.id);
const fp = d.getElementById("findpanel");
ok(fp && fp.textContent.includes(lapsed.credential_name) && fp.textContent.includes(lapsed.person) && fp.textContent.includes("Action."), "a finding opens with its person, credential, and action");
ok(fp.querySelectorAll(".tl .bar.out").length === 1 && fp.querySelectorAll(".tl .tick.bad").length >= 1, "the timeline shows the lapse and the work done after it");
const ehs = R.findings.find(f => f.corroborates);
go("finding/" + ehs.id);
ok(d.getElementById("findpanel").querySelector(`a[href="../ops/#ehs/finding/${ehs.corroborates}"]`), "the EHS lapse links its SAF finding");
// register
go("register");
ok(d.querySelector(".views a.on").dataset.view === "register" && d.querySelectorAll("#reg tr[data-person]").length === R.people.length, "the register lists every person");
const sel = d.querySelector('select[data-f="partner"]');
sel.value = "security"; sel.dispatchEvent(new w.Event("change"));
ok(d.querySelectorAll("#reg tr[data-person]").length === R.people.filter(p => p.partner === "security").length, "filter by partner");
const st = d.querySelector('select[data-f="status"]');
st.value = "lapsed"; st.dispatchEvent(new w.Event("change"));
const rows = [...d.querySelectorAll("#reg tr[data-person]")].map(x => x.dataset.person);
ok(rows.length >= 1 && rows.every(p => R.findings.some(f => f.person === p)), "the lapsed filter shows only people with a finding");
const g = R.findings.find(f => f.partner === "security" && f.person);
go("person/" + g.person);
const pp = d.getElementById("personpanel");
ok(pp && pp.textContent.includes("Firearm proficiency, category STG (shotgun)") && pp.textContent.includes("Texas DPS commissioned security officer license (Level III)") && pp.textContent.includes("Lapsed"), "a guard's record shows the Level III commission, SA and STG, and the lapse");
const tech = R.findings.find(f => f.partner === "it" && f.records.length);
go("person/" + tech.person);
ok(d.getElementById("personpanel").textContent.includes(tech.records[0]) && d.querySelector("#personpanel .flag.bad"), "a technician's work shows what was missing");
// renewals
go("renewals");
ok(d.querySelectorAll(".letter[data-notice]").length === 3 && d.querySelector('.letter[data-notice="it"]').textContent.match(/\btraining@itpartner\.example\.com\b/), "a drafted notice per partner");
ok(d.querySelector('.letter[data-notice="security"]').textContent.includes("not sent"), "notices are drafted, never sent");
const n = R.notices.find(x => x.stage);
ok(n && [...d.querySelectorAll(".flag.warn")].some(x => x.textContent.startsWith("Due now")), "the notice due now is marked");
ok(d.querySelectorAll("#bench tr").length === R.bench.length + 1, "the forward schedule's jobs with qualified people");
// requirements
go("requirements");
ok(t().includes("By role") && t().includes("EPA Section 608") && t().includes("Does not expire") && t().includes("Hall B work"), "requirements by role and by work");
ok(errors.length === 0, "no script errors " + errors.join(";"));
