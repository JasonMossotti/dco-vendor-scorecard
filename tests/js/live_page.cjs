// node tests/js/live_page.cjs <site>/live
// <site>/live is the folder scripts/render_live.py write_site() wrote: index.html plus data/index.json and data/day_NN.json.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const path = require("path");
const dir = process.argv[2];
const html = fs.readFileSync(path.join(dir, "index.html"), "utf8");
const errors = [];
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const fetches = [];
function fakeFetch(url) {
  const rel = String(url).replace(/^https:\/\/example\.test\/live\//, "");
  fetches.push(rel);
  const p = path.join(dir, decodeURIComponent(rel));
  if (!fs.existsSync(p)) return Promise.resolve({ ok: false, status: 404, json: async () => { throw new Error("404"); } });
  return Promise.resolve({ ok: true, status: 200, json: async () => JSON.parse(fs.readFileSync(p, "utf8")) });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, what, ms = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (fn()) return true; } catch (e) { /* keep polling */ } await sleep(25); }
  console.log("timed out waiting for", what);
  return false;
}
const open = hash => new JSDOM(html, {
  runScripts: "dangerously", url: "https://example.test/live/" + (hash ? "#" + hash : ""),
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e && e.stack || e))),
  beforeParse(window) { window.fetch = fakeFetch; },
});

