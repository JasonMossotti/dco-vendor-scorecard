const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const errors = [];
const vc = () => new VirtualConsole().on("jsdomError", e => errors.push(String(e)));
const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/alarms/", virtualConsole: vc() });
const w = dom.window, d = w.document;
const t = () => d.getElementById("doc").textContent;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tab = id => [...d.querySelectorAll("#tabs button")].find(b => b.dataset.view === id);
const rows = () => [...d.querySelectorAll("#alarms tr.row")];
const chip = k => d.querySelector(`#chips .chip[data-k="${k}"]`);
const count = k => +chip(k).querySelector("b").textContent;
const D = JSON.parse(d.getElementById("data").textContent);
const fire = (el, type) => el.dispatchEvent(new w.Event(type, { bubbles: true }));

ok(errors.length === 0, "no script errors " + errors.join(";"));
ok(tab("board").classList.contains("on") && t().includes("Alarm history board"), "opens on the history board");
ok(d.getElementById("now").textContent.startsWith("Sep 15 12:40") && ["out_of_scope", "out_of_window"].some(c => rows()[0].classList.contains(c)) && d.querySelector('#active-changes .ch.flag[data-change="MOP-310"]'),
   "opens during the rack A07 outage with the flagged rows pinned");
ok(d.getElementById("utc").textContent.startsWith("Sep 15 17:40") && d.getElementById("utc").textContent.endsWith(" UTC"), "UTC clock under CDT in the same format: " + d.getElementById("utc").textContent);
ok([...d.getElementById("speed").options].map(o => o.textContent).includes("Real time"), "replay speed offers real time");
const modes = [...d.querySelectorAll("#modes button")].map(b => b.textContent);
ok(modes.join("|") === "Alarm History|Live Events" && d.querySelector('#modes [data-mode="history"]').classList.contains("on"), "two board buttons, Alarm History selected");
ok(d.getElementById("alert") && d.getElementById("alert").textContent.includes("4 alarms outside approved change work"), "alert banner for the unacknowledged flags");
ok(d.querySelector("#tickets") && d.getElementById("tickets").textContent.includes("WO-41023") && d.getElementById("tickets").textContent.includes("MOP-310"), "tickets panel: the open work order and the change ticket");
d.getElementById("seen").click();
ok(!d.getElementById("alert"), "acknowledging clears the banner");

// Flood grouping: alarms on one ticket collapse into one row; nothing is lost.
d.getElementById("end").click();
const nsum = () => rows().reduce((s, r) => s + +r.dataset.n, 0);
ok(d.querySelector("#alarms .grp") && nsum() === D.alarms.length && rows().length < D.alarms.length, `grouped rows account for every alarm (${rows().length} rows)`);
const before = rows().length;
d.querySelector("#alarms .grp").click();
ok(rows().length > before && d.querySelector("#alarms tr.child"), "a group expands to show its related alarms");
const grp = d.getElementById("group"); grp.checked = false; fire(grp, "change");
ok(rows().length === D.alarms.length, "grouping can be turned off");
d.getElementById("end").click();
ok(rows().length === D.alarms.length, `every alarm at the end of the month (${rows().length})`);
ok(["critical", "major", "minor", "clear"].reduce((s, k) => s + count(k), 0) === D.alarms.length, "severity chips add up to the alarms shown");
ok(count("out_of_scope") === 3 && count("out_of_window") === 1, "three out of scope and one out of window");
ok(rows()[0].classList.contains("out_of_scope") || rows()[0].classList.contains("out_of_window") ? false : true, "at the end of the month nothing flagged is still active, so nothing is pinned");
const head = [...d.querySelectorAll("#alarms th")].map(h => h.textContent);
ok(["Ack", "Source", "Ticket", "Device", "Location", "Summary", "Change work", "Tally", "First (CDT)"].every(h => head.includes(h)), "board columns");

