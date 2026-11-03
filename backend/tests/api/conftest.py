"""API test fixtures: a TestClient wired to the test's real (rollback-
isolated) db_session and a tmp_path-scoped vault, instead of the app's
real data/vault/ paths.

`vault_components` is split out from `api_client` (rather than building
the key manager/blob store inline) so a test can request both fixtures
and assert against the vault directly - e.g. decrypting a document the
API just stored - without constructing a second, divergent vault. Both
resolve against the same per-test `tmp_path`, so they see the same
master key file and blob root.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_blob_store, get_key_manager, get_session
from app.main import app
from app.vault.blob_store import BlobStore, LocalBlobStore
from app.vault.key_manager import KeyManager, LocalKeyManager


@dataclass
class VaultComponents:
    key_manager: KeyManager
    blob_store: BlobStore


@pytest.fixture
def vault_components(tmp_path: Path) -> VaultComponents:
    return VaultComponents(
        key_manager=LocalKeyManager(tmp_path / "master.key"),
        blob_store=LocalBlobStore(tmp_path / "blobs"),
    )


@pytest.fixture
def api_client(
    db_session: Session, vault_components: VaultComponents
) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_key_manager] = lambda: vault_components.key_manager
    app.dependency_overrides[get_blob_store] = lambda: vault_components.blob_store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
