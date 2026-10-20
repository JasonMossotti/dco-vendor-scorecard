"""Live status page (/live/): the whole site minute by minute, reconciled with Site health hour by hour, and the page."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_live  # noqa: E402
import render_telemetry  # noqa: E402
from scorecard import live_status as LS  # noqa: E402
from scorecard import site_health as SH  # noqa: E402


@pytest.fixture(scope="module")
def built():
    return render_live.prepare()


def test_manifest_is_current(built):
    assert (ROOT / "data" / "live" / "manifest.json").read_text(encoding="utf-8") == render_live.manifest_text(built), \
        "data/live/manifest.json is stale; run scripts/render_live.py"


def test_every_agreement_holds(built):
    checks = built[2]
    assert [c.name for c in checks] == ["families", "groups", "units", "mains", "ride_through"]
    for c in checks:
        assert c.checked > 0 and not c.misses, (c.name, c.misses[:5])


def test_minute_conditions_leave_site_health_unchanged():
    """The minute records are kept beside Site health's hourly issues; the hourly page is what it was."""
    sh, data = SH.build()
    hourly = {(i["from"], i["family"], i["hall"], i["state"], i["text"]) for i in data["issues"]}
    minute = {(h, f, hl, s, t) for h, f, hl, s, t, _, _ in sh.minute_issues}
    for x in hourly:
        assert (x[0], *x[1:]) in minute, x
    assert all(mk is None or (mk.dtype == bool and mk.shape == (60,) and mk.any()) for *_, mk in sh.minute_issues)


def test_the_utility_trip_minute_by_minute(built):
    idx, days, _ = built
    (o,) = idx["power"]["outages"]
    start = np.datetime64(idx["window"]["start"].replace("Z", ""))
    trip = int((np.datetime64(o["trip"].replace("Z", "")) - start) / np.timedelta64(1, "m"))
    back = int((np.datetime64(o["back"].replace("Z", "")) - start) / np.timedelta64(1, "m"))
    util = next(g for g in idx["groups"] if g["key"] == "utility")
    st = np.asarray(SH.unrle(util["state"]))
    # red from the first reading after the trip (21:15) through the retransfer's minute (21:56), green either side:
    # the meter's 41 dead minutes and the minute the breaker closed again, not the two hours they fall in
    assert st[trip] == SH.GREEN and st[trip + 1] == SH.RED and st[back] == SH.RED and st[back + 1] == SH.GREEN
    assert (st == SH.RED).sum() == back - trip == 42
    fam = np.asarray(SH.unrle(idx["family_state"]["power"]))
    assert fam[trip + 1] == SH.RED and fam[trip - 60] < SH.RED
    d = days[trip // 1440]
    from scorecard.telemetry_power import unpack
    v = unpack(d["mains"]["MV-A"]["v"])
    assert v[trip % 1440 + 1] == 0 and v[trip % 1440 - 60] > 13000


def test_days_cover_the_month(built):
    idx, days, _ = built
    assert len(days) == idx["minutes"] // 1440 == idx["days"]
    from scorecard.telemetry_power import unpack
    for d in days:
        for x in d["ups"].values():
            assert all(len(unpack(v)) == 1440 for v in x.values())


def test_pack_round_trips():
    from scorecard.telemetry_power import unpack
    for a in ([5, 5, 5, 7, 7, 3, 3, 3, 3, 9], [0], [1, 2, 3], [4, 4]):
        assert unpack(LS.pack(np.asarray(a))).tolist() == a


def test_network_conditions_name_a_direction(built):
    for c in built[0]["conditions"]:
        assert (c["family"] == "network") == ("dir" in c)
        if "dir" in c:
            assert c["dir"] in ("ew", "ns")


def test_the_sample_feed_satisfies_the_contract(built):
    """data/now_sample.json is the minute after the trip in the feed contract, with the day files' values."""
    from scorecard.live.now import validate
    from scorecard.telemetry_power import unpack
    idx, days, _ = built
    m = LS.sample_minute(idx)
    doc = LS.now_doc(idx, days, m)
    validate(doc)
    d = days[m // 1440]
    i = m - d["from"]
    assert doc["source"] == {"kind": "replay", "poll_interval_s": 60, "minute": m, "note": doc["source"]["note"]}
    assert all(x["v_ll"] == 0 and x["breaker"] == "open" for x in doc["mains"].values()), "the minute after the trip: both mains dead"
    assert doc["ups"]["UPS-A1"]["runtime_s"] == unpack(d["ups"]["UPS-A1"]["rt"])[i]
    assert len(doc["mains"]["MV-A"]["kw_last_hour"]) == idx["history_min"]
    assert next(g for g in doc["groups"] if g["key"] == "utility")["state"] == "lost"
    assert doc["conditions"][0]["text"].startswith("Utility feeds: 0 of 2, site on generators")
    man = json.loads((ROOT / "data" / "live" / "manifest.json").read_text(encoding="utf-8"))
    assert "now_sample.json" in man["files"]


def test_live_tab_is_on_every_page():
    from scorecard import sitenav
    assert ("live", "Live", "live/") in sitenav.TABS
    keys = [k for k, _, _ in sitenav.TABS]
    assert keys.index("live") == keys.index("telemetry") + 1


def test_live_page_builds_and_works(tmp_path, built):
    out = tmp_path / "live"
    render_live.write_site(out, built)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    man = json.loads((ROOT / "data" / "live" / "manifest.json").read_text(encoding="utf-8"))
    import hashlib
    for name, sha in man["files"].items():
        assert hashlib.sha256((out / "data" / name).read_bytes()).hexdigest() == sha, name
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "live_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0 and "FAIL" not in proc.stdout, proc.stdout + proc.stderr