// Replay the rack A07 day: start of MOP-310, then step forward.
d.getElementById("a07").click();
ok(d.getElementById("now").textContent.startsWith("Sep 15 09:47"), "replay starts at the MOP-310 window (CDT): " + d.getElementById("now").textContent);
ok(d.querySelector('#active-changes .ch[data-change="MOP-310"]') && rows().length === 0, "MOP-310 is in progress and nothing has alarmed yet");
const slider = d.getElementById("t");
const at = iso => { slider.value = String(Date.parse(iso)); fire(slider, "input"); };
at("2026-09-15T15:30:00Z");
ok(rows().length === 1 && rows()[0].classList.contains("expected"), "the A-side tap-off opening is expected (dimmed)");
at("2026-09-15T15:43:00Z");
const r1 = rows();
ok(r1.length === 4 && r1[0].classList.contains("out_of_scope") && r1[1].classList.contains("out_of_scope") && r1[2].classList.contains("out_of_scope"), "the B side and the rack outage are out of scope and pinned on top");
ok(d.querySelector('#active-changes .ch.flag') && t().includes("3 not reconciled"), "the change card turns red");
ok(r1.some(r => r.textContent.includes("Rack A07: 18 nodes not responding") && r.textContent.includes("IT Partner")), "the IT partner's rack outage joins the Landlord's change");
at("2026-09-15T17:20:00Z");
ok(!rows().some(r => r.classList.contains("out_of_window")), "no overrun alarm before the window plus grace");
at("2026-09-15T17:32:00Z");
ok(rows()[0].classList.contains("out_of_window") && rows()[0].textContent.includes("still in effect"), "the overrun alarm fires at the window plus 15 minutes");
rows()[0].click();
ok(t().includes("2 h 06 min after the window closed") && t().includes("NT-3 owed by Landlord within 5 min: missing"), "the detail row explains the overrun and the missing notification");
const tl = d.querySelector('#tlwrap svg.tl[data-change="MOP-310"]');
ok(tl && tl.querySelectorAll('line[stroke-width="5"]').length >= 4 && tl.textContent.includes("✕"), "the focused change shows its timeline, with the missing notification");
d.getElementById("handoffbtn").click();
const ho = d.getElementById("hotext").value;
ok(ho.startsWith("Site AUS-1 shift handoff, Sep 15 12:32 CDT") && /Not reconciled with approved change work \(4\)/.test(ho) && ho.includes("WO-41023") && ho.includes("Change work in progress (1)"), "shift handoff summary");
d.getElementById("hoclose").click();
ok(!d.getElementById("handoff"), "the handoff closes");

at("2026-09-15T10:00:00Z");
ok(d.querySelector('#upcoming-changes .ch.soon[data-change="MOP-310"]') && d.getElementById("upcoming-changes").textContent.includes("Starts in 4 h 47 min"), "MOP-310 is upcoming 6 hours ahead, with a countdown: " + d.getElementById("upcoming-changes").textContent.trim().slice(0, 120));
ok(!d.querySelector('#active-changes .ch[data-change="MOP-310"]'), "upcoming work is not yet in progress");
at("2026-09-15T08:00:00Z");
ok(!d.querySelector('#upcoming-changes .ch[data-change="MOP-310"]'), "beyond the 6-hour lead time it is not listed yet");
const lead = d.getElementById("lead");
ok([...lead.options].map(o => +o.value).join(",") === "2,4,6,8,10,12,14,16,18,20,22,24" && lead.value === "6", "lead time from 2 to 24 hours, default 6");
lead.value = "8"; fire(lead, "change");
ok(d.querySelector('#upcoming-changes .ch[data-change="MOP-310"]'), "an 8-hour lead time lists it");
at("2026-09-15T10:00:00Z"); lead.value = "2"; fire(lead, "change");
ok(!d.querySelector('#upcoming-changes .ch[data-change="MOP-310"]') && t().includes("next 2 hours"), "a 2-hour lead time does not");
at("2026-09-13T06:00:00Z"); lead.value = "24"; fire(lead, "change");
const chg = d.querySelector('#upcoming-changes .ch.flag[data-change="CHG2040031"]');
ok(chg && chg.textContent.includes("Live trouble: a05-ct15 has open INC3100629") && chg.textContent.includes("Confirm before starting"), "upcoming firmware work on rack A05 is flagged against the rack's open ticket");
ok(!d.querySelector('#upcoming-changes .ch.flag[data-change="MOP-305"]'), "upcoming work with nothing open on its equipment is not flagged");
at("2026-09-13T09:00:00Z");
ok(!d.querySelector('#upcoming-changes .ch.flag[data-change="CHG2040031"]'), "the flag clears when the ticket closes");
lead.value = "6"; fire(lead, "change");

// Filters.
d.getElementById("clearchange").click();
d.getElementById("end").click();
const party = d.getElementById("party"); party.value = "Landlord"; fire(party, "change");
ok(rows().every(r => r.textContent.includes("Landlord")) && rows().length === D.alarms.filter(a => a.partner === "Landlord").length, "partner filter");
d.getElementById("reset").click();
chip("critical").click();
ok(rows().length === 0, "no critical alarm is still active at the end of the month");
chip("critical").click(); chip("clear").click();
ok(rows().length === D.alarms.filter(a => a.cleared).length, "clear chip shows every cleared alarm");
d.getElementById("reset").click();
const q = d.getElementById("q"); q.value = "WO-41023"; fire(q, "input");
ok(rows().length === 2 && rows().every(r => r.textContent.includes("WO-41023")), "search by work order: the B side and the rack power loss");
d.getElementById("reset").click();
const hl = d.getElementById("hl"); hl.value = "CDU-B3"; fire(hl, "input");
ok(d.querySelectorAll("#alarms tr.hl").length >= 1 && rows().length === D.alarms.length, "highlight marks rows without filtering");

