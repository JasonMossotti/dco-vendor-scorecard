// node tests/js/live_page.cjs <site>/live
// <site>/live is the folder scripts/render_live.py write_site() wrote: index.html plus data/index.json, data/day_NN.json,
// and data/now_sample.json. tests/test_live_status.py adds data/now_collector.json (written by the collector's NowWriter
// from in-process simulators) and data/now_stale.json (the same, an hour old).
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
const open = (hash, query) => new JSDOM(html, {
  runScripts: "dangerously", url: "https://example.test/live/" + (query ? "?" + query : "") + (hash ? "#" + hash : ""),
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

  // ---- the feed contract: the sample minute replayed as now.json reads exactly as the clock at that minute
  const sample = JSON.parse(fs.readFileSync(path.join(dir, "data", "now_sample.json"), "utf8"));
  const clock = open(String(sample.source.minute)), cd = clock.window.document, c$ = id => cd.getElementById(id);
  await until(() => !c$("lv-mains").textContent.includes("Loading"), "the clock at the sample minute");
  const feed = open("", "feed=data/now_sample.json"), fd = feed.window.document, f$ = id => fd.getElementById(id);
  await until(() => f$("lv-mains").querySelector("table"), "the sample feed");
  ok(f$("badge").textContent.includes("FEED") && f$("badge").textContent.includes(String(sample.source.minute)) && !f$("pause"), "?feed= reads the file, with no clock controls");
  for (const id of ["lv-src", "lv-mains", "lv-ups", "lv-gen"]) ok(f$(id).innerHTML === c$(id).innerHTML, `feed and clock agree: ${id}`);
  const cards = x => [...x.querySelectorAll("#lv-ride .rt")].map(e => e.outerHTML).join("");
  ok(cards(fd) && cards(fd) === cards(cd), "feed and clock agree: every ride-through card");
  const famState = x => [...x.querySelectorAll("#lv-fam .fam")].filter(e => e.dataset.fam !== "fire" && e.dataset.fam !== "security").map(e => e.dataset.fam + ":" + e.className).join(",");
  ok(famState(fd) === famState(cd), "feed and clock agree: every family's state " + famState(fd));
  const chips = x => [...x.querySelectorAll("#lv-red a.chip")].map(a => a.className + a.textContent).join("|");
  ok(chips(fd) === chips(cd), "feed and clock agree: every redundancy chip");
  ok(f$("site").textContent === c$("site").textContent, "feed and clock agree: the site's state");
  ok(!f$("lv-stale").textContent, "a replay is never stale");
  clock.window.close(); feed.window.close();

  // ---- a collector's file (tests/test_live_status.py writes it from the simulators)
  if (fs.existsSync(path.join(dir, "data", "now_collector.json"))) {
    const cdoc = JSON.parse(fs.readFileSync(path.join(dir, "data", "now_collector.json"), "utf8"));
    const col = open("", "feed=data/now_collector.json"), kd = col.window.document, k$ = id => kd.getElementById(id);
    await until(() => k$("lv-mains").querySelector("table"), "the collector's feed");
    ok(k$("badge").textContent.includes("collector"), "a collector's feed is named");
    ok([...kd.querySelectorAll("#lv-mains tbody tr")].length === Object.keys(cdoc.mains).length, "one row per main in the feed");
    ok([...kd.querySelectorAll("#lv-ups tbody tr")].length === Object.keys(cdoc.ups).length, "one row per UPS in the feed, none for the rest");
    ok(kd.querySelector('#lv-mains a[href="../telemetry/#MV-A"]'), "a collector's devices link without a minute");
    ok(/^\d+:\d\d$/.test(kd.querySelector("#lv-ride .rt .v").textContent), "ride-through from the collector in min:sec");
    ok(kd.querySelector('#lv-fam .fam[data-fam="gpu"]').textContent.includes("not in this feed"), "a family with no device in the feed says so");
    const bad = cdoc.feeds.filter(f => !f.ok);
    ok(bad.length && k$("lv-feeds").textContent.includes(bad[0].site_id || bad[0].device) && k$("lv-feeds").querySelector(".tag.bad"), "a device not answering is listed under Feeds");
    ok(!k$("lv-stale").textContent, "a fresh collector file is not stale");
    ok(k$("lv-red").textContent.includes("Not in this feed"), "redundancy says it is not in a collector's feed");
    ok(!/[<>]/.test([...kd.querySelectorAll("#lv-fam li")].map(x => x.textContent).join("")), "feed condition text is escaped");
    col.window.close();
    const st = open("", "feed=data/now_stale.json"), sd = st.window.document;
    await until(() => sd.getElementById("lv-mains").querySelector("table"), "the stale feed");
    ok(sd.getElementById("lv-stale").textContent.includes("Feed stale"), "a collector file past stale_after_s carries the stale banner");
    st.window.close();
    const no = open("", "feed=data/missing.json"), nd = no.window.document;
    await until(() => nd.getElementById("lv-stale").textContent.includes("did not answer"), "the missing feed");
    ok(nd.getElementById("lv-stale").textContent.includes("did not answer"), "a feed that does not answer says so");
    no.window.close();
    const bs = open("", "feed=https://evil.test/now.json"), bd = bs.window.document;
    ok(bd.getElementById("pause"), "a feed URL off this site is ignored (the clock runs)");
    bs.window.close();
  }
  ok(errors.length === 0, "no script errors in feed mode " + errors.join(";"));
  process.exit();
})();
