// The P1 response console on the Emergency tab: argv[2] the Emergency page, argv[3] the Post-Incident Review page.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8"), pirHtml = fs.readFileSync(process.argv[3], "utf8");
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
const DATA = JSON.parse(html.split('id="data" type="application/json">')[1].split("</script>")[0]);
const net = [];
function open(page, url, store) {
  const errs = [];
  const dom = new JSDOM(page, { runScripts: "dangerously", url, virtualConsole: new VirtualConsole().on("jsdomError", e => errs.push(String(e))),
    beforeParse(w) {   // nothing on these pages may call the network
      w.fetch = (...a) => { net.push(String(a[0])); return Promise.reject(new Error("no network")); };
      w.XMLHttpRequest = function () { net.push("xhr"); throw new Error("no network"); };
      w.navigator.sendBeacon = u => { net.push(String(u)); return false; };
      if (store) for (const [k, v] of Object.entries(store)) w.localStorage.setItem(k, v);
    } });
  const d = dom.window.document;
  return { dom, w: dom.window, d, errs, t: () => d.getElementById("doc").textContent, close: () => dom.window.close() };
}
const E = h => open(html, "https://example.test/emergency/" + h);
const R = DATA.responses, CON = DATA.console, TY = Object.fromEntries(DATA.types.map(t => [t.id, t]));
const fwd = (c, n) => { for (let i = 0; i < n; i++) c.d.getElementById("r-fwd").click(); };

// The list, and every sample P1 record opens its event's console with the facts pre-filled.
const L = E("#respond");
ok(L.errs.length === 0, "no script errors on the list " + L.errs.join(";"));
ok(L.d.getElementById("t-respond").classList.contains("on") && L.d.querySelectorAll("#resp-list tr").length === DATA.events.length + 1, "Response lists every P1 event (8)");
L.close();
let facts = 0;
for (const ev of DATA.events) for (const rec of ev.records) {
  const c = E("#respond/" + rec), e = R.events[ev.id], t = c.t();
  const card = c.d.getElementById("c-event").textContent;
  const good = c.errs.length === 0 && c.w.eval("RS") && c.w.eval("RS").id === ev.id && e.records.every(r => card.includes(r.id)) && card.includes(e.summary)
    && (e.gpus ? card.includes(String(e.gpus)) : true) && e.work.every(j => card.includes(j.id)) && e.permits.every(p => card.includes(p.permit))
    && e.clocks.every(k => card.includes(k.label)) && card.includes(e.on_call.primary) && t.includes(DATA.bridge.dial_in)
    && c.d.querySelectorAll(".ntc").length === (e.types[0] ? TY[e.types[0]].notify.length : 0);
  if (good) facts++; else console.log("  facts differ for", rec, c.errs.join(";"));
  c.close();
}
ok(facts === DATA.events.reduce((a, x) => a + x.records.length, 0) && facts === 9, `every P1 record opens its event's console with its facts (${facts} of 9)`);
const a1 = E("#respond/INC3900001"), a2 = E("#respond/WO-41023");
ok(a1.w.eval("RS").id === a2.w.eval("RS").id && a1.w.eval("RS").id === "WO-41023", "the two A07 records open the same response");
ok(a1.d.location.hash === "#respond/WO-41023", "the address names the event");
a1.close(); a2.close();
const p2 = Object.values(R.events).find(x => x.priority === "P2");
const c2 = E("#respond/" + p2.id);
ok(c2.errs.length === 0 && c2.t().includes("P2 event (escalated)"), "a P2 record opens an escalated response");
c2.close();
const proto = E("#respond/__proto__");
ok(proto.t().includes("No P1 event or P2 record __proto__") && proto.w.eval("({}).t0") === undefined, "a crafted record number opens nothing and changes no prototype");
proto.close();
const bad = E("#respond/NOPE-1");
ok(bad.t().includes("No P1 event or P2 record NOPE-1"), "an unknown record says so");
bad.close();

