"""Prompt/template versioning (M7 housekeeping #1): every LLM-backed
backend exposes a `prompt_version` fingerprint - a hash of its own
literal prompt-building source (and any template/criteria constants
that source reads) - included in that call's cache key
(app/backends/cache.py, app/backends/extract_cache.py,
app/reconcile/cache.py). Editing a prompt changes its fingerprint,
which changes every cache key it's part of, which means a prompt
change can no longer silently replay fixtures recorded under the old
wording - the exact bug class M7's registry_flags_check fix hit (the
cache key didn't depend on the prompt text, so a stale recording kept
replaying the old, wrong instruction after the prompt was already
fixed in code).

Fingerprinting the literal source (via inspect.getsource on the
prompt-building function, plus any template strings it closes over)
rather than a hand-maintained version string: a hand-maintained
number is exactly the kind of thing a future edit forgets to bump.
"""

from __future__ import annotations

import hashlib


def prompt_fingerprint(*parts: str) -> str:
    joined = "\x00".join(parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]
