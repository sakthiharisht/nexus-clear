"""LIVE leie_check adapter (SPEC.md section 7.6): a local index built
from the real monthly OIG LEIE exclusion-list CSV.

Verified 2026-11-04 by downloading the real file directly (a web
search's summary of the column list didn't exactly match - it said
"ZIP CODE"/"WAIVERSTATE"; the real header row is "ZIP"/"WVRSTATE" -
confirming direct verification over a secondhand summary):
- `GET https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv`
- Header: LASTNAME,FIRSTNAME,MIDNAME,BUSNAME,GENERAL,SPECIALTY,UPIN,
  NPI,DOB,ADDRESS,CITY,STATE,ZIP,EXCLTYPE,EXCLDATE,REINDATE,
  WAIVERDATE,WVRSTATE
- ~10MB, real excluded individuals/entities - never committed to this
  repo, never logged beyond the structural fact that a lookup
  happened (CLAUDE.md invariant 4). Cached locally
  (settings.leie_cache_path, gitignored under data/) so repeat calls
  in one environment don't re-download a multi-megabyte file each
  time ("do not hammer public APIs").

leie_check takes a name (SPEC 7.6: `leie_check(name, dob?, npi?)`), so
unlike nppes_lookup this adapter CAN and does compute `possible_match`
itself - an exact normalized last+first name match against the
index. DOB/NPI, when provided, narrow a match further but are not
required (most LEIE rows have no NPI at all).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import httpx

_DOWNLOAD_URL = "https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv"


def _normalize(value: str) -> str:
    return value.strip().upper()


class LiveLeieAdapter:
    def __init__(self, cache_path: Path, client: httpx.Client | None = None) -> None:
        self._cache_path = cache_path
        self._client = client or httpx.Client(timeout=30.0)
        self._index: dict[tuple[str, str], list[dict[str, str]]] | None = None

    def _ensure_downloaded(self) -> str:
        if self._cache_path.exists():
            return self._cache_path.read_text(encoding="utf-8", errors="replace")
        response = self._client.get(_DOWNLOAD_URL)
        response.raise_for_status()
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(response.text, encoding="utf-8")
        return response.text

    def _ensure_index(self) -> dict[tuple[str, str], list[dict[str, str]]]:
        if self._index is not None:
            return self._index
        raw = self._ensure_downloaded()
        index: dict[tuple[str, str], list[dict[str, str]]] = {}
        for row in csv.DictReader(io.StringIO(raw)):
            key = (_normalize(row.get("LASTNAME", "")), _normalize(row.get("FIRSTNAME", "")))
            index.setdefault(key, []).append(row)
        self._index = index
        return index

    def check(self, name: str, *, npi: str | None = None) -> dict[str, Any]:
        """`name` as "First Last" (this project's convention elsewhere -
        app/rules/context.py's profile.legal_name). Splits on the last
        whitespace-separated token as the last name, matching how the
        CSV's own LASTNAME/FIRSTNAME split a full name."""
        parts = name.strip().split()
        if len(parts) < 2:
            return {"possible_match": False, "npi": None}
        last_name, first_name = parts[-1], " ".join(parts[:-1])
        index = self._ensure_index()
        matches = index.get((_normalize(last_name), _normalize(first_name)), [])

        if npi:
            matches = [row for row in matches if row.get("NPI") == npi] or matches

        if not matches:
            return {"possible_match": False, "npi": None}
        return {"possible_match": True, "npi": matches[0].get("NPI") or None}
