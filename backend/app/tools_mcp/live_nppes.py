"""LIVE nppes_lookup adapter (SPEC.md section 7.6): the real public
NPPES NPI Registry API.

Verified 2026-11-04 by calling the real endpoint directly (not just
reading docs - the official API page at npiregistry.cms.hhs.gov/api-page
renders without the parameter/response details, so a live call was
the only way to actually confirm the shape):
- `GET https://npiregistry.cms.hhs.gov/api/?version=2.1&number=<NPI>`
- A nonexistent NPI returns `{"result_count": 0, "results": []}` -
  this is SPEC's "live mode is demonstrated on one fake NPI to show
  not-found handling (indeterminate)" case, confirmed directly.
- An NPI that exists returns `{"result_count": 1, "results": [{
  "number": "...", "enumeration_type": "NPI-1"|"NPI-2",
  "basic": {"first_name", "last_name", "status", ...},
  "taxonomies": [{"desc", "primary", "state", ...}], "addresses": [...],
  ...}]}` - field names only recorded here, not the real person's
  data that confirmed them (CLAUDE.md invariant 4).

No `name` parameter exists on this tool (SPEC 7.6: `nppes_lookup(npi)`
only) - so this adapter cannot itself judge "name_consistent"; it
returns the raw name/status/taxonomy descriptions it found and lets
app/reconcile's derivation compare that against the case's own
expected name, the same way it already does for FIXTURE-mode's
precomputed convenience booleans when those are absent.

Caching + rate limiting ("do not hammer public APIs"): per-process NPI
cache, plus a minimum delay enforced between actual network calls -
appropriate for this adapter's use (occasional demo/contract-test
calls), not a high-throughput service.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

_BASE_URL = "https://npiregistry.cms.hhs.gov/api/"
_MIN_INTERVAL_SECONDS = 1.0


class LiveNppesAdapter:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_call_monotonic: float | None = None

    def _throttle(self) -> None:
        if self._last_call_monotonic is None:
            return
        elapsed = time.monotonic() - self._last_call_monotonic
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)

    def lookup(self, npi: str) -> dict[str, Any]:
        """Raw-ish payload: `exists`, and when found, `name`, `status`,
        `taxonomy_descriptions`. Never raises on a clean not-found -
        that is a legitimate, expected answer (CLAUDE.md invariant 2:
        a registry miss is `indeterminate`, not an error)."""
        if npi in self._cache:
            return self._cache[npi]

        self._throttle()
        response = self._client.get(_BASE_URL, params={"version": "2.1", "number": npi})
        self._last_call_monotonic = time.monotonic()
        response.raise_for_status()
        data = response.json()

        if data.get("result_count", 0) == 0 or not data.get("results"):
            payload: dict[str, Any] = {"exists": False}
        else:
            record = data["results"][0]
            basic = record.get("basic", {})
            name = " ".join(
                part for part in (basic.get("first_name"), basic.get("last_name")) if part
            )
            payload = {
                "exists": True,
                "name": name or None,
                "status": basic.get("status"),
                "taxonomy_descriptions": [
                    t.get("desc") for t in record.get("taxonomies", []) if t.get("desc")
                ],
            }

        self._cache[npi] = payload
        return payload