// The tier list equals the procedure; Send records the message and the free text; escalation at the routing file's minutes.
const c = E("#respond/WO-41023");
const ty = TY[R.events["WO-41023"].types[0]];
ok([...c.d.querySelectorAll(".ntc .nh b")].map(x => x.textContent).join("|") === ty.notify.map(n => n.name).join("|"), "the notifications are the procedure's tiers, in order");
c.d.querySelector("[data-extra=site_leadership]").value = "Hall A access restricted to the bridge team.";
c.d.querySelector("[data-extra=site_leadership]").dispatchEvent(new c.w.Event("input"));
c.d.querySelector("[data-send=site_leadership]").click();
ok(c.w.eval("RS").sent.site_leadership && c.w.eval("RS").sent.site_leadership.text.includes("Hall A access restricted") && c.w.eval("RS").sent.site_leadership.text.includes("72 GPUs"), "Send records the pre-filled message with the free text");
ok(c.d.getElementById("n-site_leadership").textContent.includes("not acknowledged"), "a sent notice waits for its acknowledgement");
const [e1, e2] = CON.escalate;
fwd(c, e1.after_min / 5 - 1);
ok(!c.d.getElementById("n-site_leadership").textContent.includes("Escalated"), `not escalated before ${e1.after_min} min`);
fwd(c, 1);
ok(c.d.getElementById("n-site_leadership").textContent.includes(`${e1.to} told`), `escalated to ${e1.to} at ${e1.after_min} min`);
fwd(c, (e2.after_min - e1.after_min) / 5);
ok(c.d.getElementById("n-site_leadership").textContent.includes(`${e2.to} told`), `escalated to ${e2.to} at ${e2.after_min} min`);
c.d.querySelector("[data-ack=site_leadership]").click();
ok(c.d.getElementById("n-site_leadership").textContent.includes("Acknowledged"), "an acknowledgement is marked by hand");
// The bridge against its clock, the gate, the decision log, command handover.
c.d.getElementById("r-bridge").click();
ok(c.d.getElementById("c-bridge").textContent.includes("Late"), "a bridge opened after 15 minutes is late");
ok(c.d.getElementById("r-rts").disabled, "return to service is locked until the gate is complete");
c.d.querySelectorAll("[data-rts]").forEach(x => { x.checked = true; x.dispatchEvent(new c.w.Event("change")); });
ok(!c.d.getElementById("r-rts").disabled, "the gate complete unlocks return to service");
c.d.querySelector('[data-hold="MOP-310"][data-what="Hold"]').click();
ok(c.d.getElementById("decisions").textContent.includes("Hold MOP-310"), "holding a change is a logged decision");
c.d.getElementById("r-cmd").value = "Customer Site Lead"; c.d.getElementById("r-cmd-go").click();
ok(c.d.getElementById("c-notify").textContent.includes("Customer Site Lead since"), "command handover is recorded");
ok(c.d.getElementById("timeline").textContent.includes("Notice sent to Site leadership"), "every action writes the timeline");
// Close: YAML, and a review that starts from it.
c.d.getElementById("r-close").click();
const y = c.w.eval("responseYaml()");
ok(y.startsWith("# Emergency response") && y.includes("event: \"WO-41023\"") && y.includes("Hall A access restricted"), "close exports the response as YAML");
const pirLink = c.d.getElementById("r-pir");
ok(pirLink && pirLink.getAttribute("href") === "../pir/#new=WO-41023", "close offers the post-incident review");
const saved = c.w.localStorage.getItem("usm.emergency.responses");
c.close();
const pir = open(pirHtml, "https://example.test/pir/#new=INC3900001", {"usm.emergency.responses": saved});
const comms = [...pir.d.querySelectorAll('input[data-f^="communications."][data-f$=".message"]')].map(x => x.value);
ok(pir.errs.length === 0 && comms.some(m => m.includes("Hall A access restricted")), "the review's communications come from the response");
ok(pir.d.querySelector('input[data-f="Incident Commander"]').value === "Customer Site Lead", "the review's Incident Commander comes from the response");
ok(pir.d.querySelector('input[data-f="Review meeting"]').value.startsWith("Due by 2026-09-2"), "the review is due in five business days");
pir.close();

// Drill: seeded acknowledgements, one never, so escalation shows.
const dr = E("#respond/WO-41023");
const m = dr.d.getElementById("r-mode"); m.value = "drill"; m.dispatchEvent(new dr.w.Event("change"));
dr.d.querySelectorAll("[data-send]").forEach(b => b.click());
dr.d.getElementById("r-bridge").click();
fwd(dr, 7);
const acked = dr.d.querySelectorAll(".ntc.ack").length, esc = dr.d.querySelectorAll(".ntc.esc").length;
ok(acked === ty.notify.length - 1 && esc === 1, `drill: ${acked} acknowledged, ${esc} never (escalated)`);
ok([...dr.d.querySelectorAll("#roll tr")].slice(1).every(r => r.textContent.includes("CDT") || r.textContent.includes("Scribe")), "drill: the leads join the bridge");
dr.close();

// Replay of A07: the recorded bridge, and the same score as the Command view.
const rp = E("#respond/WO-41023/replay");
fwd(rp, 80);
const s = DATA.command.replays[0].summary;
ok(rp.errs.length === 0 && rp.d.getElementById("replay-score").textContent.includes(`${s.met} of ${s.steps}`) && s.met === 9 && s.steps === 14, "the A07 replay shows 9 of 14 met, as the Command view");
ok(rp.d.querySelectorAll("#timeline tr").length - 1 === R.events["WO-41023"].replay.length, "the replay plays every entry of the comms log (27)");
ok(rp.d.getElementById("c-bridge").textContent.includes("Late") && !rp.d.querySelector("[data-send]"), "the replay shows the late bridge and is read-only");
rp.close();

// A Live link opens the console at its minute.
const lv = E("#respond/INC3900001/2026-09-15T16:30Z");
ok(lv.d.getElementById("clk").textContent.startsWith("11:30 CDT"), "a Live link starts the clock at its minute");
lv.close();
ok(net.length === 0, "nothing calls the network " + net.join(","));
