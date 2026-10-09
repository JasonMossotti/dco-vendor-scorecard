// node tests/js/telemetry_page.cjs <site>/index.html <site>
// <site> is the folder scripts/render_telemetry.py write_site() wrote: index.html plus data/ (racks.json, gpu/, windows/).
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(process.argv[2], "utf8");
const site = process.argv[3] || path.dirname(process.argv[2]);
const errors = [];
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const fetches = [];
function fakeFetch(url) {
  const rel = String(url).replace(/^https:\/\/example\.test\/telemetry\//, "");
  fetches.push(rel);
  const p = path.join(site, decodeURIComponent(rel));
  if (!fs.existsSync(p)) return Promise.resolve({ ok: false, status: 404, json: async () => { throw new Error("404"); } });
  return Promise.resolve({ ok: true, status: 200, json: async () => JSON.parse(fs.readFileSync(p, "utf8")) });
}
const opts = {
  runScripts: "dangerously", url: "https://example.test/telemetry/",
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e && e.stack || e))),
  beforeParse(window) { window.fetch = fakeFetch; },
};
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, what, ms = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (fn()) return true; } catch (e) { /* keep polling */ } await sleep(25); }
  console.log("timed out waiting for", what);
  return false;
}

(async () => {
  const dom = new JSDOM(html, opts);
  const w = dom.window, d = w.document;
  const D = JSON.parse(d.getElementById("data").textContent);
  const main = () => d.getElementById("main");
  const t = () => main().textContent;
  const go = async hash => { w.location.hash = hash; await sleep(30); };

  // ---- overview
  ok(errors.length === 0, "no script errors on load " + errors.join(";"));
  ok(t().includes("GPU telemetry") && d.querySelectorAll(".tile").length === 11, "overview: five tiles per hall and the agreements tile");
  const agree = D.agreements.reduce((a, c) => a + c.checked - c.misses, 0), tot = D.agreements.reduce((a, c) => a + c.checked, 0);
  ok(t().includes(`${agree.toLocaleString("en-US")} of ${tot.toLocaleString("en-US")}`), "agreements count on the overview");
  ok(t().includes(`${D.halls["HALL-B"].at_cap_pct.toFixed(1)}%`) && t().includes("132 kW"), "Hall B time at the power limit and the cap's reason");
  ok(d.querySelectorAll("#tree a").length >= D.racks.length + 4, "tree lists every rack");
  await until(() => d.querySelectorAll("#hm g[data-rack]").length === D.racks.length, "heatmap rows");
  ok(d.querySelectorAll("#hm g[data-rack]").length === D.racks.length, "heatmap: a row per rack");
  const b14 = D.racks.find(r => r.rack === "B14");
  const first = () => d.querySelector('#hm g[data-rack="B14"] rect');
  ok(first() && first().getAttribute("x") === "0" && first().getAttribute("fill") === "var(--none)" && +first().getAttribute("width") === b14.from_hour, "Hall B rows are grey before power-on");
  const a07 = () => [...d.querySelectorAll('#hm g[data-rack="A07"] rect')].find(r => +r.getAttribute("x") <= 377 && +r.getAttribute("x") + +r.getAttribute("width") > 377);
  ok(a07() && a07().getAttribute("fill") === "var(--none)", "A07 is grey during the Sep 15 outage hour");
  const before = d.querySelector("#hm svg").innerHTML;
  d.querySelector('#hm-btns button[data-m="util"]').click();
  await until(() => d.querySelector('#hm-btns button[data-m="util"]').classList.contains("on") && d.querySelector("#hm svg").innerHTML !== before, "metric switch");
  ok(d.querySelector("#hm svg").innerHTML !== before && t().includes("0 %") && t().includes("100 %"), "switching the heatmap metric redraws it with the new scale");
  ok(d.querySelectorAll("#hm .hmticks span").length >= 9, "day ticks on the heatmap");
  ok(t().includes("XID 94") && d.querySelector('a[href="#a31-ct11/0"]') && t().includes("18 trays"), "notable events link to GPUs and group the rack power loss");
  ok(d.querySelector('#tree a[href="#gpus"]').classList.contains("on"), "tree highlights the overview");

  // ---- rack view at the outage hour
  await go("#A07/377");
  await until(() => d.querySelectorAll(".gg button[data-host]").length === 72, "A07 grid");
  ok(d.querySelectorAll(".gg button[data-host]").length === 72 && d.querySelectorAll(".gg button.no").length === 72, "#A07 at Sep 15 17:00 UTC: every GPU cell is dark (no samples)");
  ok(t().includes("Sep 15 17:00 UTC") && d.getElementById("hr").value === "377", "hour selector shows the outage hour");
  ok(d.querySelector('#tree a[href="#A07"]').classList.contains("on"), "tree highlights the rack");
  await until(() => d.querySelectorAll("#rc svg").length === 3, "rack charts");
  ok(d.querySelectorAll("#rc svg").length === 3 && t().includes("CDU-A1 secondary supply"), "three rack month charts with the CDU supply line");
  d.getElementById("hr").value = "300";
  d.getElementById("hr").dispatchEvent(new w.Event("input", { bubbles: true }));
  await until(() => d.querySelectorAll(".gg button.no").length === 0, "grid at hour 300");
  ok(d.querySelectorAll(".gg button.no").length === 0 && w.location.hash === "#A07/300", "moving the hour slider recolours the grid and updates the address");
  d.querySelector('#gg-btns button[data-m="cap"]').click();
  await until(() => d.querySelector('#gg-btns button[data-m="cap"]').classList.contains("on"), "grid metric");
  ok(t().includes("Time at power limit") && d.querySelector('#gg-btns button[data-m="cap"]').classList.contains("on"), "grid metric switch");

  // ---- the XID 94 GPU
  await go("#a31-ct11/0");
  await until(() => d.querySelectorAll("table.labels td").length > 0, "GPU labels");
  const x = t();
  ok(x.includes("a31-ct11 GPU 0") && x.includes("GPU-cb5953d0-6aee-9f09-bf52-e47384e4b06f") && x.includes("GPU-a95746f8-e0e3-442e-b940-d620ba2e6a43") && x.includes("new GPUs, new UUID, new series"), "labels show both UUIDs across the tray replacement");
  ok(x.includes("XID 94") && d.querySelector('a[href="../tickets/#INC3100068"]'), "XID 94 event with its ticket link");
  ok(x.includes("GH-F2") && d.querySelector('a[href="../gpu/#A31"]'), "the GPU Health finding on this host, linked");
  ok(main().querySelectorAll("svg[data-ch]").length === 4, "four month charts");
  ok(main().querySelectorAll("svg[data-ch] rect[fill='#e3e7ec']").length >= 4, "drain bands on the charts");
  ok(x.includes("Sep 1 05:49 UTC") && x.includes("pending"), "counters table shows the change and the pending remap");
  ok(d.getElementById("scrape").textContent.includes("# TYPE DCGM_FI_DEV_GPU_TEMP gauge") && d.getElementById("scrape").textContent.includes("Sep 27 23:59 UTC") === false, "month's last scrape shown before a window is opened");
  ok(d.querySelectorAll("#win-btns button").length === 2, "two minute windows for this tray");
  d.querySelector("#win-btns button").click();
  await until(() => d.getElementById("wm"), "window loaded");
  ok(d.getElementById("wm") && main().querySelectorAll("#win svg[data-ch]").length === 4, "minute detail: four minute charts");
  const sc = () => d.getElementById("scrape").textContent;
  ok(sc().includes("# TYPE DCGM_FI_DEV_GPU_TEMP gauge") && sc().includes('DCGM_FI_DEV_XID_ERRORS{gpu="0"') && /DCGM_FI_DEV_XID_ERRORS\{[^}]*\} 94\n/.test(sc()), "scrape at the cursor shows XID 94 after the XID minute");
  ok(sc().includes('Hostname="a31-ct11"') && sc().includes('modelName="NVIDIA GB200"') && sc().includes("# HELP DCGM_FI_DEV_THERMAL_VIOLATION"), "scrape labels and HELP lines");
  d.getElementById("wm").value = "10";
  d.getElementById("wm").dispatchEvent(new w.Event("input", { bubbles: true }));
  await sleep(20);
  ok(/DCGM_FI_DEV_XID_ERRORS\{[^}]*\} 0\n/.test(sc()) && t().includes("Sep 1 04:59 UTC"), "moving the cursor before the XID shows 0");
  d.getElementById("wm").value = "100";
  d.getElementById("wm").dispatchEvent(new w.Event("input", { bubbles: true }));
  await sleep(20);
  ok(/DCGM_FI_DEV_GPU_UTIL\{[^}]*\} 0\n/.test(sc()) && /DCGM_FI_DEV_XID_ERRORS\{[^}]*\} 94\n/.test(sc()), "a drained minute still scrapes: utilization 0, last XID kept");
  d.getElementById("csv").click();
  await sleep(10);
  ok(t().includes("rows"), "CSV button runs without an exception (" + d.getElementById("csv-note").textContent + ")");

  // ---- a tray that went dark (rack A07 power loss): the window's minute after the samples stop
  await go("#a07-ct01/0");
  await until(() => d.querySelectorAll("#win-btns button").length === 2, "A07 windows");
  d.querySelector("#win-btns button").click();
  await until(() => d.getElementById("wm"), "A07 window loaded");
  d.getElementById("wm").value = "100";
  d.getElementById("wm").dispatchEvent(new w.Event("input", { bubbles: true }));
  await sleep(20);
  ok(sc().includes("no sample") && !/DCGM_FI_DEV_GPU_TEMP\{/.test(sc()), "a dark minute says no sample, never a zero reading");
  ok(t().includes("rack input power lost"), "the tray's events name the rack power loss");

  // ---- reference pages
  await go("#fields");
  ok(D.fields.every(f => t().includes(f.name)) && d.querySelectorAll(".tag.it").length === D.collection.enabled_beyond_default.length, "field reference lists every field and marks the four turned on");
  ok(t().includes("9400") && d.querySelector('a[href^="https://github.com/NVIDIA/dcgm-exporter"]'), "collection settings and sources");
  await go("#agreements");
  ok(D.agreements.every(a => t().includes(a.title)) && t().includes("never to contradict"), "agreements page shows every check");

  // ---- error state
  await go("#A99");
  ok(t().includes("GPU telemetry"), "an unknown rack falls back to the overview");
  fs.renameSync(path.join(site, "data/gpu/A12.json"), path.join(site, "data/gpu/A12.json.bak"));
  try {
    await go("#A12");
    await until(() => t().includes("Could not load"), "error message");
    ok(t().includes("Could not load data/gpu/A12.json") && errors.length === 0, "a missing rack file shows a message, not an exception");
  } finally {
    fs.renameSync(path.join(site, "data/gpu/A12.json.bak"), path.join(site, "data/gpu/A12.json"));
  }
  await go("#gpus");
  await go("#A12");
  await until(() => d.querySelectorAll(".gg button[data-host]").length === 72, "A12 grid after the file returns");
  ok(d.querySelectorAll(".gg button[data-host]").length === 72, "the rack loads once the file is back (no stale failure cached)");

  // ---- deep link and back
  const dom2 = new JSDOM(html, opts);
  await sleep(50);
  ok(dom2.window.document.getElementById("main").textContent.includes("GPU telemetry"), "a fresh load without a hash opens the overview");
  const dom3 = new JSDOM(html, { ...opts, url: "https://example.test/telemetry/#fields" });
  await sleep(50);
  ok(dom3.window.document.getElementById("main").textContent.includes("Field reference"), "a deep link to #fields opens it");
  ok(!/<\/script/i.test(d.getElementById("data").textContent), "inline data cannot close the script tag");
  ok(errors.length === 0, "still no script errors " + errors.join(";"));
  w.close(); dom2.window.close(); dom3.window.close();
})().catch(e => { console.log("FAIL: test crashed", e && e.stack || e); process.exitCode = 1; });
