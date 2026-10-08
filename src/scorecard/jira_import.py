"""Read the partners' Jira projects into one shape the deployment program can use.

Two export formats, one result:

* **JSON**, the response of a Jira Cloud search (``/rest/api/3/search/jql``): ``{"issues": [...], "isLast": ...}``.
  A multi-page export is a list of those responses, or one file per page.
* **CSV**, Jira's issue export, with the column names set in ``config/jira_fields.yaml``.

Custom field ids and CSV headers differ between Jira sites, so the field map is configuration. The importer only
reads; it never writes to Jira. Assignees are not read: who signed is the sign-off record's business, by role.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIELD_MAP = ROOT / "config" / "jira_fields.yaml"
UTC = timezone.utc


class JiraImportError(ValueError):
    pass


def load_field_map(path: Path = FIELD_MAP) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _time(value: Any, formats: list[str]) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in formats:
        try:
            t = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return t if t.tzinfo else t.replace(tzinfo=UTC)
    raise JiraImportError(f"unrecognised date {s!r}; add its format to csv_date_formats")


def _day(value: Any) -> str | None:
    return str(value)[:10] if value else None


def _category(name: str, fmap: dict[str, Any]) -> str:
    for cat, names in fmap["status_categories"].items():
        if name in names:
            return cat
    raise JiraImportError(f"status {name!r} is in no status category; add it to status_categories")


def _row(project: str, fmap: dict[str, Any], **v: Any) -> dict[str, Any]:
    proj = fmap["projects"].get(project)
    if proj is None:
        raise JiraImportError(f"project {project} is not in the field map")
    return {"project": project, "partner": proj["partner"], **v}


def from_json(data: Any, fmap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Issues from one search response or a list of pages."""
    fmap = fmap or load_field_map()
    f, fmts = fmap["fields"], fmap["csv_date_formats"]
    pages = data if isinstance(data, list) else [data]
    out = []
    for page in pages:
        if "issues" not in page:
            raise JiraImportError("not a Jira search response: no 'issues'")
        for i in page["issues"]:
            x, project = i["fields"], i["key"].rsplit("-", 1)[0]
            _row(project, fmap)                      # an unmapped project fails before any field is read
            out.append(_row(project, fmap, key=i["key"], id=i.get("id"),
                            type=x["issuetype"]["name"], summary=x.get("summary", ""),
                            status=x["status"]["name"], category=x["status"]["statusCategory"]["key"],
                            parent=(x.get("parent") or {}).get("key"),
                            created=_iso(_time(x.get("created"), fmts)), updated=_iso(_time(x.get("updated"), fmts)),
                            resolved=_iso(_time(x.get("resolutiondate"), fmts)), due=_day(x.get("duedate")),
                            start=_day(x.get(f["start"])), step=x.get(f["step"]), rack=x.get(f["rack"]),
                            doc=x.get(f["doc"])))
    return out


def from_csv(text: str, fmap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Issues from a Jira CSV export."""
    fmap = fmap or load_field_map()
    c, fmts = fmap["csv_columns"], fmap["csv_date_formats"]
    rows = list(csv.DictReader(text.splitlines()))
    if rows and c["key"] not in rows[0]:
        raise JiraImportError(f"no {c['key']!r} column: check csv_columns in the field map")
    out = []
    for r in rows:
        get = lambda k: (r.get(c[k]) or "").strip() or None  # noqa: E731
        out.append(_row(get("key").rsplit("-", 1)[0], fmap, key=get("key"), id=get("id"), type=get("type"),
                        summary=get("summary") or "", status=get("status"), category=_category(get("status"), fmap),
                        parent=get("parent"), created=_iso(_time(get("created"), fmts)),
                        updated=_iso(_time(get("updated"), fmts)), resolved=_iso(_time(get("resolved"), fmts)),
                        due=_day(get("due")), start=_day(get("start")), step=get("step"), rack=get("rack"),
                        doc=get("doc")))
    return out


def to_csv(issues: list[dict[str, Any]], fmap: dict[str, Any] | None = None) -> str:
    """Write issues as a CSV export with the field map's headers (for tests and for hand-off to a spreadsheet)."""
    import io
    fmap = fmap or load_field_map()
    c = fmap["csv_columns"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(c.values()), lineterminator="\n")
    w.writeheader()
    for i in issues:
        w.writerow({c[k]: i.get(k) or "" for k in c})
    return buf.getvalue()


def load_dir(path: Path, fmap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every export in a folder (``*.json`` and ``*.csv``), sorted by key; a key seen twice is an error."""
    fmap = fmap or load_field_map()
    out: list[dict[str, Any]] = []
    for p in sorted(Path(path).glob("*")):
        if p.suffix == ".json":
            out += from_json(json.loads(p.read_text(encoding="utf-8")), fmap)
        elif p.suffix == ".csv":
            out += from_csv(p.read_text(encoding="utf-8"), fmap)
    keys = [i["key"] for i in out]
    if dup := sorted({k for k in keys if keys.count(k) > 1}):
        raise JiraImportError(f"issues exported twice: {', '.join(dup[:5])}")
    return sorted(out, key=lambda i: (i["project"], int(i["key"].rsplit("-", 1)[1])))