// Other views.
tab("changes").click();
ok(d.querySelectorAll("#changelist tr.row").length === D.declarations.length && t().includes("Change conflicts"), "every change with its declaration");
ok(d.querySelectorAll("#changelist svg.tl").length === D.declarations.length, "every change with its timeline");
ok(d.getElementById("changelist").textContent.includes("WO-41017") && d.getElementById("orphans").textContent.includes("WO-41014"), "work orders: under their MOP, and the one with no MOP on file");
const setRange = (a, b) => { tab("board").click(); const f = d.getElementById("from"), e = d.getElementById("to"); f.value = a; fire(f, "change"); d.getElementById("to").value = b; fire(d.getElementById("to"), "change"); tab("changes").click(); };
setRange("2026-09-13", "2026-09-14");
const ids = [...d.querySelectorAll("#changelist tr.row")].map(r => r.dataset.change);
ok(ids.join(",") === "MOP-309,MOP-305,CHG2040031" && t().includes("Showing 3 of 12") && !d.getElementById("orphans"), "the Change work tab follows the Board's date range: " + ids.join(","));
setRange("2026-09-24", "2026-09-24");
ok(d.querySelectorAll("#changelist tr.row").length === 0 && d.getElementById("orphans").textContent.includes("WO-41014"), "a day with only unapproved planned work");
d.getElementById("allrange").click();
ok(d.querySelectorAll("#changelist tr.row").length === D.declarations.length, "show the whole month again");
d.querySelector('#changelist tr[data-change="MOP-305"]').click();
ok(tab("board").classList.contains("on") && rows().length >= 1 && rows().every(r => r.textContent.includes("MOP-305")), "a change opens the board at its window");
tab("notify").click();
ok(d.querySelectorAll("#km tr").length === 3 && t().includes("IA-KM-01") && t().includes("IA-KM-02"), "both key measures");
ok(t().includes("Change window overrun") && d.querySelectorAll("#owed .badge.bad").length >= 2, "missing change-work notifications shown");
// Customer notification routing.
const mrow = ev => d.querySelector(`#matrix tr[data-event="${ev}"]`);
const counts = ev => [...mrow(ev).children].slice(-3).map(c => +c.textContent);
ok(d.querySelectorAll("#matrix tr[data-event]").length === 10 && counts("out_of_scope").join(",") === "3,9,9" && counts("nt_breach").join(",") === "4,4,0", "routing matrix with the sample month's events, emails, and texts");
ok(d.querySelectorAll("#oncall td").length === 168, "on-call schedule covers every hour of the week");
const look = () => d.getElementById("lookup").textContent;
ok(look().includes("after hours") && look().includes("Ops engineer 4") && look().includes("+1 512 555 0104"), "Monday 03:00 is the weekend on-call");
const lkd = d.getElementById("lkday"), lkt = d.getElementById("lktime");
lkd.value = "Tue"; fire(lkd, "change"); lkt.value = "10:00"; fire(lkt, "change");
ok(look().includes("business hours") && look().includes("Ops engineer 1"), "Tuesday 10:00 is business hours: " + look().slice(0, 80));
const lke = d.getElementById("lkevent"); lke.value = "minor"; fire(lke, "change");
ok(look().includes("board only"), "a minor alarm goes on the board only");
const majorEmails = counts("major")[1];
const mb = mrow("major").querySelector('input[data-k="business"][data-v="email"]'); mb.checked = false; fire(mb, "change");
ok(counts("major")[1] < majorEmails, `turning off business-hours email for major alarms cuts emails (${majorEmails} to ${counts("major")[1]})`);
d.getElementById("rcexport").click();
ok(d.getElementById("rcyaml").value.includes("{event: major, label: \"Major alarm\", business: [], after_hours: [email]"), "export gives the edited YAML");
d.getElementById("rcreset").click();
ok(counts("major")[1] === majorEmails && !d.getElementById("rcyaml"), "reset to the reviewed file");
ok(d.querySelectorAll("#dispatch tr").length > 100 && d.querySelector("#dispatch tr.escal"), "the dispatch replay lists messages and escalations");
tab("about").click();
ok(t().includes("not by itself a finding against anyone") && t().includes("NT-3"), "rules in plain words, with the framing");
const dom2 = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/alarms/#notify", virtualConsole: vc() });
ok(dom2.window.document.getElementById("doc").textContent.includes("Notifications owed to the Customer"), "a link to a view opens that view");

