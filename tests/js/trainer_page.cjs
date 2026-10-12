// Ownership trainer (agreements/ownership-trainer/): the quiz runs, scores, and reveals the clause and the records.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/agreements/ownership-trainer/", virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const D = JSON.parse(d.getElementById("tr-data").textContent);
const scn = () => D.scenarios.find(s => s.scenario === d.querySelector(".tr-what").textContent);
const opt = (q, v) => [...d.querySelectorAll(`.tr-opt[data-q="${q}"]`)].find(b => b.dataset.v === v);
const notice = s => s.notifier ? `${s.notifier}|${s.minutes}` : "none";
function answer(s, right) {
  (right ? s.R : [s.R.includes("Landlord") ? "IT Partner" : "Landlord"]).forEach(p => opt("R", p).click());
  opt("A", right ? s.A : (s.A === "Customer" ? "Landlord" : "Customer")).click();
  opt("N", right ? notice(s) : (notice(s) === "none" ? "Landlord|5" : "none")).click();
  d.getElementById("tr-check").click();
}

ok(errors.length === 0, "no script errors " + errors.join(";"));
ok(D.scenarios.length === 22, "one scenario per row of the ownership matrix");
ok(d.querySelector(".doctabs a.on").textContent === "Ownership trainer", "its tab is marked");
ok(d.getElementById("tr-progress").textContent.startsWith("Question 1 of 10"), "opens on a quick round of 10");
ok(d.getElementById("tr-check").disabled, "cannot check before answering all three");
let s = scn();
answer(s, true);
ok(d.querySelector(".tr-verdict.ok"), "a right answer is marked right");
ok(d.getElementById("tr-progress").textContent.includes("1 right"), "and scored");
ok(d.querySelector(".tr-clause").textContent.includes(s.component) && d.querySelector('.tr-clause a[href="../interface-agreement/#4-break-fix-ownership-matrix"]'), "the clause is shown with a link to the matrix");
ok(d.querySelectorAll(".tr-raci td").length === 5, "the full RACI row");
d.getElementById("tr-next").click();
s = scn();
answer(s, false);
ok(d.querySelector(".tr-verdict.no") && d.querySelectorAll(".tr-opt.wrong").length >= 1 && d.querySelectorAll(".tr-opt.right").length >= 3, "a wrong answer shows the right ones");
ok(d.getElementById("tr-progress").textContent.includes("1 right"), "and is not scored");
for (let i = 2; i < 10; i++) { d.getElementById("tr-next").click(); answer(scn(), true); }
d.getElementById("tr-next").click();
ok(d.querySelector(".tr-end h2").textContent === "9 of 10 right" && d.querySelectorAll(".tr-end li").length === 10, "the score at the end");
const seen = new Set();
// Every row, in order: the leak at the manifold and the utility outage.
[...d.querySelectorAll("#tr-modes button")].find(b => b.dataset.mode === "all").click();
ok(d.getElementById("tr-progress").textContent.startsWith("Question 1 of 22"), "every row mode has 22 questions");
for (let i = 0; i < 22; i++) {
  s = scn(); seen.add(s.n);
  if (s.component.startsWith("Rack manifold")) {
    answer(s, true);
    const t = d.getElementById("tr-reveal").textContent;
    ok(s.A === "Customer" && s.R.join() === "IT Partner" && s.notifier === "IT Partner" && s.minutes === 5, "manifold leak: IT Partner does it, the Customer owns it, NT-1 in 5 minutes");
    ok(t.includes("DM-COOL") && t.includes("HO-3") && d.querySelector('.tr-recs a[href="../../tickets/#INC3100714"]'), "with the boundary, the handoff, and the A06 leak ticket");
  } else if (s.component.startsWith("138 kV")) {
    answer(s, true);
    ok(s.A === "Utility" && s.notifier === "Landlord" && d.getElementById("tr-reveal").textContent.includes("FA-6"), "utility outage: the Landlord alerts the Customer (FA-6)");
  } else if (s.component.startsWith("Customer Telemetry")) {
    answer(s, true);
    ok(d.getElementById("tr-reveal").textContent.includes("the Customer owns this system"), "the Customer's own system owes no notification");
  } else answer(s, true);
  d.getElementById("tr-next").click();
}
ok(seen.size === 22 && d.querySelector(".tr-end h2").textContent === "22 of 22 right", "every row once");
ok(!/localStorage|sessionStorage|fetch\(/.test(html), "nothing is stored or sent");
ok(errors.length === 0, "still no script errors " + errors.join(";"));