(async () => {
  const D = JSON.parse(html.split('<script id="data" type="application/json">')[1].split("</script>")[0]);
  const W0 = Date.parse(D.window.start), MIN = 60e3, DAY = 864e5, SPAN = Math.floor((Date.parse(D.window.end) - W0) / DAY) * DAY;
  const trip = D.jumps.find(j => j.key === "trip").m + 4;            // the minute after the utility tripped (21:14:20 UTC)

  // ---- the live feed: no hash runs on the viewer's clock, on the Alarm Board's formula
  let dom = open(""), w = dom.window, d = w.document, $ = id => d.getElementById(id);
  await until(() => !$("lv-mains").textContent.includes("Loading"), "today's day file");
  ok(errors.length === 0, "no script errors on load " + errors.join(";"));
  ok($("badge").textContent.includes("LIVE") && $("badge").classList.contains("live"), "opens on the live feed");
  const now = Date.now(), t = W0 + ((now - W0) % SPAN + SPAN) % SPAN, m = Math.floor((t - W0) / MIN);
  ok($("where").textContent.includes(`minute ${m} `) || $("where").textContent.includes(`minute ${m + 1} `), "the sample minute is the Live Events board's (whole days re-dated to today)");
  const lt = new Date(now - 5 * 3600e3);
  ok($("now").textContent.startsWith(`${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][lt.getUTCMonth()]} ${lt.getUTCDate()} `), "the clock shows the viewer's date in CDT");
  ok(fetches.some(f => f === `data/day_${String(Math.floor(m / 1440)).padStart(2, "0")}.json`), "loads only today's day file");
  ok(d.querySelectorAll("#lv-fam .fam").length === 9, "a tile per family, fire protection, and security");
  ok(d.querySelectorAll("#lv-red a.chip").length === D.groups.length, "a chip for every redundancy group");
  ok(d.querySelector('a[href="../alarms/#live"]') && d.querySelector('a[href="../tickets/"]'), "links the Alarm Board's live events and the Incident Portal");
  w.close();

  // ---- the utility trip, paused at its minute
  dom = open(String(trip)); w = dom.window; d = w.document;
  await until(() => !$("lv-mains").textContent.includes("Loading"), "the trip's day file");
  ok($("badge").textContent.includes("Paused"), "a minute in the link opens paused");
  ok($("lv-src").textContent.includes("On generators") && $("lv-src").textContent.includes("7 of 7 generators"), "on generators, all seven on the bus");
  ok([...d.querySelectorAll("#lv-mains tbody tr")].every(r => r.textContent.includes("dead") && r.textContent.includes("open")), "both mains dead, breakers open");
  const rides = [...d.querySelectorAll("#lv-ride .rt .v")].map(x => x.textContent);
  ok(/^\d+:\d\d$/.test(rides[0]) && /^\d+:\d\d$/.test(rides[1]), "IT and cooling ride-through in min:sec " + rides.slice(0, 2));
  ok($("lv-ride").textContent.includes(`${D.power.outages[0].bridge_s} s`) && $("lv-ride").textContent.includes("Margin now"), "take-load time and margin");
  const util = [...d.querySelectorAll("#lv-red a.chip")].find(a => a.title.startsWith("Utility feeds"));
  ok(util && util.classList.contains("bad") && util.textContent.includes("0 of 2"), "utility feeds 0 of 2, red");
  const pw = d.querySelector('#lv-fam .fam[data-fam="power"]');
  ok(pw.classList.contains("bad") && pw.textContent.includes("site on generators"), "power family lost: site on generators");
  ok($("lv-ops").textContent.includes("Utility power lost"), "the Alarm Board's alarm is active");
  ok(d.querySelector(`#lv-mains a[href="../telemetry/#MV-A/${trip}"]`) && d.querySelector(`#lv-ups a[href="../telemetry/#UPS-A1/${trip}"]`), "devices link into Telemetry at the same minute");

  // ---- an hour earlier: on utility, both mains near 13.8 kV
  w.location.hash = String(trip - 60); await sleep(40);
  await until(() => $("lv-src").textContent.includes("On utility"), "utility back");
  ok($("lv-src").textContent.includes("On utility"), "an hour earlier the site is on utility");
  const kv = [...d.querySelectorAll("#lv-mains tbody tr td:nth-child(2)")].map(x => parseFloat(x.textContent));
  ok(kv.length === 2 && kv.every(v => v > 13.1 && v < 14.5), "both mains near 13.8 kV " + kv);
  const amps = [...d.querySelectorAll("#lv-mains tbody tr td:nth-child(3)")].map(x => parseFloat(x.textContent.replace(/,/g, "")));
  ok(amps.every(a => a > 10), "both mains carry current " + amps);
  ok(d.querySelectorAll("#lv-mains svg.spark polyline").length === 2, "a last-hour sparkline per main");
  ok(!d.querySelector('#lv-red a.chip.bad'), "full redundancy an hour before the trip");

  // ---- the rack A07 outage jump runs from just before it
  d.querySelector('button[data-jump]').click(); await sleep(20);
  const a07 = [...d.querySelectorAll("button[data-jump]")].find(b => b.textContent.includes("A07"));
  a07.click(); await sleep(40);
  ok($("badge").textContent.includes("Replay"), "a jump replays from that moment");
  w.location.hash = String(+a07.dataset.jump + 25); await sleep(40);
  const feeds = [...d.querySelectorAll("#lv-red a.chip")].find(a => a.title.startsWith("Rack feeds, Hall A"));
  ok(feeds && feeds.classList.contains("bad"), "Hall A rack feeds red during the A07 outage");
  ok(d.querySelector('#lv-fam .fam[data-fam="power"] a[href^="../telemetry/#A07/"]'), "the A07 condition links the rack at its hour");

  // ---- pause and speed
  w.location.hash = ""; await sleep(40);
  $("pause").click(); ok($("badge").textContent.includes("Paused") && $("pause").textContent === "Play", "pause");
  $("pause").click(); ok(!$("badge").textContent.includes("Paused"), "play");
  $("speed").value = "60"; $("speed").dispatchEvent(new w.Event("change"));
  ok($("badge").textContent.includes("1 min per second"), "faster speed");
  $("golive").click(); ok($("badge").textContent.includes("LIVE"), "back to the live feed");

  // ---- escaping and integrity
  const conds = [...d.querySelectorAll("#lv-fam li")].map(x => x.textContent).join("");
  ok(!/[<>]/.test(conds), "condition text is escaped");
  ok([...d.querySelectorAll('a[href^="../tickets/#"]')].every(a => a.target === "_blank" && a.rel === "noopener"), "ticket links open the Incident Portal in a new tab");
  ok(errors.length === 0, "no script errors " + errors.join(";"));
  w.close();
})();
