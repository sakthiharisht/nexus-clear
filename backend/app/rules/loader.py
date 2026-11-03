"""Load and validate a rule pack YAML file against app/rules/schema.py.

M1 accept criterion: the loader rejects malformed packs.
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.rules.schema import RulePack


class RulePackError(Exception):
    """A rule pack file is missing, not YAML, or fails schema validation."""


def load_rule_pack(path: str | Path) -> RulePack:
    pack_path = Path(path)

    try:
        text = pack_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RulePackError(f"{pack_path}: could not read rule pack: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulePackError(f"{pack_path}: not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise RulePackError(f"{pack_path}: rule pack must be a YAML mapping at the top level")

    try:
        return RulePack.model_validate(raw)
    except ValidationError as exc:
        raise RulePackError(f"{pack_path}: rule pack failed validation:\n{exc}") from exc
