// node tests/js/telemetry_page.cjs <site>/index.html <site>
// <site> is the folder scripts/render_telemetry.py write_site() wrote: index.html plus data/ (racks.json, gpu/, windows/, cdu/, cdu_minutes/,
// power/, power/windows/, power_minutes/, network/, network/windows/, mechanical/, mechanical/windows/, mechanical_minutes/, mgmt/, mgmt/windows/, storage/).
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

  // ---- site health (the landing page)
  ok(errors.length === 0, "no script errors on load " + errors.join(";"));
  const S = D.site, H = S.hours;
  ok(t().includes("Site health") && d.querySelector('#tree a[href="#site"]').classList.contains("on"), "the tab opens on Site health");
  ok(d.getElementById("shr").value === String(H - 1) && d.getElementById("sh-lab").textContent.includes("Sep 27, 23:00 to 00:00 UTC"), "the clock starts at the month's last hour");
  ok(d.querySelectorAll("#sh-red a.shchip").length === S.groups.length, "a chip for every redundancy group");
  ok(d.querySelectorAll("#sh-fam a.shtile").length === 7, "a tile per device family");
  ok(d.querySelectorAll("#sh-map .shrack").length === 64 && d.querySelectorAll("#sh-map .shcdu").length === 8, "hall map: 64 racks and 8 CDUs");
  ok(t().includes("Hall C (800 VDC pilot)") && d.querySelector('#sh-map a[href="../deployments/#hallc"]'), "Hall C shown as planned, linked to readiness");
  ok(d.querySelector('a[href="../alarms/"]'), "links to the Alarm Board for alarms");
  // the utility outage hour: site on generators, every UPS on battery for seconds, generators 7 running
  await go("#site/597");
  ok(d.getElementById("shr").value === "597", "the hash sets the hour");
  const util = [...d.querySelectorAll("#sh-red a.shchip")].find(a => a.title.startsWith("Utility feeds"));
  ok(util && util.classList.contains("bad") && util.textContent.includes("0 of 2"), "utility feeds 0 of 2, red, during the outage");
  ok(t().includes("site on generators") && t().includes("UPS-A1: on battery 11 s"), "conditions list the outage and the UPSs on battery");
  const pw = [...d.querySelectorAll("#sh-fam a.shtile")].find(a => a.getAttribute("href") === "#power");
  ok(pw.classList.contains("bad") && pw.textContent.includes("Generators running7"), "power tile lost, with 7 generators running");
  // step and jump
  d.querySelector('#sh-step button[data-s="1"]').click();
  ok(d.getElementById("shr").value === "598" && w.location.hash === "#site/598", "+1 hour moves the clock and the link");
  ok(!t().includes("site on generators"), "the next hour has utility back");
  d.querySelector('#sh-step button[data-j="-1"]').click();
  ok(d.getElementById("shr").value === "597", "previous change goes back to the outage hour");
  // A07 outage: both feeds lost, the rack red on the hall map and linked at that hour
  await go("#site/377");
  const a07r = d.querySelector('#sh-map a.shrack[href="#A07/377"]');
  ok(a07r && a07r.classList.contains("bad") && a07r.title.includes("no GPUs reporting") && a07r.title.includes("both power feeds lost"), "A07 red on the hall map during its outage");
  const feeds = [...d.querySelectorAll("#sh-red a.shchip")].find(a => a.title.startsWith("Rack feeds, Hall A"));
  ok(feeds && feeds.classList.contains("bad") && feeds.textContent.includes("31 of 32"), "Hall A rack feeds 31 of 32, red");
  // a Hall B rack before it is installed, and during commissioning
  await go("#site/130");
  ok(d.querySelector("#sh-map span.shrack.off") && [...d.querySelectorAll("#sh-map span.shrack.off")].some(x => x.textContent === "B32"), "uninstalled Hall B racks are grey");
  ok(d.querySelector("#sh-map a.shrack.com"), "a commissioning rack is hatched");
  // the month strip: a click moves the clock
  const svg = d.querySelector("#sh-strip svg[data-strip]");
  ok(svg && svg.querySelectorAll("rect").length > 20 && svg.querySelector("line.cur"), "month strip drawn with a cursor");
  ok(t().includes("Full redundancy all month: Generators"), "systems that held all month are listed");
  ok(S.agreements.every(a => a.misses === 0) && d.querySelectorAll("#main table tbody tr td .tag.ok").length >= S.agreements.length, "every agreement holds and is shown");
  ok(!/[<>]/.test([...d.querySelectorAll("#sh-cond td")].map(x => x.textContent).join("")), "condition text is escaped");

  // ---- overview
  await go("#gpus");
  ok(errors.length === 0, "no script errors on the GPU overview " + errors.join(";"));
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
  ok(fam()[0].startsWith("Site health") && fam()[1].startsWith("GPUs") && fam()[2].startsWith("CDUs") && fam()[3].startsWith("Power") && fam()[4].startsWith("Network") && fam()[5].startsWith("Mechanical") && fam()[6].startsWith("Storage") && C.planned.every(p => fam().some(x => x.startsWith(p) && x.includes("planned"))), "family selector lists Site health, GPUs, CDUs, Power, Network, Mechanical, Storage and any greyed planned families: " + fam().join(" | "));
  ok(d.querySelectorAll("#tree ul.fam a").length === 7 && d.querySelectorAll("#tree ul.fam .planned").length === C.planned.length && !d.querySelector("#tree ul.fam .planned a"), "planned families are not links");
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

  // ---- network
  const N = D.network;
  await go("#network");
  ok(t().includes("Network telemetry") && d.querySelectorAll(".fm a").length === N.leaves.length
     && d.querySelectorAll(".fm a i.x").length === N.leaves.filter(x => x.flagged.length).length, "network overview: a fabric-map cell per leaf, a red dot per leaf with a faulty link");
  const nAgree = N.agreements.reduce((a, c) => a + c.checked - c.misses, 0);
  ok(t().includes(`${nAgree.toLocaleString("en-US")} of`) && N.agreements.length === 9 && N.agreements.every(c => c.misses === 0), "network agreements on the overview, none missed");
  ok(d.querySelector('#main a[href="../tickets/#INC3100136"]') && t().includes("errors continued") && t().includes("F-011") && t().includes("Rack A07 lost input power"), "events: the wrong-end replacement, its finding, and the rack power loss");
  ok(d.querySelector('#tree a[data-fam="network"]').classList.contains("on") && !d.querySelector('#tree .famsec[data-fam="network"]').classList.contains("off")
     && d.querySelector('#tree .famsec[data-fam="power"]').classList.contains("off"), "tree highlights Network and shows only its section");
  const hb = N.halls["HALL-B"];
  ok(hb.cabled_start < hb.cabled_end && N.events.filter(e => e.kind === "cabled").length === hb.racks && d.querySelector('#main a[href="../deployments/#rack/B07"]'), "Hall B: links cabled during the month, one cabling event per rack linked to its deployment record");
  noBad("#network");
  await go("#leaf-a07-r1");
  await until(() => d.querySelectorAll("#lp tbody tr").length === 36 && d.querySelector("#lc svg"), "leaf ports");
  ok(d.querySelectorAll("#lp tbody tr").length === 36 && d.querySelector('#lp a[href="#leaf-a07-r1:swp18"]').parentElement.textContent.includes("record"), "leaf: 36 ports, swp18 marked with a record");
  ok(d.querySelector('#tree a[href="#leaf-a07-r1"]').classList.contains("on"), "tree highlights the leaf");
  d.getElementById("lcsv").click();
  await until(() => /rows/.test(d.getElementById("lcsv-note").textContent), "leaf CSV");
  ok(d.getElementById("lcsv-note").textContent.startsWith(`${36 * D.network.hours} rows`), "leaf CSV: every port, every hour");
  noBad("#leaf-a07-r1");
  const ev = N.events.find(e => e.device === "leaf-a07-r1:swp18");
  const win = N.windows.find(w => w.device === ev.device && Date.parse(w.from) <= Date.parse(ev.t) && Date.parse(ev.t) < Date.parse(w.from) + w.minutes * 60000);
  const W = JSON.parse(fs.readFileSync(path.join(site, "data/network", win.file), "utf8"));
  await go(`#leaf-a07-r1:swp18/${ev.m}`);
  await until(() => d.getElementById("nw-pre") && d.getElementById("nw-pre").textContent.includes("PortXmitDataExtended"), "port minute detail");
  const pre = () => d.getElementById("nw-pre").textContent, i = ev.m - W.m0;
  ok(d.querySelector(".finding") && t().includes("F-011") && d.querySelectorAll("#pc svg[data-ch]").length === 6, "port: the finding, and six hourly charts");
  ok(pre().includes(`SymbolErrorCounterExtended{`) && pre().includes(` ${W.fields.tx[i]}`) && W.fields.up[i] === 0, "UFM scrape at the drop minute reads the window's counters; the link is down then");
  d.querySelector('#nw-raw button[data-r="mlx"]').click();
  ok(/Physical state\s+: Polling/.test(pre()), "mlxlink shows the link polling while it is down");
  d.querySelector('#nw-raw button[data-r="perf"]').click();
  ok(pre().includes("SymbolErrorCounter:") && pre().includes(`LinkDownedCounter:`), "perfquery shows the IBTA counters");
  d.querySelector('#nw-raw button[data-r="host"]').click();
  ok(pre().includes(`node_infiniband_port_data_received_bytes_total{device="mlx5_1",port="1"} ${W.fields.tx[i] * 4}`), "the tray's node_exporter receives exactly what the switch port sent (4-octet words x 4)");
  d.getElementById("nwcsv").click();
  ok(d.getElementById("nwcsv-note").textContent.startsWith(`${W.minutes} rows`), "port window CSV: one row a minute");
  noBad("#leaf-a07-r1:swp18 minute view");
  await go("#nvlink-A15");
  await until(() => d.querySelectorAll("#nvc svg[data-ch]").length === 4, "NVLink charts");
  ok(d.querySelectorAll("#nvc tbody tr").length === 9 && d.querySelector('#nvc a[href="#a15-nvsw3"]').parentElement.textContent.includes("record"), "NVLink rack: nine trays, a15-nvsw3 marked");
  await go("#a15-nvsw3");
  await until(() => d.getElementById("nv-pre"), "NVLink tray window");
  ok(d.getElementById("nv-pre").textContent.includes("nmx-telemetry") && t().includes("the rack's other trays together") && d.querySelectorAll("#nv svg[data-ch]").length === 2, "the failed tray's window opens with the NMX-T read and the other trays' traffic");
  noBad("#a15-nvsw3");
  await go("#A07");
  const a07Leaves = N.leaves.filter(x => x.racks.includes("A07")).map(x => x.id);
  ok(a07Leaves.length === 4 && a07Leaves.every(l => d.querySelector(`#main a[href="#${l}"]`)) && d.querySelector('#main a[href="#nvlink-A07"]'), "a GPU rack links its four leaves and its NVLink trays");
  await go("#network-fields");
  ok(["port", "chassis", "nvlink"].every(k => N.fields[k].every(f => t().includes(f.name))) && N.sources.every(s => d.querySelector(`a[href="${s.url}"]`)), "#network-fields lists every field and source");
  await go("#network-agreements");
  ok(d.querySelectorAll("tbody tr").length === N.agreements.length && N.agreements.every(a => t().includes(a.title)), "#network-agreements shows every check");
  fs.renameSync(path.join(site, "data/network/leaf-a02-r0.json"), path.join(site, "data/network/leaf-a02-r0.json.bak"));
  try {
    await go("#leaf-a02-r0");
    await until(() => t().includes("Could not load"), "network error message");
    ok(t().includes("Could not load data/network/leaf-a02-r0.json") && errors.length === 0, "a missing leaf file shows a message, not an exception");
  } finally {
    fs.renameSync(path.join(site, "data/network/leaf-a02-r0.json.bak"), path.join(site, "data/network/leaf-a02-r0.json"));
  }

  // ---- mechanical
  const Mx = D.mechanical;
  await go("#mechanical");
  await until(() => d.querySelectorAll(".ctile .spark svg").length === Mx.air.length, "air unit sparklines");
  ok(t().includes("Mechanical telemetry") && d.querySelectorAll(".ctile").length === Mx.chillers.length + Mx.pumps.length + 1 + Mx.air.length, "mechanical overview: a tile per chiller, pump, the loop, and each air unit");
  ok(d.querySelectorAll('#main svg a[href^="#CH-"]').length === Mx.chillers.length && d.querySelector('#main svg rect[fill="#d64545"]') && d.querySelector('#main svg rect[fill="#7a4b00"]'), "plant map: a row per chiller, the trips in red, the lockouts marked");
  const mAgree = Mx.agreements.reduce((a, c) => a + c.checked - c.misses, 0);
  ok(t().includes(`${mAgree.toLocaleString("en-US")} of`) && Mx.agreements.every(c => c.misses === 0), "mechanical agreements on the overview, none missed");
  ok(t().includes("WO-41035") && t().includes("PM-0015") && t().includes("EN-F2") && t().includes("L-005") && t().includes("hid no excursion"), "events carry the work orders, PM tasks, and findings");
  ok(t().includes("Hall C") && t().includes("not in service".slice(0, 3)) && d.querySelector('#tree a[href="#mechanical"]').classList.contains("on"), "Hall C shown as planned; tree highlights Mechanical");
  noBad("#mechanical");
  await go("#CH-03");
  await until(() => d.querySelectorAll("#mc svg").length === 4, "CH-03 charts");
  ok(d.querySelectorAll("#mc svg").length === 4 && t().includes("143.0 h") && t().includes("EN-F2") && d.querySelector('#main a[href="../devices/#CH-03"]'), "CH-03: four charts, the 143-hour lockout, its finding, and its device card");
  noBad("#CH-03");
  const trip = Mx.events.find(e => e.device === "CH-08" && e.kind === "trip");
  await go(`#CH-08/${trip.m}`);
  await until(() => d.getElementById("mm-raw") && d.getElementById("mm-raw").textContent.includes("present-value"), "CH-08 minute view");
  const mraw = () => d.getElementById("mm-raw").textContent;
  ok(t().includes("Alarm Off (7)") && t().includes("ALARM (4)") && /binary-value #35[\s\S]*?present-value: active[\s\S]*?status-flags: \{true,false,false,false\}/.test(mraw()), "CH-08 at its trip: Alarm Off, compressor ALARM, BV 35 active and in alarm");
  ok(d.querySelectorAll("#mm-ch svg").length === 3 && t().includes("Download CSV"), "minute view: three charts and the CSV button");
  d.querySelector('#mm-step button[data-s="-60"]').click();
  await sleep(30);
  ok(w.location.hash === `#CH-08/${trip.m - 60}` && (t().includes("Local On (0)") || t().includes("Standby (12)")), "stepping back an hour updates the hash and the readings");
  const hold = Mx.events.find(e => e.device === "CH-06" && e.kind === "hold");
  await go(`#CH-06/${hold.m + 30}`);
  await until(() => d.getElementById("mm-raw") && /priority-array: \{(Null,){7}inactive/.test(d.getElementById("mm-raw").textContent), "CH-06 priority array");
  ok(/priority-array: \{(Null,){7}inactive/.test(mraw()) && t().includes("BMS Off (14)") && /binary-value #1 [\s\S]*?status-flags: \{false,false,false,false\}/.test(mraw()), "CH-06 under its BMS hold: Off at priority 8, BMS Off, and OVERRIDDEN stays false");
  const inh = Mx.events.find(e => e.device === "TW-B2" && e.kind === "inhibit");
  await go(`#TW-B2/${inh.m + 60}`);
  await until(() => d.getElementById("mm-raw") && d.getElementById("mm-raw").textContent.includes("event-algorithm-inhibit"), "TW-B2 minute view");
  ok(mraw().includes("event-algorithm-inhibit: TRUE") && t().includes("High supply temperature (Event_Algorithm_Inhibit)"), "TW-B2 during its inhibit: Event_Algorithm_Inhibit TRUE");
  noBad("#TW-B2 minute");
  const fan = Mx.events.find(e => e.device === "TW-A4" && e.kind === "fan");
  await go(`#TW-A4/${fan.m + 5}`);
  await until(() => d.getElementById("mm-tbl") && d.getElementById("mm-tbl").textContent.includes("Failed fan"), "TW-A4 minute view");
  const failed = [...d.querySelectorAll("#mm-tbl tr")].find(r => r.textContent.startsWith("Failed fan")), running = [...d.querySelectorAll("#mm-tbl tr")].find(r => r.textContent.startsWith("Evaporator fans running"));
  ok(failed && failed.querySelector("td.n").textContent === "6" && running.querySelector("td.n").textContent === "5", "TW-A4 during its fan failure: fan 6 failed, five running");
  for (const id of ["FWP-1", "FW-LOOP", "CRAH-B1"]) {
    await go("#" + id);
    await until(() => d.querySelectorAll("#mc svg").length >= 3, id + " charts");
    ok(d.querySelectorAll("#mc svg").length >= 3, `${id}: its month charts`);
    noBad("#" + id);
  }
  await go("#mech-fields");
  ok(["chiller", "pump", "loop", "air"].every(k => Mx.objects[k].every(o => t().includes(o.name))) && Mx.sources.every(s => d.querySelector(`a[href="${s.url}"]`)) && t().includes("OVERRIDDEN"), "#mech-fields lists every object and source and explains priority writes");
  await go("#mech-agreements");
  ok(d.querySelectorAll("tbody tr").length === Mx.agreements.length && Mx.agreements.every(a => t().includes(a.title)), "#mech-agreements shows every check");
  fs.renameSync(path.join(site, "data/mechanical_minutes/CH-05.json"), path.join(site, "data/mechanical_minutes/CH-05.json.bak"));
  try {
    await go("#CH-05/100");
    await until(() => t().includes("Could not load"), "mechanical error message");
    ok(t().includes("Could not load data/mechanical_minutes/CH-05.json") && errors.length === 0, "a missing chiller minute file shows a message, not an exception");
  } finally {
    fs.renameSync(path.join(site, "data/mechanical_minutes/CH-05.json.bak"), path.join(site, "data/mechanical_minutes/CH-05.json"));
  }

  // ---- management network
  const Gx = D.mgmt, gmin = iso => Math.round((Date.parse(iso) - Date.parse(Gx.window.start)) / 60000);
  const gOut = Gx.findings.find(f => f.kind === "unticketed_outage"), swap = Gx.findings.find(f => f.kind === "console_swap");
  ok(Gx.findings.length === 4 && ["unticketed_outage", "validation_gap", "late_bmc", "console_swap"].every(k => Gx.findings.some(f => f.kind === k)), "four management findings, one of each kind");
  await go("#management");
  await until(() => d.querySelectorAll("#gm-ch svg").length === 2, "management charts");
  ok(t().includes("Management network telemetry") && d.querySelectorAll("#main .finding").length === 4 && d.querySelector('#tree a[href="#management"]').classList.contains("on"), "management overview: the four findings; tree highlights Management");
  ok(d.querySelectorAll('#main table a[href^="#mgmt-"]').length >= 64 && t().includes("Console sessions") && t().includes("does not match the label"), "a row per rack, the session log, and the mismatched prompt flagged");
  const gAgree = Gx.agreements.reduce((a, c) => a + c.checked - c.misses, 0);
  ok(t().includes(`${gAgree.toLocaleString("en-US")} of`) && Gx.agreements.every(c => c.misses === 0), "management agreements on the overview, none missed");
  noBad("#management");
  await go("#a27-mgmt1");
  await until(() => d.querySelectorAll("#gm-r svg").length === 4, "A27 management charts");
  ok(t().includes("Rack A27 management") && d.querySelectorAll("#gm-r svg").length === 4 && t().includes(gOut.title) && t().includes("swp49") && t().includes("con-a4"), "a27-mgmt1 opens rack A27: four charts, its finding, the port map with uplinks and console");
  noBad("#mgmt-A27");
  await go(`#mgmt-A27/${gmin(gOut.from) + 30}`);
  await until(() => d.getElementById("gm-raw") && d.getElementById("gm-raw").textContent.includes("GET /redfish/v1/"), "A27 minute detail");
  ok(d.getElementById("gm-raw").textContent.includes("Timeout: No Response from a27-mgmt1") && d.getElementById("gm-raw").textContent.includes("poll failed") && d.querySelectorAll("#gm-grid g[data-ep]").length === 35, "minute detail during the outage: 35 BMC rows, the switch silent, the poll failed");
  const gr = d.getElementById("gmm");
  gr.value = "0"; gr.dispatchEvent(new w.Event("input"));
  ok(d.getElementById("gm-raw").textContent.includes("200 OK") && d.getElementById("gm-raw").textContent.includes("ifOperStatus"), "before the outage the BMC answers and the switch reports its ports");
  noBad("#mgmt-A27 minute");
  await go("#con-b2");
  ok(t().includes(swap.title) && [...d.querySelectorAll("#main tbody tr")].some(tr => tr.textContent.includes("does not match")), "con-b2: the swap finding and the mismatched port");
  await go("#oob-agg-a1");
  ok(d.querySelectorAll("#main tbody tr").length === 64 && t().includes("a32-mgmt2"), "oob-agg-a1: a port per Hall A rack switch");
  await go("#mgmt-fields");
  ok(Gx.fields.every(f => t().includes(f.name)) && Gx.sources.every(s => d.querySelector(`a[href="${s.url}"]`)), "#mgmt-fields lists every field and source");
  await go("#mgmt-agreements");
  ok(d.querySelectorAll("tbody tr").length === Gx.agreements.length && Gx.agreements.every(a => t().includes(a.title)), "#mgmt-agreements shows every check");
  await go(`#site/${Math.floor(gmin(gOut.from) / 60) + 2}`);
  const mt = [...d.querySelectorAll("#sh-fam a.shtile")].find(a => a.getAttribute("href") === "#management");
  ok(mt && mt.classList.contains("warn") && mt.textContent.includes("a27-mgmt1 down"), "site health: the management tile degraded during the A27 switch outage");
  fs.renameSync(path.join(site, "data/mgmt/A05.json"), path.join(site, "data/mgmt/A05.json.bak"));
  try {
    await go("#mgmt-A05");
    await until(() => t().includes("Could not load"), "management error message");
    ok(t().includes("Could not load data/mgmt/A05.json") && errors.length === 0, "a missing rack management file shows a message, not an exception");
  } finally {
    fs.renameSync(path.join(site, "data/mgmt/A05.json.bak"), path.join(site, "data/mgmt/A05.json"));
  }

  // ---- storage and its fabric
  const Sx = D.storage, stall = Sx.findings.find(f => f.kind === "fabric_stall"), wrong = Sx.findings.find(f => f.kind === "wrong_bay");
  ok(Sx.findings.length === 4 && ["fabric_stall", "custody_gap", "closed_before_rebuild", "wrong_bay"].every(k => Sx.findings.some(f => f.kind === k)), "storage data carries the four findings");
  await go("#storage");
  ok(t().includes("Storage and storage fabric telemetry") && Sx.findings.filter(f => f.kind !== "fabric_stall").every(f => t().includes(f.title)) && d.querySelectorAll("#sg-ch svg").length === 4, "#storage: findings and a throughput and protection chart per cluster");
  ok(d.querySelector('#tree a[data-fam="storage"]').classList.contains("on") && !d.querySelector('#tree .famsec[data-fam="storage"]').classList.contains("off") && d.querySelector('#tree .famsec[data-fam="network"]').classList.contains("off"), "tree highlights Storage and shows only its section");
  ok([...d.querySelectorAll("#main a")].some(a => a.getAttribute("href") === "#storage-tickets") && ![...d.querySelectorAll("#main a")].some(a => /tickets\/#INC35/.test(a.getAttribute("href"))), "storage tickets link to the storage tickets view, not the Incident Portal");
  noBad("#storage");
  await go(`#${wrong.devices[0]}`);
  await until(() => d.querySelector("#sg-n svg"), "storage node bays");
  ok(t().includes(wrong.title) && d.querySelectorAll("#sg-n svg text").length >= 24 && t().includes(wrong.ticket_bay) && t().includes(wrong.changed_bay), "storage node: the wrong-bay finding, a row per bay, and both bays named");
  ok([...d.querySelectorAll("#sg-n tbody tr")].some(tr => tr.textContent.includes(wrong.changed_bay) && tr.textContent.includes("Removed")), "the bay whose serial changed lists its Redfish events");
  noBad("#storage node");
  await go("#storage");
  ok(!t().includes(stall.summary) && [...d.querySelectorAll("#main a")].some(a => a.getAttribute("href") === "#north-south"), "#storage leaves the fabric finding to Network, North-South");
  await go("#north-south");
  ok(t().includes("North-South traffic") && t().includes(stall.title) && d.querySelector(".dirbar a.on").getAttribute("href") === "#north-south" && d.querySelectorAll("#main a[href^='#eth-']").length >= Sx.switches.length, "#north-south: the fabric finding, every fabric switch, North-South marked");
  ok(d.querySelector('#tree a[data-fam="network"]').classList.contains("on") && d.querySelector('#tree a[href="#north-south"]').classList.contains("on") && d.querySelector('#tree .famsec[data-fam="network"] a[href="#management"]'), "the Network section holds the fabric and the management network");
  noBad("#north-south");
  await go("#network");
  ok(d.querySelector(".dirbar a.on").getAttribute("href") === "#network", "#network is East-West");
  await go(`#${stall.devices[0]}`);
  await until(() => d.querySelector("#sg-s svg"), "row leaf charts");
  ok(t().includes(stall.title) && t().includes("Compute tray ports") && t().includes("linkDown"), "row leaf: the stall finding, its tray ports, and its traps");
  noBad("#row leaf");
  const sp = Sx.switches.find(s => s.role === "spine");
  await go(`#${sp.id}`);
  await until(() => t().includes("Downlinks"), "spine view");
  ok(sp.peers.every(p => d.querySelector(`#main a[href="#${p}"]`)), "spine: links to every leaf it carries");
  await go("#STG-A1");
  ok(d.querySelectorAll("#main tbody tr").length === 8, "storage rack: its eight nodes");
  await go("#storage-tickets");
  ok(d.querySelectorAll("#main table")[0].querySelectorAll("tbody tr").length === Sx.tickets.length && d.querySelectorAll("#main table")[1].querySelectorAll("tbody tr").length === Sx.custody.length, "#storage-tickets: every ticket and every custody handover");
  await go("#storage-fields");
  ok(Sx.fields.every(f => t().includes(f.name)) && Sx.sources.every(s => d.querySelector(`a[href="${s.url}"]`)), "#storage-fields lists every field and source");
  await go("#storage-agreements");
  ok(d.querySelectorAll("tbody tr").length === Sx.agreements.length && Sx.agreements.every(a => t().includes(a.title)), "#storage-agreements shows every check");
  const ep = Sx.episodes.find(e => e.switch === stall.devices[0]);
  await go(`#site/${Math.floor((Date.parse(ep.from) - Date.parse(D.window.start)) / 3600000)}`);
  const stt = [...d.querySelectorAll("#sh-fam a.shtile")].find(a => a.getAttribute("href") === "#network");
  ok(stt && stt.classList.contains("warn") && stt.textContent.includes("flapping"), "site health: the network tile degraded while the storage fabric uplink flapped");
  fs.renameSync(path.join(site, "data/storage/stg-a1-n01.json"), path.join(site, "data/storage/stg-a1-n01.json.bak"));
  try {
    await go("#stg-a1-n01");
    await until(() => t().includes("Could not load"), "storage error message");
    ok(t().includes("Could not load data/storage/stg-a1-n01.json") && errors.length === 0, "a missing storage node file shows a message, not an exception");
  } finally {
    fs.renameSync(path.join(site, "data/storage/stg-a1-n01.json.bak"), path.join(site, "data/storage/stg-a1-n01.json"));
  }

  // ---- error state
  await go("#A99");
  ok(t().includes("Site health"), "an unknown rack falls back to Site health");
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
  ok(dom2.window.document.getElementById("main").textContent.includes("Site health"), "a fresh load without a hash opens Site health");
  const dom3 = new JSDOM(html, { ...opts, url: "https://example.test/telemetry/#fields" });
  await sleep(50);
  ok(dom3.window.document.getElementById("main").textContent.includes("Field reference"), "a deep link to #fields opens it");
  ok(!/<\/script/i.test(d.getElementById("data").textContent), "inline data cannot close the script tag");
  ok(errors.length === 0, "still no script errors " + errors.join(";"));
  w.close(); dom2.window.close(); dom3.window.close();
})().catch(e => { console.log("FAIL: test crashed", e && e.stack || e); process.exitCode = 1; });
