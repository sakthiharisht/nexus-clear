# nexus-clear
Credentialing Readiness Agent MVP

## Key management caveat

The vault's master key (`app/vault/key_manager.py`'s `LocalKeyManager`) loads
from the `MASTER_KEY` env var (base64, 256-bit) when set, falling back to a
local file (`MASTER_KEY_PATH`, generated on first use, mode 0600) when it
isn't. Neither path is a production key-management story: a real deployment
should source the master key from a KMS/Secrets Manager/Vault directly,
with rotation and access-logging on the key itself - not a long-lived raw
key sitting in a process's environment or on a container's disk. Treat both
as dev/demo-only.
