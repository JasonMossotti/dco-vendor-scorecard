// The Emergency tab: the decision tree, the procedures, the call lists, and the Command view (moved from the PIR page).
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
function open(hash) {
  const errs = [];
  const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/emergency/" + hash, virtualConsole: new VirtualConsole().on("jsdomError", e => errs.push(String(e))) });
  const d = dom.window.document;
  return { dom, d, errs, t: () => d.getElementById("doc").textContent };
}
const DATA = JSON.parse(html.split('id="data" type="application/json">')[1].split("</script>")[0]);

// Procedures: the tree, the cards, and the sample's P1 events.
const p = open("");
ok(p.errs.length === 0, "no script errors " + p.errs.join(";"));
ok(p.d.getElementById("t-procedures").classList.contains("on"), "opens on Procedures");
ok(p.t().includes("Always first") && p.t().includes("call 911 first"), "life safety comes first");
ok(p.d.querySelectorAll(".plain .card").length === DATA.types.length && DATA.types.length === 9, "one card per event type (9)");
ok(p.d.querySelectorAll("table tr").length === DATA.events.length + 1 && DATA.events.length === 8, "the 8 P1 events in the sample are listed");
ok(p.t().includes("WO-41023 and INC3900001"), "the A07 records are one event");
// Walk the tree: not hurt, no fire, power, site-wide -> utility outage.
const click = label => [...p.d.querySelectorAll("#stepper [data-node]")].find(b => b.textContent.startsWith(label)).click();
ok(p.d.querySelector("#stepper .q").textContent === "Is anyone hurt or in danger?", "the tree starts with life safety");
click("No"); click("No"); click("Power"); click("Yes, site-wide");
ok(p.d.querySelector("#stepper .leaf") !== null && p.d.querySelector("#stepper .leaf .q").textContent === "Utility outage or generator run", "the tree reaches the utility procedure");
ok(p.d.querySelector('#stepper a[href="#proc/power_utility"]') !== null, "the leaf opens its procedure");
ok(p.d.querySelector("#stepper .trail").textContent.includes("Has the utility feed been lost"), "the answers so far are shown");
p.d.getElementById("restart").click();
ok(p.d.querySelector("#stepper .q").textContent === "Is anyone hurt or in danger?", "start over returns to the first question");
click("No"); p.d.getElementById("back").click();
ok(p.d.querySelector("#stepper .q").textContent === "Is anyone hurt or in danger?", "back undoes one answer");
ok(p.d.querySelectorAll(".outline a.to").length === 10, "the whole tree shows every path (10)");
ok(p.errs.length === 0, "still no script errors " + p.errs.join(";"));

// One procedure.
const r = open("#proc/power_rack");
ok(r.errs.length === 0, "no script errors on a procedure " + r.errs.join(";"));
ok(r.d.querySelector("h1").textContent === "Rack, busway, or UPS power loss", "#proc/power_rack opens the procedure");
ok(r.t().includes("+1 512 555 0150") && r.t().includes("4471 0915 #"), "the bridge is on the card");
ok(r.t().includes("Questions for the bridge") && r.t().includes("What does one more failure take down?"), "bridge questions shown");
ok(r.d.querySelectorAll("ul.gate li").length === 4 && r.t().includes("A07 factor F6"), "the return-to-service gate carries the A07 lesson");
ok(r.t().includes("decide on the bridge to extend it or close the work") && r.t().includes("A07 factor F5"), "the change window decision carries the A07 lesson");
ok([...r.d.querySelectorAll("table tr")].some(tr => tr.textContent.startsWith("Site leadership") && tr.textContent.includes("within 15 min")), "site leadership within the runbook's 15 minutes");
ok(r.t().includes("WO-41023 and INC3900001"), "the sample event is named");
ok(r.d.querySelector(".printonly") !== null, "the print card has its footer");
for (const t of DATA.types) {
  const x = open("#proc/" + t.id);
  ok(x.errs.length === 0 && x.d.querySelector("h1").textContent === t.name && x.d.querySelectorAll("ol.acts li").length === t.actions.length + t.questions.length, `procedure ${t.id} renders every action and question`);
}

// Call lists.
const c = open("#contacts");
ok(c.errs.length === 0, "no script errors on Call lists " + c.errs.join(";"));
ok(c.d.getElementById("t-contacts").classList.contains("on"), "#contacts opens Call lists");
ok(c.d.querySelectorAll("#contacts tr").length === DATA.contacts.length + 1, "every contact listed");
ok(c.d.querySelectorAll("#contacts .stale").length === 1 && c.t().includes("Overdue: 130 days"), "the one overdue contact is flagged");
ok(c.t().includes("Ops engineer 3") && c.t().includes("+1 512 555 0103"), "the on-call rota is read from the routing file");
ok(c.d.querySelectorAll("#tiers tr").length === DATA.tiers.length + 1, "the tier matrix has a row per tier");
ok(c.t().includes("29 CFR 1904.39"), "the injury reporting rule cites its source");
ok(![...c.d.querySelectorAll("#contacts td.num")].some(td => /\+1 \d{3} \d{3} (?!01)\d{4}/.test(td.textContent)), "every phone number is in the fictional 555-01xx range");

// Command (moved from the PIR page).
const m = open("#replay");
ok(m.errs.length === 0, "no script errors on #replay " + m.errs.join(";"));
ok(m.d.getElementById("t-command").classList.contains("on"), "#replay opens the Command tab");
ok(m.t().includes("Incident Commander runbook") && m.t().includes("Paging tree") && m.t().includes("Status-update templates"), "runbook sections shown");
ok(m.t().includes("The Customer is Incident Commander for any P1"), "who commands is read from the Interface Agreement");
ok([...m.d.querySelectorAll("table tr")].some(tr => tr.textContent.startsWith("P1") && tr.textContent.includes("every 30 min")), "severity matrix gives the P1 update cadence");
ok(m.d.getElementById("replay") !== null && m.t().includes("Replay: Rack A07 lost both power feeds"), "replay section shown");
const stats = [...m.d.querySelectorAll(".stat .v")].map(x => x.textContent);
ok(stats.join(",") === "14,9,5", "replay scores 14 steps, 9 met, 5 missed: " + stats);
ok(m.d.querySelectorAll("tr.why").length === 5, "every missed step says why");
ok(m.t().includes("2 h 37 min") && m.t().includes("TO-A07-A still open at confirmation") && m.t().includes("no decision in the comms log"), "missed checks name their evidence");
ok(m.t().includes("Bridge comms log") && m.t().includes("Joint bridge open for rack A07."), "comms log shown");
ok(m.d.querySelector('a[href="../pir/#PIR-2026-001"]') !== null, "replay links to its review on the PIR page");
m.d.getElementById("t-procedures").click();
ok(m.d.getElementById("stepper") !== null && m.dom.window.location.hash === "#procedures", "the Procedures tab returns to the tree");
ok(m.errs.length === 0, "still no script errors " + m.errs.join(";"));