// Play and Pause: ticks update the board in place, so the Pause button is the same element and stops the replay.
tab("board").click();
d.getElementById("a07").click();
const playBtn = d.getElementById("play");
playBtn.click();
const t0 = d.getElementById("now").textContent;
setTimeout(() => {
  ok(d.getElementById("play") === playBtn && playBtn.textContent === "Pause", "the Pause button survives replay ticks");
  ok(d.getElementById("now").textContent !== t0, "the replay advanced: " + d.getElementById("now").textContent);
  playBtn.click();
  const t1 = d.getElementById("now").textContent;
  ok(playBtn.textContent === "Play", "Pause stops the replay");
  setTimeout(() => {
    ok(d.getElementById("now").textContent === t1, "the clock stays put after Pause");
    const sp = d.getElementById("speed"); sp.value = "1"; fire(sp, "change");
    playBtn.click();
    setTimeout(() => {
      const dt = Date.parse("2026 " + d.getElementById("utc").textContent.replace(" UTC", "") + "Z") - Date.parse("2026 " + t1.replace(" CDT", "") + "Z") - 5 * 3600e3;
      ok(dt >= 1000 && dt <= 3000, `real time advances about one second per second (${dt} ms)`);
      playBtn.click();
      live();
    }, 1600);
  }, 500);
}, 700);

// An upcoming change that overlaps redundancy-reducing work on connected equipment is flagged (none in the sample month).
const Dc = JSON.parse(JSON.stringify(D));
Dc.conflicts = [{changes: ["MOP-310", "MOP-305"], assets: [], text: "MOP-310 and MOP-305 both reduce power redundancy on connected equipment in overlapping windows"}];
const dom3 = new JSDOM(html.replace(d.getElementById("data").textContent, () => JSON.stringify(Dc)), { runScripts: "dangerously", url: "https://example.test/alarms/", virtualConsole: vc() });
const d3 = dom3.window.document, s3 = d3.getElementById("t");
s3.value = String(Date.parse("2026-09-15T10:00:00Z")); s3.dispatchEvent(new dom3.window.Event("input", { bubbles: true }));
ok(d3.querySelector('#upcoming-changes .ch.flag[data-change="MOP-310"]') && d3.getElementById("upcoming-changes").textContent.includes("Change conflict: MOP-310 and MOP-305"), "an upcoming change conflict is flagged");
dom3.window.close();

// Live Events: the sample runs on the viewer's clock (a fixed fake clock here).
function live() {
  let now = Date.parse("2026-10-06T17:00:00Z");
  w.Date.now = () => now;
  tab("board").click();
  d.querySelector('#modes [data-mode="live"]').click();
  ok(d.querySelector("h1").textContent === "Live event board" && !d.getElementById("t") && d.querySelector(".livebadge"), "Live Events: no replay slider, a live badge");
  ok(d.getElementById("now").textContent.startsWith("Oct 6 12:00:00") && d.getElementById("utc").textContent.startsWith("Oct 6 17:00:00"), "the live clock is the viewer's clock: " + d.getElementById("now").textContent);
  const W0 = Date.parse(D.window.start), SPAN = Math.floor((Date.parse(D.window.end) - W0) / 864e5) * 864e5, T = W0 + (now - W0) % SPAN;
  const byId = Object.fromEntries(D.alarms.map(a => [a.id, a]));
  ok(rows().every(r => { const a = byId[r.dataset.id]; return Date.parse(a.raised) <= T && (!a.cleared || Date.parse(a.cleared) > T - 6 * 3600e3); }), "only active alarms and those cleared in the last 6 hours");
  d.getElementById("liveA07").click();
  ok(d.querySelector('#active-changes .ch[data-change="MOP-310"]') && !rows().some(r => r.classList.contains("out_of_scope")) && !d.getElementById("alert"), "starting at the rack A07 incident: MOP-310 in progress, nothing flagged yet");
  now += 15 * 60e3;
  setTimeout(() => {
    ok(d.getElementById("now").textContent.startsWith("Oct 6 12:15"), "the live clock runs on: " + d.getElementById("now").textContent);
    ok(rows().some(r => r.classList.contains("out_of_scope")) && d.getElementById("alert") && d.getElementById("tickets").textContent.includes("WO-41023"), "ten minutes in, the B side opens: flagged, alerted, and the work order is open");
    d.querySelector('#modes [data-mode="history"]').click();
    ok(d.querySelector("h1").textContent === "Alarm history board" && d.getElementById("t"), "back to Alarm History");
    const dom4 = new JSDOM(html, { runScripts: "dangerously", url: "https://example.test/alarms/#live", virtualConsole: vc() });
    ok(dom4.window.document.querySelector("h1").textContent === "Live event board", "a link to #live opens the Live Events board");
    dom4.window.close();
    ok(errors.length === 0, "still no script errors " + errors.join(";"));
    w.close(); dom2.window.close();
  }, 1200);
}
