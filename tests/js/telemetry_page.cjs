// node tests/js/telemetry_page.cjs <site>/index.html <site>
// <site> is the folder scripts/render_telemetry.py write_site() wrote: index.html plus data/ (racks.json, gpu/, windows/, cdu/, cdu_minutes/,
// power/, power/windows/, power_minutes/).
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

  // ---- CDUs: the device-family selector and the overview
  const C = D.cdu;
  const noBad = what => ok(!/\bundefined\b|\bNaN\b/.test(t()), `no undefined/NaN text in ${what}`);
  const fam = () => [...d.querySelectorAll("#tree ul.fam > li")].map(li => li.textContent.trim());
  ok(fam()[0].startsWith("GPUs") && fam()[1].startsWith("CDUs") && fam()[2].startsWith("Power") && C.planned.every(p => fam().some(x => x.startsWith(p) && x.includes("planned"))), "family selector lists GPUs, CDUs, Power and the greyed planned families: " + fam().join(" | "));
  ok(d.querySelectorAll("#tree ul.fam a").length === 3 && d.querySelectorAll("#tree ul.fam .planned").length === C.planned.length && !d.querySelector("#tree ul.fam .planned a"), "planned families are not links");
  ok(!d.querySelector('#tree .famsec[data-fam="gpu"]').classList.contains("off") && d.querySelector('#tree .famsec[data-fam="cdu"]').classList.contains("off"), "on a GPU view the GPU section shows and the CDU section is hidden");
  ok([...d.querySelectorAll("#tree .planned")].some(x => x.textContent.includes("CDU-C1")) && !d.querySelector('#tree a[href="#CDU-C1"]'), "Hall C CDUs are greyed, not links");
  await go("#cdus");
  await until(() => d.querySelectorAll(".ctile .spark svg").length === C.cdus.length, "CDU sparklines");
  ok(t().includes("CDU telemetry") && d.querySelectorAll(".ctile").length === 8 && d.querySelectorAll(".ctile .spark svg").length === 8, "#cdus renders 8 CDU tiles with sparklines");
  ok(t().includes("Hall C (800 VDC pilot)") && t().includes("planned") && t().includes("CDU-C1, CDU-C2, CDU-C3"), "Hall C shown as planned, not in service");
  ok(t().includes("N+1 headroom") && t().includes(`${(100 * (1 - C.halls["HALL-A"].heat_peak_kw / C.halls["HALL-A"].capacity_n_kw)).toFixed(1)}%`), "Hall A N+1 headroom from the page data");
  ok(d.querySelector('a[href="../tickets/#WO-41031"]') && d.querySelector('a[href="../tickets/#INC3100714"]') && d.querySelector('a[href="#A07"]'), "overview events link records to the Incident Portal and the rack outage to its rack");
  ok(d.querySelector('#tree a[data-fam="cdu"]').classList.contains("on") && d.querySelector('#tree a[href="#cdus"]:not([data-fam])').classList.contains("on") && d.querySelector('#tree .famsec[data-fam="gpu"]').classList.contains("off"), "tree highlights the CDU family and overview, hides the GPU section");
  noBad("#cdus");

  // ---- one CDU
  await go("#CDU-B3");
  await until(() => d.querySelectorAll("#cc svg[data-ch]").length === 8, "CDU-B3 charts");
  ok(d.querySelectorAll("#cc svg[data-ch]").length === 8 && t().includes("Pump speed") && t().includes("Filter differential pressure") && t().includes("facility water supply"), "#CDU-B3 renders the eight hourly charts");
  ok(t().includes(C.cdus.find(c => c.id === "CDU-B3").uri) && d.querySelector('a[href="../devices/#CDU-B3"]') && d.querySelector('a[href="#B17"]'), "header: URI, device card, racks served link to the rack views");
  ok(d.querySelector('a[href="../tickets/#WO-41031"]') && d.querySelector('a[href="../tickets/#PM-0010"]') && d.querySelector('a[href="../tickets/#MOP-303"]'), "CDU-B3 events link WO-41031 and PM-0010");
  ok(d.querySelectorAll('#cc svg[data-ch] rect[fill="#f8d9d5"]').length === 8 && d.querySelectorAll('#cc svg[data-ch] rect[fill="#e3e7ec"]').length === 8, "the pump failure and the PM are banded on every chart");
  const b3pump = C.events.find(e => e.cdu === "CDU-B3" && e.kind === "pump");
  const mOf = iso => Math.floor((Date.parse(iso) - Date.parse(D.window.start)) / 60000);
  ok(d.querySelector(`a.b[href="#CDU-B3/${Math.max(0, mOf(b3pump.t) - 10)}"]`), "a Minute detail link ten minutes before the pump failure");
  ok(d.querySelector('#tree a[href="#CDU-B3"]').classList.contains("on"), "tree highlights the CDU");
  noBad("#CDU-B3");
  await go("#CDU-A1");
  await until(() => d.querySelectorAll("#cc svg[data-ch]").length === 8, "CDU-A1 charts");
  ok(t().includes("Rack A07 lost input power") && d.querySelectorAll('#cc svg[data-ch] rect[fill="#dde8fb"]').length === 8, "a Hall A CDU lists the hall's rack outage and bands it");

  // ---- minute detail: the pump 2 failure on CDU-A2
  const crit = C.redfish_states.find(s => s.cdu === "CDU-A2" && s.property === "Status.Health" && s.value === "Critical" && s.resource.endsWith("/Pumps/2"));
  await go(`#CDU-A2/${crit.m}`);
  await until(() => d.getElementById("cm-json") && d.getElementById("cm-json").textContent.includes("CoolingUnit"), "CDU-A2 minute view");
  ok(fetches.includes("data/cdu_minutes/CDU-A2.json"), "the minute file is fetched only when the minute view opens");
  const blocks = () => Object.fromEntries(d.getElementById("cm-json").textContent.split(/\n(?=# GET )/).map(b => { const name = /\(([^,]+),/.exec(b)[1]; return [name, JSON.parse(b.slice(b.indexOf("\n") + 1))]; }));
  let J = blocks();
  ok(Object.keys(J).length === 11 && J["Pumps/2"].Status.Health === "Critical" && J["CoolingUnit"].PumpRedundancy[0].Status.Health === "Warning" && J["CoolingUnit"].Status.HealthRollup === "Warning", "at the failure minute Pumps/2 is Critical and PumpRedundancy Warning");
  ok(J["CoolingUnit"].EquipmentType === "CDU" && J["CoolingUnit"].CoolingCapacityWatts === C.unit.capacity_kw * 1000 && J["CoolingUnit"].Coolant.AdditivePercent === 25, "CoolingUnit resource shape");
  const raw = JSON.parse(fs.readFileSync(path.join(site, "data/cdu_minutes/CDU-A2.json"), "utf8"));
  const dec = (k, m) => { let s = 0; for (let i = 0; i <= m; i++) s += raw.fields[k][i]; return s / C.fields.find(f => f.key === k).scale; };
  ok(J["SecondaryCoolantConnectors/1"].SupplyTemperatureCelsius.Reading === dec("sec_supply_c", crit.m) && J["SecondaryCoolantConnectors/1"].HeatRemovedkW.Reading === dec("heat_kw", crit.m)
     && J["Pumps/1"].PumpSpeedPercent.Reading === dec("pump1_pct", crit.m) && J["Reservoirs/1"].FluidLevelPercent.Reading === dec("reservoir_pct", crit.m)
     && J["Sensors"].Members.find(x => x["@odata.id"].endsWith("/Sensors/FilterDP")).Reading === dec("filter_dp_kpa", crit.m) && J["EnvironmentMetrics"].PowerWatts.Reading === dec("power_w", crit.m), "minute JSON readings equal the decoded file values");
  let run1 = 0; for (let i = 0; i <= crit.m; i++) if (dec("pump1_pct", i) > 0) run1++;
  ok(J["Pumps/1"].ServiceHours === Math.round((raw.service_hours_start[0] + run1 / 60) * 10) / 10 && J["Filters/1"].RatedServiceHours === C.unit.rated_service_hours && J["Filters/1"].ServicedDate === raw.filter_serviced[0], "pump service hours and filter service record");
  ok(t().includes(new Date(Date.parse(D.window.start) + crit.m * 60000).toISOString().slice(11, 16) + " UTC") && d.querySelectorAll("#cm-ch svg[data-ch]").length === 3 && d.querySelectorAll("#cm-tbl tbody tr").length === C.fields.length, "minute time, three mini charts, every field in the readings table");
  d.querySelector('#cm-res button[data-r="Pumps/2"]').click();
  await sleep(20);
  ok(d.getElementById("cm-json").textContent.split("# GET ").length === 2 && d.getElementById("cm-json").textContent.includes("/Pumps/2"), "a resource button narrows the JSON to that resource");
  d.querySelector('#cm-res button[data-r="all"]').click();
  await sleep(20);
  d.querySelector('#cm-step button[data-s="-60"]').click();
  await sleep(20);
  ok(w.location.hash === `#CDU-A2/${crit.m - 60}` && d.getElementById("cmi").value === String(crit.m - 60) && blocks()["Pumps/2"].Status.Health === "OK", "stepping back an hour updates the address and the state is OK before the failure");
  d.getElementById("cmi").value = "0";
  d.getElementById("cmi").dispatchEvent(new w.Event("change", { bubbles: true }));
  await sleep(20);
  J = blocks();
  ok(J["Pumps/2"].Status.Health === "OK" && J["CoolingUnit"].PumpRedundancy[0].Status.Health === "OK" && J["CoolingUnit"].Status.HealthRollup === "OK" && J["LeakDetection/LeakDetectors/1"].DetectorState === "OK" && J["Pumps/2"].Status.State === "Enabled", "at minute 0 everything is OK");
  ok(J["Pumps/1"].ServiceHours === Math.round((raw.service_hours_start[0] + (dec("pump1_pct", 0) > 0 ? 1 : 0) / 60) * 10) / 10, "service hours at minute 0 start from the record");
  d.getElementById("ccsv").click();
  await sleep(10);
  ok(d.getElementById("ccsv-note").textContent.includes("61 rows"), "CSV of the ±60 window at minute 0 has 61 rows (" + d.getElementById("ccsv-note").textContent + ")");
  noBad("#CDU-A2 minute view");
  await go("#CDU-A4/999999");
  await until(() => d.getElementById("cm-json") && d.getElementById("cm-json").textContent.includes("CoolingUnit"), "CDU-A4 minute view");
  ok(d.getElementById("cmi").value === String(raw.minutes - 1), "an out-of-range minute is clamped to the last minute");

  // ---- CDU reference pages
  await go("#cdu-fields");
  ok(C.fields.every(f => t().includes(f.property) && t().includes(f.bacnet)) && t().includes("illustrative") && t().includes("not CoolIT's or any vendor's map"), "#cdu-fields lists every field and the illustrative-points note");
  ok(C.sources.every(s => d.querySelector(`a[href="${s.url}"]`)) && t().includes("DetectorState") && t().includes("Row leak rope"), "sources, states and detectors");
  await go("#cdu-agreements");
  ok(d.querySelectorAll("tbody tr").length === 9 && C.agreements.every(a => t().includes(a.title)) && t().includes(`${C.agreements.reduce((a, c) => a + c.checked - c.misses, 0).toLocaleString("en-US")} of`), "#cdu-agreements shows the 9 checks");
  noBad("#cdu-agreements");

  // ---- the rack view links to its CDU
  await go("#A01");
  await until(() => d.querySelectorAll("#rc svg").length === 3, "A01 charts");
  ok(d.querySelector('#main a[href="#CDU-A1"]') && t().includes("Cooled by CDU-A1") && t().includes("CDU-A1 secondary supply"), "rack A01 links to CDU-A1 and labels the supply line");
  await go("#CDU-C1");
  ok(t().includes("CDU telemetry"), "an unknown CDU falls back to the CDU overview");
  fs.renameSync(path.join(site, "data/cdu_minutes/CDU-B1.json"), path.join(site, "data/cdu_minutes/CDU-B1.json.bak"));
  try {
    await go("#CDU-B1/5");
    await until(() => t().includes("Could not load"), "CDU error message");
    ok(t().includes("Could not load data/cdu_minutes/CDU-B1.json") && errors.length === 0, "a missing CDU minute file shows a message, not an exception");
  } finally {
    fs.renameSync(path.join(site, "data/cdu_minutes/CDU-B1.json.bak"), path.join(site, "data/cdu_minutes/CDU-B1.json"));
  }
  await go("#cdus");
  await go("#CDU-B1/5");
  await until(() => d.getElementById("cm-json") && d.getElementById("cm-json").textContent.includes("CoolingUnit"), "CDU-B1 minute view after the file returns");
  ok(d.getElementById("cm-json") && d.getElementById("cm-json").textContent.includes("CoolingUnit"), "the minute view loads once the file is back (no stale failure cached)");

  // ---- power
  const P = D.power;
  await go("#power");
  await until(() => d.querySelectorAll(".ctile .spark svg").length === P.ups.length, "UPS sparklines");
  ok(t().includes("Power telemetry") && d.querySelector("#main svg a[href='#UPS-A1']") && d.querySelectorAll(".ctile").length === P.ups.length + P.gens.length, "power overview: one-line diagram and a tile per UPS and generator");
  ok(d.querySelectorAll(".ctile .spark svg").length === P.ups.length, "every UPS tile draws its load sparkline");
  const pAgree = P.agreements.reduce((a, c) => a + c.checked - c.misses, 0);
  ok(t().includes(`${pAgree.toLocaleString("en-US")} of`) && P.agreements.every(c => c.misses === 0), "power agreements on the overview, none missed");
  ok(t().includes("below 30%") && d.querySelector('#main a[href="#GEN-4"]'), "GEN-4's monthly test below 30% of rated is flagged");
  ok(d.querySelector('#tree a[href="#power"]').classList.contains("on"), "tree highlights Power");
  noBad("#power");
  await go("#UPS-A1");
  await until(() => d.querySelectorAll("#pc svg").length === 4, "UPS-A1 charts");
  ok(d.querySelectorAll("#pc svg").length === 4 && t().includes("Busway runs fed") && t().includes("Galaxy VX"), "UPS-A1: four charts and its busway runs");
  ok(d.querySelector('#main a[href="#BW-A-R1-PG-A1-A"]') && t().includes("WO-41009"), "UPS-A1 links its runs and the outage work order");
  noBad("#UPS-A1");
  const byp = P.events.find(e => e.device === "UPS-A1" && e.kind === "bypass"), mo = mOf(byp.t) + 5;
  await go(`#UPS-A1/${mo}`);
  await until(() => d.getElementById("pm-raw-out") && d.getElementById("pm-raw-out").textContent.includes("upsOutputSource"), "UPS minute view");
  const praw = () => d.getElementById("pm-raw-out").textContent;
  ok(praw().includes("upsOutputSource: bypass") && /1\.3\.6\.1\.4\.1\.318\.1\.1\.1\.4\.1\.1\.0 = INTEGER: 9/.test(praw()), "five minutes into the maintenance bypass the SNMP walk reads bypass (PowerNet 9 switchedBypass)");
  ok(d.querySelectorAll("#pm-ch svg").length === 3 && d.querySelectorAll("#pm-tbl tbody tr").length === P.fields.ups.length, "minute view: three charts and every point");
  d.querySelector('#pm-step button[data-s="-10"]').click();
  await sleep(20);
  ok(w.location.hash === `#UPS-A1/${mo - 10}` && praw().includes("upsOutputSource: normal"), "ten minutes earlier the UPS is on double conversion");
  const out = P.outages[0];
  await go(`#UPS-A1/${mOf(out.trip)}`);
  await until(() => /33\.1\.2\.6\.0 = INTEGER: -\d/.test(praw()), "outage minute");
  ok(/33\.1\.2\.6\.0 = INTEGER: -\d/.test(praw()) && t().includes("utility"), "in the outage minute the battery current is negative (discharging)");
  d.querySelector('#pm-raw button[data-r="modbus"]').click();
  await sleep(20);
  ok(praw().includes("990-5915F") && praw().includes("45379"), "the Galaxy VX Modbus read lists its registers");
  d.getElementById("pcsv").click();
  await sleep(10);
  ok(d.getElementById("pcsv-note").textContent.includes("121 rows"), "CSV of the ±60 window has 121 rows (" + d.getElementById("pcsv-note").textContent + ")");
  noBad("#UPS-A1 minute view");
  const g4 = P.gens.find(g => g.id === "GEN-4").runs.find(r => r.kind === "test");
  await go(`#GEN-4/${mOf(g4.t) + 10}`);
  await until(() => d.getElementById("pm-raw-out") && d.getElementById("pm-raw-out").textContent.includes("EMCP"), "GEN-4 minute view");
  ok(praw().includes("function 03") && praw().includes("Running"), "GEN-4 ten minutes into its test: Modbus holding registers, Running");
  ok(t().includes("30% of rated") && t().includes("L-003"), "GEN-4 minute view shows the NFPA 110 line and the Landlord finding");
  noBad("#GEN-4 minute view");
  await go("#GEN-4");
  await until(() => d.querySelectorAll("#pc svg").length >= 2, "GEN-4 charts");
  ok(t().includes("L-003") && t().includes("Monthly loaded exercise"), "GEN-4 shows its test run and the finding");
  await go("#BW-A-R1-PG-A2-A");
  await until(() => d.querySelectorAll("#pc svg").length === 4 && d.querySelector("#ptap table"), "run charts and tap-off table");
  ok(d.querySelectorAll("#ptap tbody tr").length === P.runs.find(r => r.id === "BW-A-R1-PG-A2-A").tapoffs.length && t().includes("Starline"), "busway run: four charts and a row per tap-off");
  const wb = d.querySelector("#pw-btns button");
  ok(wb, "the run has a one-minute window around its events");
  wb.click();
  await until(() => d.getElementById("pw-raw") && d.getElementById("pw-raw").textContent.includes("35774"), "busway window raw read");
  ok(d.getElementById("pw-raw").textContent.includes("snmpget") && d.querySelectorAll("#pw svg").length === 3, "the window charts the run and shows the CPM read");
  noBad("#BW-A-R1-PG-A2-A");
  await go("#TO-A07-A");
  await until(() => d.querySelectorAll("#pc svg").length === 3, "tap-off charts");
  ok(t().includes("went dark") && d.querySelector('#main a[href="#TO-A07-B"]'), "TO-A07-A: rack A07 lost both feeds, linked to its partner tap-off");
  await go("#A07");
  await until(() => d.querySelector('#main a[href="#TO-A07-A"]'), "A07 power feeds");
  ok(d.querySelector('#main a[href="#TO-A07-A"]') && d.querySelector('#main a[href="#TO-A07-B"]'), "the rack view lists its A and B tap-offs");
  await go("#power-fields");
  ok(["ups", "busway", "tapoff", "generator"].every(k => P.fields[k].every(f => t().includes(f.name))) && P.sources.every(s => d.querySelector(`a[href="${s.url}"]`)), "#power-fields lists every point and source");
  await go("#power-agreements");
  ok(d.querySelectorAll("tbody tr").length === P.agreements.length && P.agreements.every(a => t().includes(a.title)), "#power-agreements shows every check");
  fs.renameSync(path.join(site, "data/power_minutes/UPS-B2.json"), path.join(site, "data/power_minutes/UPS-B2.json.bak"));
  try {
    await go("#UPS-B2/5");
    await until(() => t().includes("Could not load"), "power error message");
    ok(t().includes("Could not load data/power_minutes/UPS-B2.json") && errors.length === 0, "a missing UPS minute file shows a message, not an exception");
  } finally {
    fs.renameSync(path.join(site, "data/power_minutes/UPS-B2.json.bak"), path.join(site, "data/power_minutes/UPS-B2.json"));
  }
  await go("#power");
  await go("#UPS-B2/5");
  await until(() => d.getElementById("pm-raw-out") && d.getElementById("pm-raw-out").textContent.includes("UPS-B2"), "UPS-B2 after the file returns");
  ok(d.getElementById("pm-raw-out") && praw().includes("UPS-B2"), "the UPS minute view loads once the file is back");

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
