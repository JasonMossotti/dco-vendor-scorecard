// The Devices page: the list by system, search, a device by its link (#name) with its connections, a rack's
// trays and their leaf ports, a leaf port, and the drawing card shown in place.
// Usage: node devices_page.cjs PAGE.html
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const [file] = process.argv.slice(2);
const errors = [];
const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "dangerously", url: "https://example.test/devices/#leaf-a07-r1%20port%2018",
  pretendToBeVisual: true, beforeParse(w) { w.fetch = () => Promise.reject(new Error("offline")); w.scrollTo = () => {}; },
  virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const tick = () => new Promise(r => w.setTimeout(r, 0));
const go = async h => { w.location.hash = h; await tick(); await tick(); };

(async () => {
  await tick(); await tick();
  const main = d.getElementById("main"), list = d.getElementById("list");
  ok(main.querySelector("h1").textContent === "leaf-a07-r1 port 18", "a link to a leaf port opens it");
  const cells = [...main.querySelectorAll("table.conn td")].map(t => t.textContent);
  ok(cells.some(t => t.startsWith("a13-ct18") && t.includes("mlx5_1")), "the port is cabled to a13-ct18, NIC mlx5_1");
  ok(main.querySelector("tr.hit") && main.querySelector("tr.hit").textContent.includes("a13-ct18"), "the port table marks the port");
  ok(main.querySelector(".loc-pop.loc-inline") !== null, "the drawing card is shown in place");
  ok(main.querySelector(".loc-pop .loc-x") === null, "with no close button");
  ok([...list.querySelectorAll("h2")].map(h => h.textContent).join("|").includes("InfiniBand fabric"), "the list has a section per system");
  ok(list.querySelectorAll("a").length > 300, "the list names the devices");
  await go("#A07");
  ok(main.querySelector("h1").textContent === "Rack A07", "a rack by its link");
  const trays = main.querySelectorAll("table.inside tbody tr");
  ok(trays.length === 18, "the rack lists its 18 compute trays");
  ok(trays[0].textContent.includes("a07-ct01") && trays[0].textContent.includes("leaf-a04-r0 port 1"), "with each tray's leaf ports");
  ok([...main.querySelectorAll("table.conn a")].some(a => a.textContent === "TO-A07-B"), "and its feeds");
  await go("#" + encodeURIComponent("CDU-B3"));
  ok(main.querySelector("h1").textContent === "CDU-B3" && main.textContent.includes("MUPS-B1"), "a CDU and what powers it");
  const q = d.getElementById("q");
  q.value = "a13-ct1"; q.dispatchEvent(new w.Event("input"));
  ok(/^1\d matches|^\d+ matches/.test(d.getElementById("count").textContent), "search finds trays: " + d.getElementById("count").textContent);
  q.value = "leaf-a07-r1 port 18"; q.dispatchEvent(new w.Event("input"));
  ok([...list.querySelectorAll("a")].some(a => a.textContent.startsWith("leaf-a07-r1 port 18")), "search finds a port");
  for (const [dev, href] of [["leaf-a07-r1 port 18", "#leaf-a07-r1:swp18"], ["leaf-a07-r1", "#leaf-a07-r1"], ["A07", "#A07"], ["a13-ct18", "#a13-ct18/0"], ["a15-nvsw3", "#a15-nvsw3"], ["UPS-B4", "#UPS-B4"], ["CDU-A1", "#CDU-A1"]]) {
    await go("#" + encodeURIComponent(dev));
    ok(main.querySelector(`a.tel[href="../telemetry/${href}"]`), `${dev}: the card links to its telemetry view`);
  }
  await go("#B30");
  ok(!main.querySelector("a.tel"), "a rack with no telemetry gets no Telemetry link");
  ok(!main.querySelector(".pred"), "and no prediction");
  await go("#CDU-A1");
  const pred = main.querySelector(".pred");
  ok(pred && pred.textContent.includes("Filter healthy by condition") && pred.textContent.includes("due by the calendar"), "a CDU card says its filter's condition: " + (pred && pred.textContent));
  ok(pred && pred.querySelector('a[href="../patterns/#predict"]'), "and links to the Predictive maintenance view");
  await go("#a16-ct18");
  ok(main.querySelector(".pred") && main.querySelector(".pred").textContent.includes("GPU 2 on the memory watch list"), "a tray on the GPU memory watch list says so");
  await go("#nothing-here");
  ok(main.textContent.includes("No device by that name"), "an unknown name says so");
  const names = ["leaf-a07-r1 port 18", "leaf-a07-r1:swp18", "Rack A07", "a13-ct18", "A06_PowerShelf_1", "leaf-a07-r1 port 40", "UPS-B4"];
  console.log("LOOKUP " + JSON.stringify(Object.fromEntries(names.map(n => { const h = w.DEVICES.lookup(n); return [n, h ? [h[0], h[1].text, h[1].conn] : null]; }))));
  // the asset register (#assets), an asset by serial, and a device's own register section
  await go("#assets");
  ok(main.querySelector("h1").textContent === "Asset register", "the register opens from its link");
  ok([...main.querySelectorAll(".finding")].length === 3, "with its three findings");
  ok(main.textContent.includes("F-007") && main.textContent.includes("SP-3"), "and the other checks' findings it corroborates");
  const rq = d.getElementById("rq");
  rq.value = "a09-mgmt2"; rq.dispatchEvent(new w.Event("input"));
  ok(/^\d+ assets?/.test(d.getElementById("rcount").textContent), "register search: " + d.getElementById("rcount").textContent);
  await go("#asset/MSK4Z3UMGF");
  ok(main.querySelector("h1").textContent === "MSK4Z3UMGF" && main.textContent.includes("Disposed"), "a disposed switch by its serial");
  ok(main.textContent.includes("Answering at the last daily scan in a09-mgmt2"), "still answering in a09-mgmt2");
  await go("#asset/NOPE0000");
  ok(main.textContent.includes("No asset with that tag or serial"), "an unknown serial says so");
  await go("#A15_PowerShelf_1");
  const reg = [...main.querySelectorAll("h2.sec")].some(h => h.textContent === "In the asset register");
  ok(reg && main.querySelector("table.reg").textContent.includes("PSU 3"), "a power shelf lists its PSUs in the register");
  ok(main.textContent.includes("AR-1"), "with the finding on its PSU");
  ok(errors.length === 0, "no script errors " + errors.join(";"));
})();
