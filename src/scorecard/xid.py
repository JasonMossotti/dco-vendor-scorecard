"""GPU XID codes: NVIDIA's public Xid catalog as transcribed in ``config/xid_catalog.yaml``.

One source for every XID name the site shows: the synthetic generator's driver messages, the failure
pattern signatures, and the Glossary's XID popups all read it, so a name cannot drift from NVIDIA's.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOG = Path(__file__).resolve().parents[2] / "config" / "xid_catalog.yaml"


@lru_cache(maxsize=2)
def catalog(path: Path = CATALOG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def names(path: Path = CATALOG) -> dict[int, str]:
    """{xid: NVIDIA's name} for every code in the catalog addendum."""
    return {c["xid"]: c["name"] for c in catalog(path)["codes"]}


def critical(path: Path = CATALOG) -> list[int]:
    """The XIDs that start the IT Partner's GPU restoration clock at AUS-1."""
    return [c["xid"] for c in catalog(path)["codes"] if c.get("critical")]
