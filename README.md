# nexus-clear
Credentialing Readiness Agent MVP

## Eval honesty

This README does not quote specific accuracy/ECE/cost/latency numbers from
the M5 Classify eval, and should not gain any without checking the number's
mode label first: `uv run python -m app.eval.run` labels every classify
mode built from simulated fixtures with a `-SIMULATED` suffix
(`app/eval/classify_run.py`), in both its markdown table and the JSON run
file. A number from a `-SIMULATED` row is not real model output - see the
M5/M5.1 completion reports for which modes, if any, are still simulated.

## Key management caveat

The vault's master key (`app/vault/key_manager.py`'s `LocalKeyManager`) loads
from the `MASTER_KEY` env var (base64, 256-bit) when set, falling back to a
local file (`MASTER_KEY_PATH`, generated on first use, mode 0600) when it
isn't. Neither path is a production key-management story: a real deployment
should source the master key from a KMS/Secrets Manager/Vault directly,
with rotation and access-logging on the key itself - not a long-lived raw
key sitting in a process's environment or on a container's disk. Treat both
as dev/demo-only.
