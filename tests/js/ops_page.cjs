const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/ops/", virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const t = () => d.getElementById("doc").textContent;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const C = JSON.parse(d.getElementById("data").textContent).calendar;
const go = h => { w.location.hash = h; w.dispatchEvent(new w.HashChangeEvent("hashchange")); };

ok(errors.length === 0, "no script errors " + errors.join(";"));
ok(t().includes("Maintenance and change calendar") && d.querySelector('.views a.on').dataset.view === "calendar", "opens on the Calendar view");
ok(d.querySelectorAll("#cal .day").length === C.days.length && C.days.length === 84 && C.days[0] === "2026-08-31" && C.days.at(-1) === C.first_compute, "twelve weeks of days, Aug 31 to first compute");
ok(d.querySelectorAll("#cal .day.fwd").length === C.days.length - C.past_days && d.querySelector(`#cal .day[data-day="${C.as_of}"]`).classList.contains("asof"), "the forward schedule is shaded from the as-of day");
ok(d.querySelectorAll("#cal .day.freeze").length === 8 && Object.keys(C.surge).every(s => d.querySelector(`#cal .day[data-day="${s}"] .sg`)), "the freeze days are shaded and every surge day is marked");
const chips = [...d.querySelectorAll("#cal .chip:not(.items)")].map(c => c.textContent);
ok(C.jobs.every(j => chips.includes(j.id) || d.querySelector(`#cal .day[data-day="${j.day}"]`).textContent.includes("more")), "every job is on its day");
ok(C.findings.every(f => f.jobs.every(id => [...d.querySelectorAll("#cal .chip.red")].some(c => c.textContent === id))), "every job in a finding is red");
ok([...d.querySelectorAll("#cal .chip.off")].map(c => c.textContent).sort().join() === C.jobs.filter(j => j.status === "deferred").map(j => j.id).sort().join(), "deferred changes are struck through");
ok(C.findings.every(f => t().includes(f.id) && t().includes(f.text)), "every finding listed with its text");
ok(C.agreements.every(a => t().includes(a.title)), "every agreement listed");
// a day
d.querySelector('#cal .day[data-day="2026-09-04"]').click(); go(w.location.hash.slice(1));
const dp = d.getElementById("daypanel");
ok(dp && dp.textContent.includes("Surge day: 3 Hall B energizations") && dp.textContent.includes("MOP-303") && dp.textContent.includes("Pump 2 of CDU-B3"), "a surge day opens with its jobs and what each takes out");
ok(dp.querySelectorAll(".tl .row").length === C.jobs.filter(j => j.day === "2026-09-04").length && dp.textContent.includes("CAL-1"), "a timeline row per job and the day's finding");
// a finding with device evidence
go("calendar/finding/CAL-5");
const fp = d.getElementById("findpanel");
ok(fp && fp.textContent.includes("MOP-310") && fp.querySelectorAll(".bar.dev").length === 2 && fp.textContent.includes("neither feed"), "the overrun shows the booked window beside both tap-offs the busway recorded");
ok(fp.textContent.includes("12:16 CDT") && fp.textContent.includes("14:22 CDT"), "times are Central");
const fwd = C.findings.filter(f => f.period === "forward");
ok(fwd.length === 4 && new Set(fwd.map(f => f.kind)).size === 4, "four forward conflicts, one of each kind");
go("calendar/finding/" + fwd.find(f => f.kind === "freeze").id);
ok(d.getElementById("findpanel").textContent.includes("CST"), "after November 1 the page shows standard time");
// a job
go("calendar/job/MOP-305");
const jp = d.getElementById("jobpanel");
ok(jp && jp.textContent.includes("UPS-A1") && jp.textContent.includes("IT UPSs (Hall A), 4 make 3") && jp.textContent.includes("PM-0012"), "a job names its unit, group, and maintenance record");
// filters
go("calendar");
const src = d.querySelector('select[data-f="source"]');
src.value = "Forward"; src.dispatchEvent(new w.Event("change"));
ok([...d.querySelectorAll("#cal .day:not(.fwd) .chip:not(.items)")].length === 0, "the Forward filter leaves the data weeks empty");
const red = d.querySelector('input[data-f="reduce"]');
red.checked = true; red.dispatchEvent(new w.Event("change"));
const left = [...d.querySelectorAll("#cal .chip:not(.items)")].map(c => c.textContent);
ok(left.length && left.every(id => { const j = C.jobs.find(x => x.id === id); return j.takes !== "none" && j.period === "forward"; }), "only forward jobs that take a unit out");
// Safety (EHS)
const S = JSON.parse(d.getElementById("data").textContent).ehs;
go("ehs");
ok(d.querySelector('.views a.on').dataset.view === "ehs" && t().includes("Safety (EHS)") && t().includes("Monthly EHS report"), "the Safety view opens with the monthly EHS report");
ok(Object.keys(S.report).length === 3 && Object.values(S.partners).every(n => t().includes(n)), "the report has a row for each partner");
ok(d.querySelectorAll("#permits tr").length - 1 === S.permits.length, "every permit is listed");
ok(S.findings.length === 5 && S.findings.every(f => t().includes(f.id) && t().includes(f.text)), "every finding listed with its text");
ok(S.agreements.every(a => t().includes(a.title) && a.checked - a.misses.length + a.explained === a.checked), "every agreement listed, and each holds or is explained");
ok(t().includes("never findings") && S.events.every(x => t().includes(x.event + "")), "reported events are listed and are never findings");
ok(t().includes("PIR-2026-001") && t().includes("Referred to Customer EHS"), "the A07 review's referral to Customer EHS is shown");
// the as-found finding: the wrong tap-off
const a07 = S.findings.find(f => f.refs.includes("TO-A07-B"));
go("ehs/finding/" + a07.id);
const sf = d.getElementById("sfpanel");
ok(sf && sf.textContent.includes("no permit open on it") && sf.textContent.includes("10:42 CDT") && sf.querySelectorAll(".bar.dev").length === 1 && sf.querySelectorAll(".bar.permit").length === 1, "the wrong tap-off opened with no permit, beside the first permit on it");
// a lockout recorded before the device isolated the circuit
const lp = S.findings.find(f => f.kind === "lock_power");
go("ehs/finding/" + lp.id);
ok(d.getElementById("sfpanel").querySelectorAll(".bar.lock").length === 1 && d.getElementById("sfpanel").querySelectorAll(".bar.dev").length === 1, "a lockout finding shows the lockout beside the device's isolation");
// untrained: badge-ins and the lapsed course
const un = S.findings.find(f => f.kind === "untrained");
go("ehs/finding/" + un.id);
ok(d.getElementById("sfpanel").textContent.includes("Badge-ins that day") && d.getElementById("sfpanel").textContent.includes("NFPA 70E"), "a training finding shows the lapsed course and the badge-ins");
// a permit
const pf = S.permits.find(p => p.permit === un.refs[1]);
go("ehs/permit/" + pf.permit);
const pp = d.getElementById("permitpanel");
ok(pp && pp.textContent.includes(pf.job) && pp.querySelector(".flag.bad") && pp.textContent.includes("lapsed") && pp.textContent.includes(un.id), "a permit names its job, its people's training, and its finding");
// filters
go("ehs");
const ty = d.querySelector('select[data-fe="ptype"]');
ty.value = "loto"; ty.dispatchEvent(new w.Event("change"));
ok(d.querySelectorAll("#permits tr").length - 1 === S.permits.filter(p => p.type === "loto").length, "the type filter shows only lockouts");
const fl = d.querySelector('input[data-fe="flagged"]');
fl.checked = true; fl.dispatchEvent(new w.Event("change"));
ok(d.querySelectorAll("#permits tr").length - 1 === S.permits.filter(p => p.type === "loto" && p.findings.length).length, "only lockouts in a finding");
go("ehs/permit/" + pf.permit);
d.querySelector('[data-close="ehs"]').click();
ok(w.location.hash === "#ehs", "closing a panel stays on the Safety view");
ok(errors.length === 0, "still no script errors " + errors.join(";"));
