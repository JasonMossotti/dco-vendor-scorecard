# The Live page's feed: `now.json`

The Live tab (`/live/`) normally replays the synthetic sample month on a simulated clock. Given a feed, it shows the
site now instead: `/live/?feed=now.json` reads one small JSON file and reads it again every poll interval the file
names. A site's read-only collector writes that file every poll (`scripts/collect.py --now`); the demo ships one
written from the sample month (`/live/?feed=data/now_sample.json`, the minute after the 09-24 utility trip), and the
page draws both through the same code. A test checks that the replayed minute reads on the page exactly as the clock
shows that minute (`tests/js/live_page.cjs`).

- Schema: [`now.schema.json`](now.schema.json) (JSON Schema draft 2020-12), version `aus1-live-now/1`.
- Writers: `src/scorecard/live/now.py` (`NowWriter`, from the collector) and `src/scorecard/live_status.py`
  (`now_doc`, a replay from the sample month).
- Reader: `templates/live.html` (feed mode). The `feed` parameter must be a path on the same site; anything with a
  scheme or starting with `//` is ignored and the page runs the clock.

Everything here is synthetic and fictional. No field, register, or point name implies knowledge of any real
company's internal systems.

## The document

| Field | Type | Meaning |
|---|---|---|
| `schema` | `"aus1-live-now/1"` | The contract version. The page refuses any other and says so. |
| `site` | string | The site the file describes (`AUS-1`). |
| `generated_at` | UTC time, `YYYY-MM-DDTHH:MM:SSZ` | When the writer finished this poll. The page's clock shows it in CDT and UTC. |
| `source.kind` | `collector` or `replay` | Who wrote it. A replay is never stale; it also carries `source.minute`, the sample minute. |
| `source.poll_interval_s` | number | How often the writer polls; the page re-reads the file this often (clamped to 5 to 60 s). |
| `stale_after_s` | number | Past this age a collector's file gets a red "Feed stale" banner: the values are the last known, not the site now. Default three poll intervals. |
| `take_load_s` | number or null | The generators' take-load time, for the ride-through margin (12 s, measured at the 09-24 trip). |
| `mains.<id>` | object | Each 13.8 kV main's meter: `v_ll` (average line-to-line V), `i_avg` (A), `kw`, `pf`, `hz`, `breaker` (`closed`, `open`, or null), `kw_last_hour` (up to 60 values, oldest first, the last one now). |
| `ups.<id>` | object | `output` (`normal`, `battery`, `bypass`, `other`), `load_kw`, `load_pct`, `runtime_s` (upsAdvBatteryRunTimeRemaining), `charge_pct` (upsAdvBatteryCapacity). |
| `ride_through.<scope>` | object | `s`, the shortest runtime among the scope's UPSs carrying load, and `set_by`, the UPS that sets it. Scopes: `SITE-IT`, `SITE-COOLING`, and each hall (`HALL-A`, `HALL-B`). |
| `generators.<id>` | object | `state` (`stopped`, `starting`, `running`, `cooldown`, `other`), `kw`, `breaker`, `fuel_pct`. |
| `conditions[]` | list | What is degraded or lost now: `family` (gpu, cdu, power, network, mechanical, mgmt, storage), `hall` (or null for the site), `state` (`degraded` or `lost`), `text`, `device`, `since` (when first seen), and for the network `dir` (`ew` or `ns`). Lost first, then the oldest. |
| `groups[]` | list, optional | Redundancy: `key` and `hall` (Site health's group), `avail`, `total`, `state` (`normal`, `degraded`, `lost`, `not_in_service`). A replay carries Site health's groups; a collector leaves it out. |
| `feeds[]` | list | One row per configured device: `device`, `site_id`, `family`, `protocol`, `ok`, `last_ok` (the last good poll, or null), `error`. |

Unknown values are `null`, never invented: a device the collector cannot read keeps its last values in the file and
is listed under `feeds` with `ok: false`.

## States the collector sets

The collector does not run Site health. It sets states from a short list that follows Site health's rules where it
reads the same thing (`config/site_health.yaml`), so a reader can check every condition against its reading:

| Reading | State | Family |
|---|---|---|
| Every utility main dead (no voltage) or its breaker open | lost: "Site on generators" | power |
| One main dead or open, the other in | degraded | power |
| A UPS on battery | degraded (Site health: the UPS is doing its job) | power |
| A UPS on static bypass | degraded (the unit is out of service) | power |
| A ride-through at or below `take_load_s` | lost | power |
| A generator's fuel below `fuel_amber_pct` (50%) | degraded | power |
| A busway's voltage out of its tolerance, or a tap-off breaker open | degraded | power |
| A CDU pump or pump redundancy not `OK` (Redfish `Status.Health`) | degraded | cdu |
| A leak detected | lost (Site health: a leak is red) | cdu |
| A BMS point held by an operator or out of service | degraded | mechanical |
| A device not answering | degraded: its last values are shown | the device's family |

A family with no device in the feed shows "not in this feed" rather than normal. Redundancy needs Site health's group
rules (units against the design, planned work counted), which the collector does not run yet, so a collector's file
has no `groups` and the page says so.

## Serving it

The page and the file must come from the same site. The simplest deployment is a small web server (or a file share
behind one) on the monitoring network that serves the built Live page and the collector's file side by side:

```
/srv/aus1/www/live/index.html, data/...   # scripts/build_site.py output for /live/
/srv/aus1/www/live/now.json               # scripts/collect.py --now /srv/aus1/www/live/now.json
```

then `https://<monitoring host>/live/?feed=now.json`. The writer replaces the file atomically (it writes beside it and
renames), so a reader never sees half a document. `docs/LIVE_READINESS.md` lists what a deployment still needs.
