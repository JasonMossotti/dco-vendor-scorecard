// The training portal's views on the Training tab: courses, job guides, PM guides, and quizzes scored in the browser.
// Usage: node training_portal.cjs TRAINING.html
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const errors = [];
const dom = new JSDOM(fs.readFileSync(process.argv[2], "utf8"), { runScripts: "dangerously", url: "https://example.test/training/#courses",
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const t = () => d.getElementById("doc").textContent;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const T = JSON.parse(d.getElementById("data").textContent).portal;
const REFS = JSON.parse(d.getElementById("refs").textContent);
const go = h => { w.location.hash = h; w.dispatchEvent(new w.HashChangeEvent("hashchange")); };

ok(d.querySelector(".views a.on").dataset.view === "courses", "opens Courses from its address");
ok(T.courses.every(c => d.querySelector(`a[href="#course/${c.id}"]`)), "every course listed");
const pf = d.getElementById("pf");
pf.value = "Security Partner"; pf.dispatchEvent(new w.Event("change"));
ok(T.courses.filter(c => c.partner === "Security Partner" || c.partner === "Everyone").every(c => d.querySelector(`a[href="#course/${c.id}"]`))
   && !d.querySelector('a[href="#course/cdu"]'), "filter courses by partner");
// a course with devices, drawings, records, and references
const ups = T.courses.find(c => c.id === "ups");
go("course/ups");
ok(d.querySelector(".views a.on").dataset.view === "courses" && t().includes(ups.title), "a course opens");
ok(ups.devices.every(g => g.names.every(n => d.querySelector(`a[href="../devices/#${encodeURIComponent(n)}"]`))), "its devices link to the device directory");
ok(ups.sheets.every(s => d.querySelector(`a[href="../site/${encodeURIComponent(s.file)}"]`)), "its drawings link");
ok(ups.records.every(r => t().includes(r.id)), "its records from the sample are listed");
const upsRefs = REFS.items["courses:ups"];
ok(upsRefs.length > 0 && upsRefs.every(k => d.querySelector(`a[href="${REFS.list[k].url}"][target="_blank"][rel="noopener noreferrer"]`)), "its references open in a new tab");
ok(!JSON.stringify(T).includes("https://"), "no web address in the glossary-scanned data");
ok(ups.raci.every(r => t().includes(r.component)), "its RACI rows");
// job guides
go("guides");
ok(T.guides.every(g => d.querySelector(`a[href="#guide/${g.id}"]`)), "every job guide listed");
const g = T.guides.find(x => x.id === "ups-on-battery");
go("guide/" + g.id);
ok(t().includes("First 15 minutes") && t().includes(g.owner) && g.first15.every(s => t().includes(s)), "a job guide opens with its first 15 minutes and owner");
ok(g.procedure && d.querySelector(`a[href="../emergency/#proc/${g.procedure.id}"]`), "it links the emergency procedure");
ok(t().includes(`${g.alarm_count} alarm`), "it counts the sample's alarms");
// PM guides
go("pm");
ok(T.pm.every(p => d.querySelector(`a[href="#pm/${p.id}"]`)), "every PM guide listed");
const p = T.pm.find(x => x.id === "ups_pm");
go("pm/ups_pm");
ok(d.querySelector(".views a.on").dataset.view === "pm" && t().includes(p.title) && t().includes(`${p.minutes} minutes`) && p.permits.every(x => t().includes(x.name)), "a PM guide opens with its duration and permits");
ok(p.records.every(r => t().includes(r.id)) && p.forward.every(j => t().includes(j.id)), "its records and scheduled jobs");
// quizzes
go("quizzes");
ok(T.quizzes.length === 4 && T.quizzes.every(q => d.querySelector(`a[href="#quiz/${q.id}"]`)), "four quizzes");
const q = T.quizzes.find(x => x.id === "security");
go("quiz/security");
ok(d.querySelectorAll("fieldset.qq").length === q.questions.length, "every question shown");
q.questions.forEach((x, i) => { const pick = i === 0 ? (x.answer + 1) % x.options.length : x.answer; d.querySelector(`input[name="q${i}"][value="${pick}"]`).checked = true; });
d.getElementById("score").click();
ok(d.getElementById("result").textContent.startsWith(`${q.questions.length - 1} of ${q.questions.length} right`), "scored in the browser");
ok(d.querySelectorAll("fieldset.qq.wrong").length === 1 && d.querySelector("fieldset.qq.wrong .why").textContent.includes(q.questions[0].options[q.questions[0].answer]), "a wrong answer shows the right one");
ok(d.getElementById("result").textContent.includes("Not recorded"), "nothing recorded");
d.getElementById("reset").click();
ok(!d.querySelector("fieldset.qq.wrong") && d.getElementById("result").textContent === "", "start again clears it");
// the register's views still work beside the portal
go("certs");
ok(d.querySelector(".views a.on").dataset.view === "certs", "Certifications still opens");
ok(errors.length === 0, "no script errors " + errors.join(";"));
