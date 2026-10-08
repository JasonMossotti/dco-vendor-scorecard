// Related records on the Incident Portal: the links the records make, the relations people confirmed, and
// the suggestions scored from the data, with Confirm and Deny kept in this browser.
// Usage: node relations.cjs PAGE.html
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const errors = [];
const dom = new JSDOM(fs.readFileSync(process.argv[2], "utf8"), { runScripts: "dangerously", url: "https://example.test/tickets/#INC3100136",
  pretendToBeVisual: true, virtualConsole: new VirtualConsole().on("jsdomError", e => errors.push(String(e))) });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };
setTimeout(() => {
  const t = () => d.getElementById("detail").textContent;
  ok(errors.length === 0, "no script errors " + errors.join(";"));
  ok(t().includes("Linked in the records"), "links from the records are grouped");
  d.querySelector('a.tk-link[href="#INC3100153"]');
  ok(t().includes("Suggested by the data"), "suggestions shown");
  const sug = d.querySelector("[data-confirm]");
  ok(sug !== null, "a suggestion can be confirmed");
  ok(t().match(/\(\+\d+\)/) !== null, "each reason shows its points");
  const key = sug.dataset.confirm;
  d.querySelector(`[data-type="${key}"]`).value = "duplicate";
  sug.click();
  ok(d.getElementById("detail").textContent.includes("saved in this browser"), "a confirmation is kept in this browser");
  ok(d.getElementById("detail").textContent.includes("Duplicate"), "with the type the person chose");
  const undo = d.querySelector("[data-undo]");
  ok(undo !== null, "and can be removed");
  undo.click();
  const deny = d.querySelector("[data-deny]");
  deny.click();
  ok(d.getElementById("detail").textContent.includes("denied in this browser"), "a denied suggestion is hidden and counted");
  d.querySelector("[data-clear]").click();
  ok(d.querySelector("[data-deny]") !== null, "denied suggestions can come back");
  d.getElementById("rel-add").value = "wo-41023";
  d.getElementById("rel-add-why").value = "Manual test";
  d.getElementById("rel-add-go").click();
  ok(d.getElementById("detail").textContent.includes("Manual test"), "any record can be related by hand");
  d.getElementById("rel-add").value = "NOPE"; d.getElementById("rel-add-go").click();
  ok(d.getElementById("rel-add").placeholder.includes("No such record"), "an unknown number is explained");
  ok(errors.length === 0, "still no script errors " + errors.join(";"));
  // A record whose relation a person confirmed shows who confirmed it and why, from the repository.
  w.location.hash = "#INC3100153";
  setTimeout(() => {
    const t2 = d.getElementById("detail").textContent;
    ok(t2.includes("Confirmed by a person") && t2.includes("IT Partner Site Manager") && t2.includes("2026-09-30"),
       "a curated relation shows its type, who confirmed it, and when");
    ok(t2.includes("INC3100170"), "and the record it relates to");
    ok(errors.length === 0, "no script errors on the curated record " + errors.join(";"));
  }, 30);
}, 30);
