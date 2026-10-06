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
ok(tab("board").classList.contains("on") && t().includes("Customer alarm board"), "opens on the board");
ok(d.getElementById("now").textContent.startsWith("Sep 15 12:40") && ["out_of_scope", "out_of_window"].some(c => rows()[0].classList.contains(c)) && d.querySelector('#active-changes .ch.flag[data-change="MOP-310"]'),
   "opens during the rack A07 outage with the flagged rows pinned");
ok(d.getElementById("utc").textContent.startsWith("Sep 15 17:40") && d.getElementById("utc").textContent.endsWith(" UTC"), "UTC clock under CDT in the same format: " + d.getElementById("utc").textContent);
ok([...d.getElementById("speed").options].map(o => o.textContent).includes("Real time"), "replay speed offers real time");
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

at("2026-09-15T10:00:00Z");
ok(d.querySelector('#upcoming-changes .ch.soon[data-change="MOP-310"]') && d.getElementById("upcoming-changes").textContent.includes("Starts in 4 h 47 min"), "MOP-310 is upcoming 6 hours ahead, with a countdown: " + d.getElementById("upcoming-changes").textContent.trim().slice(0, 120));
ok(!d.querySelector('#active-changes .ch[data-change="MOP-310"]'), "upcoming work is not yet in progress");
at("2026-09-15T08:00:00Z");
ok(!d.querySelector('#upcoming-changes .ch[data-change="MOP-310"]'), "beyond the 6-hour lead time it is not listed yet");

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
d.querySelector('#changelist tr[data-change="MOP-305"]').click();
ok(tab("board").classList.contains("on") && rows().length >= 1 && rows().every(r => r.textContent.includes("MOP-305")), "a change opens the board at its window");
tab("notify").click();
ok(d.querySelectorAll("#km tr").length === 3 && t().includes("IA-KM-01") && t().includes("IA-KM-02"), "both key measures");
ok(t().includes("Change window overrun") && d.querySelectorAll("#owed .badge.bad").length >= 2, "missing change-work notifications shown");
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
      ok(errors.length === 0, "still no script errors " + errors.join(";"));
      w.close(); dom2.window.close();
    }, 1600);
  }, 500);
}, 700);
