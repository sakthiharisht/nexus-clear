"""Pydantic models for a rule pack file (rules/tx_bcbstx_lpc.yaml).

Mirrors SPEC.md section 6. Every rule's `params` dict must match the shape
its `kind` expects — see the per-kind `*Params` models below and
`Rule.parsed_params()`. `RulePack.model_validate()` is where a malformed
pack is rejected (CLAUDE.md / SPEC.md M1 accept criterion); app/rules/loader.py
is a thin YAML-reading wrapper around it.

Known rule-pack design issue (flagged for the SPEC.md change proposal): the
`registry_check` kind is used with three different `params` shapes in the
seed pack (R-SUP-001: tool+subject+expect_status; R-ID-002: tool+expect list;
R-EXC-001: tool+on_possible_match). `RegistryCheckParams` below accepts the
union of all three rather than one coherent shape, which pushes the real
branching into the kind evaluator (app/rules/kinds.py) instead of the schema.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.core.contracts import Severity

RuleKind = Literal[
    "doc_type_match",
    "legibility",
    "enum_match",
    "date_not_expired",
    "date_expiring_soon",
    "name_match",
    "registry_check",
    "numeric_max",
    "numeric_min_pair",
    "presence_all",
    "history_gap",
    "checksum",
    "path_route",
    "injection_flag",
]

ChecksumAlgorithm = Literal["npi_luhn_80840"]
ApplicationPath = Literal["CAQH", "TSCA"]


class _StrictModel(BaseModel):
    """Base for every model in this file: unknown keys are a load error, not
    silently ignored (a typo'd field in the rule pack should fail loudly)."""

    model_config = ConfigDict(extra="forbid")


class DocTypeMatchParams(_StrictModel):
    pass


class LegibilityParams(_StrictModel):
    min_score: float


class EnumMatchParams(_StrictModel):
    field: str
    allowed: list[str]
    rejected: list[str] = []


class DateNotExpiredParams(_StrictModel):
    field: str
    as_of: Literal["target_date"]
    # Only used when the rule also gates on a status field (e.g. license
    # status must be "Active"); not every date_not_expired rule has one.
    status_field: str | None = None
    active_values: list[str] | None = None


class DateExpiringSoonParams(_StrictModel):
    field: str
    as_of: Literal["target_date"]
    within_days: int


class NameMatchParams(_StrictModel):
    left: str
    right: str
    alt_right: str | None = None
    min_probability: float


class RegistryCheckParams(_StrictModel):
    tool: str
    subject: str | None = None
    expect_status: str | None = None
    expect: list[str] | None = None
    on_possible_match: str | None = None


class NumericMaxParams(_StrictModel):
    field: str
    max: float


class NumericMinPairParams(_StrictModel):
    fields: list[str]
    mins: list[float]

    @model_validator(mode="after")
    def _lengths_match(self) -> "NumericMinPairParams":
        if len(self.fields) != len(self.mins):
            raise ValueError(
                f"fields ({len(self.fields)}) and mins ({len(self.mins)}) must be the same length"
            )
        return self


class PresenceAllParams(_StrictModel):
    fields: list[str]


class HistoryGapParams(_StrictModel):
    min_years: float
    max_gap_months: int
    field: str


class ChecksumParams(_StrictModel):
    field: str
    algorithm: ChecksumAlgorithm


class PathRouteParams(_StrictModel):
    path: ApplicationPath
    fallback: ApplicationPath


class InjectionFlagParams(_StrictModel):
    pass


_PARAMS_MODEL_BY_KIND: dict[RuleKind, type[_StrictModel]] = {
    "doc_type_match": DocTypeMatchParams,
    "legibility": LegibilityParams,
    "enum_match": EnumMatchParams,
    "date_not_expired": DateNotExpiredParams,
    "date_expiring_soon": DateExpiringSoonParams,
    "name_match": NameMatchParams,
    "registry_check": RegistryCheckParams,
    "numeric_max": NumericMaxParams,
    "numeric_min_pair": NumericMinPairParams,
    "presence_all": PresenceAllParams,
    "history_gap": HistoryGapParams,
    "checksum": ChecksumParams,
    "path_route": PathRouteParams,
    "injection_flag": InjectionFlagParams,
}


class AppliesWhen(_StrictModel):
    """Gates a rule to a subset of cases (e.g. Associate-only rules). A rule
    whose gate does not match always evaluates to `not_applicable`, never
    `fail` (SPEC.md section 6)."""

    field: str
    equals: str | bool | int | float


class Rule(_StrictModel):
    id: str
    title: str
    severity: Severity
    kind: RuleKind
    params: dict[str, object]
    source: str
    needs_verification: bool
    applies_when: AppliesWhen | None = None
    note: str | None = None

    def parsed_params(self) -> _StrictModel:
        """The strongly-typed params model for this rule's `kind`. Raises
        pydantic.ValidationError if `params` doesn't match that kind's shape.
        """
        model_cls = _PARAMS_MODEL_BY_KIND[self.kind]
        return model_cls.model_validate(self.params)

    @model_validator(mode="after")
    def _params_match_kind(self) -> "Rule":
        try:
            self.parsed_params()
        except ValidationError as exc:
            raise ValueError(
                f"rule {self.id}: params do not match kind {self.kind!r}: {exc}"
            ) from exc
        return self


class Source(_StrictModel):
    url: str | None = None
    doc_date: str | None = None
    last_verified: str
    notes: str


class RequiredSlot(_StrictModel):
    slot: str
    doc_type: str
    required: bool
    source: str
    needs_verification: bool


class RulePack(_StrictModel):
    pack_id: str
    version: str
    jurisdiction: str
    payer: str
    provider_type: str
    application_path: ApplicationPath
    target_date_default_offset_days: int
    sources: dict[str, Source]
    required_slots: list[RequiredSlot]
    rules: list[Rule]

    @model_validator(mode="after")
    def _check_cross_references(self) -> "RulePack":
        errors: list[str] = []

        seen_rule_ids: set[str] = set()
        for rule in self.rules:
            if rule.id in seen_rule_ids:
                errors.append(f"duplicate rule id: {rule.id}")
            seen_rule_ids.add(rule.id)
            if rule.source not in self.sources:
                errors.append(f"rule {rule.id} references unknown source {rule.source!r}")

        seen_slots: set[str] = set()
        for slot in self.required_slots:
            if slot.slot in seen_slots:
                errors.append(f"duplicate required_slot: {slot.slot}")
            seen_slots.add(slot.slot)
            if slot.source not in self.sources:
                errors.append(
                    f"required_slot {slot.slot} references unknown source {slot.source!r}"
                )

        if errors:
            raise ValueError("; ".join(errors))
        return self
