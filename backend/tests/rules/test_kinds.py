"""One test class per rule kind: pass, fail, and unknown (where a missing
value makes the kind undecidable) — CLAUDE.md: "100% unit-tested including
not_applicable" (not_applicable itself is engine-level applies_when gating,
covered in test_engine.py; this file is the per-kind pass/fail/unknown
matrix each kind is responsible for)."""

from datetime import date

from app.rules.context import (
    CaseFacts,
    CoiFacts,
    CvFacts,
    CvPosition,
    DocumentFact,
    LicenseFacts,
    ProfileFacts,
    RegistryResult,
    SupervisionFacts,
)
from app.rules.kinds import (
    EvalContext,
    evaluate_checksum,
    evaluate_date_expiring_soon,
    evaluate_date_not_expired,
    evaluate_doc_type_match,
    evaluate_enum_match,
    evaluate_history_gap,
    evaluate_injection_flag,
    evaluate_legibility,
    evaluate_name_match,
    evaluate_numeric_max,
    evaluate_numeric_min_pair,
    evaluate_path_route,
    evaluate_presence_all,
    evaluate_registry_exclusion_check,
    evaluate_registry_flags_check,
    evaluate_registry_status_check,
)
from app.rules.schema import (
    ChecksumParams,
    DateExpiringSoonParams,
    DateNotExpiredParams,
    DocTypeMatchParams,
    EnumMatchParams,
    HistoryGapParams,
    InjectionFlagParams,
    LegibilityParams,
    NameMatchParams,
    NumericMaxParams,
    NumericMinPairParams,
    PathRouteParams,
    PresenceAllParams,
    RegistryExclusionCheckParams,
    RegistryFlagsCheckParams,
    RegistryStatusCheckParams,
)

AS_OF = date(2026, 11, 17)


def _ctx(**overrides: object) -> EvalContext:
    facts = CaseFacts(target_date=AS_OF, **overrides)  # type: ignore[arg-type]
    return EvalContext(facts=facts, as_of=AS_OF, application_path="CAQH")


# ---- per-document kinds ---------------------------------------------------


def _doc(**overrides: object) -> DocumentFact:
    base: dict[str, object] = {"doc_id": "doc-1", "slot": "license"}
    base.update(overrides)
    return DocumentFact(**base)  # type: ignore[arg-type]


class TestDocTypeMatch:
    params = DocTypeMatchParams()

    def test_pass_when_uploaded_matches_expected(self) -> None:
        doc = _doc(expected_doc_type="texas_lpc_license", uploaded_doc_type="texas_lpc_license")
        assert evaluate_doc_type_match(self.params, doc).status == "pass"

    def test_fail_when_uploaded_is_a_different_type(self) -> None:
        doc = _doc(expected_doc_type="texas_lpc_license", uploaded_doc_type="cv")
        assert evaluate_doc_type_match(self.params, doc).status == "fail"

    def test_unknown_when_not_yet_classified(self) -> None:
        doc = _doc(expected_doc_type="texas_lpc_license", uploaded_doc_type=None)
        assert evaluate_doc_type_match(self.params, doc).status == "unknown"


class TestLegibility:
    params = LegibilityParams(min_score=0.7)

    def test_pass_above_threshold(self) -> None:
        assert evaluate_legibility(self.params, _doc(legible_score=0.95)).status == "pass"

    def test_fail_below_threshold(self) -> None:
        assert evaluate_legibility(self.params, _doc(legible_score=0.2)).status == "fail"

    def test_unknown_when_not_scored(self) -> None:
        assert evaluate_legibility(self.params, _doc(legible_score=None)).status == "unknown"


class TestInjectionFlag:
    params = InjectionFlagParams()

    def test_pass_when_clean(self) -> None:
        doc = _doc(contains_injection_text=False)
        assert evaluate_injection_flag(self.params, doc).status == "pass"

    def test_fail_when_instruction_like_text_found(self) -> None:
        doc = _doc(contains_injection_text=True)
        result = evaluate_injection_flag(self.params, doc)
        assert result.status == "fail"

    def test_unknown_when_not_yet_scanned(self) -> None:
        doc = _doc(contains_injection_text=None)
        assert evaluate_injection_flag(self.params, doc).status == "unknown"


# ---- per-case kinds --------------------------------------------------------


class TestEnumMatch:
    params = EnumMatchParams(
        field="license.license_type", allowed=["LPC", "LPC-S"], rejected=["LPC Associate"]
    )

    def test_pass_when_allowed(self) -> None:
        ctx = _ctx(license=LicenseFacts(license_type="LPC"))
        assert evaluate_enum_match(self.params, ctx).status == "pass"

    def test_fail_when_rejected(self) -> None:
        ctx = _ctx(license=LicenseFacts(license_type="LPC Associate"))
        assert evaluate_enum_match(self.params, ctx).status == "fail"

    def test_unknown_when_field_missing(self) -> None:
        ctx = _ctx(license=LicenseFacts(license_type=None))
        assert evaluate_enum_match(self.params, ctx).status == "unknown"


class TestDateNotExpired:
    params_with_status = DateNotExpiredParams(
        field="license.expiration_date",
        as_of="target_date",
        status_field="license.status",
        active_values=["Active"],
    )
    params_plain = DateNotExpiredParams(field="coi.expiration_date", as_of="target_date")

    def test_pass_when_future_and_active(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=date(2027, 1, 1), status="Active"))
        assert evaluate_date_not_expired(self.params_with_status, ctx).status == "pass"

    def test_fail_when_expired(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=date(2020, 1, 1), status="Active"))
        assert evaluate_date_not_expired(self.params_with_status, ctx).status == "fail"

    def test_fail_when_status_not_active_even_if_not_expired(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=date(2030, 1, 1), status="Suspended"))
        assert evaluate_date_not_expired(self.params_with_status, ctx).status == "fail"

    def test_unknown_when_expiration_missing(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=None, status="Active"))
        assert evaluate_date_not_expired(self.params_with_status, ctx).status == "unknown"

    def test_unknown_when_status_field_missing(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=date(2027, 1, 1), status=None))
        assert evaluate_date_not_expired(self.params_with_status, ctx).status == "unknown"

    def test_plain_variant_without_status_field(self) -> None:
        ctx = _ctx(coi=CoiFacts(expiration_date=date(2027, 1, 1)))
        assert evaluate_date_not_expired(self.params_plain, ctx).status == "pass"

    def test_unknown_when_field_points_at_a_non_date_value(self) -> None:
        # Misconfigured rule pack: `field` resolves to a string, not a date.
        bad_params = DateNotExpiredParams(field="license.status", as_of="target_date")
        ctx = _ctx(license=LicenseFacts(status="Active"))
        assert evaluate_date_not_expired(bad_params, ctx).status == "unknown"


class TestDateExpiringSoon:
    params = DateExpiringSoonParams(
        field="license.expiration_date", as_of="target_date", within_days=90
    )

    def test_pass_when_far_in_the_future(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=date(2028, 1, 1)))
        assert evaluate_date_expiring_soon(self.params, ctx).status == "pass"

    def test_fail_when_within_window(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=date(2026, 12, 1)))
        assert evaluate_date_expiring_soon(self.params, ctx).status == "fail"

    def test_unknown_when_missing(self) -> None:
        ctx = _ctx(license=LicenseFacts(expiration_date=None))
        assert evaluate_date_expiring_soon(self.params, ctx).status == "unknown"


class TestNameMatch:
    params = NameMatchParams(
        left="license.holder_name", right="profile.legal_name", min_probability=0.9
    )

    def test_pass_when_resolved_probability_above_threshold(self) -> None:
        ctx = _ctx(
            license=LicenseFacts(holder_name="Jonathan Smith"),
            profile=ProfileFacts(legal_name="Jon Smith"),
        )
        ctx.facts.name_match_probabilities["R-LIC-004"] = 0.95
        result = evaluate_name_match("R-LIC-004", self.params, ctx)
        assert result.status == "pass"
        assert result.confidence == 0.95

    def test_fail_when_resolved_probability_below_threshold(self) -> None:
        ctx = _ctx(
            license=LicenseFacts(holder_name="John Smyth"),
            profile=ProfileFacts(legal_name="Jon Smith"),
        )
        ctx.facts.name_match_probabilities["R-LIC-004"] = 0.2
        assert evaluate_name_match("R-LIC-004", self.params, ctx).status == "fail"

    def test_unknown_when_not_yet_resolved(self) -> None:
        ctx = _ctx(
            license=LicenseFacts(holder_name="Jon Smith"),
            profile=ProfileFacts(legal_name="Jon Smith"),
        )
        assert evaluate_name_match("R-LIC-004", self.params, ctx).status == "unknown"


class TestRegistryStatusCheck:
    params = RegistryStatusCheckParams(
        tool="tx_license_lookup", subject="supervisor", expect_status="Active"
    )

    def test_pass_when_status_matches(self) -> None:
        ctx = _ctx()
        ctx.facts.registry_results["R-SUP-001"] = RegistryResult(status="Active")
        assert evaluate_registry_status_check("R-SUP-001", self.params, ctx).status == "pass"

    def test_fail_when_status_does_not_match(self) -> None:
        ctx = _ctx()
        ctx.facts.registry_results["R-SUP-001"] = RegistryResult(status="Expired")
        assert evaluate_registry_status_check("R-SUP-001", self.params, ctx).status == "fail"

    def test_unknown_when_no_result_resolved_yet(self) -> None:
        assert evaluate_registry_status_check("R-SUP-001", self.params, _ctx()).status == "unknown"


class TestRegistryFlagsCheck:
    params = RegistryFlagsCheckParams(
        tool="nppes_lookup", expect=["exists", "name_consistent", "taxonomy_counselor"]
    )

    def test_pass_when_all_flags_true(self) -> None:
        ctx = _ctx()
        ctx.facts.registry_results["R-ID-002"] = RegistryResult(
            checks={"exists": True, "name_consistent": True, "taxonomy_counselor": True}
        )
        assert evaluate_registry_flags_check("R-ID-002", self.params, ctx).status == "pass"

    def test_fail_when_any_flag_false(self) -> None:
        ctx = _ctx()
        ctx.facts.registry_results["R-ID-002"] = RegistryResult(
            checks={"exists": True, "name_consistent": False, "taxonomy_counselor": True}
        )
        assert evaluate_registry_flags_check("R-ID-002", self.params, ctx).status == "fail"

    def test_unknown_when_no_result_resolved_yet(self) -> None:
        assert evaluate_registry_flags_check("R-ID-002", self.params, _ctx()).status == "unknown"


class TestRegistryExclusionCheck:
    params = RegistryExclusionCheckParams(
        tool="leie_check", on_possible_match="escalate_to_reviewer"
    )

    def test_pass_when_clean(self) -> None:
        ctx = _ctx()
        ctx.facts.registry_results["R-EXC-001"] = RegistryResult(possible_match=False)
        assert evaluate_registry_exclusion_check("R-EXC-001", self.params, ctx).status == "pass"

    def test_unknown_when_hit(self) -> None:
        ctx = _ctx()
        ctx.facts.registry_results["R-EXC-001"] = RegistryResult(possible_match=True)
        assert evaluate_registry_exclusion_check("R-EXC-001", self.params, ctx).status == "unknown"

    def test_unknown_when_not_yet_checked(self) -> None:
        ctx = _ctx()
        # A result exists (the tool ran) but hasn't determined possible_match yet.
        ctx.facts.registry_results["R-EXC-001"] = RegistryResult(possible_match=None)
        assert evaluate_registry_exclusion_check("R-EXC-001", self.params, ctx).status == "unknown"

    def test_unknown_when_no_result_resolved_yet(self) -> None:
        result = evaluate_registry_exclusion_check("R-EXC-001", self.params, _ctx())
        assert result.status == "unknown"


class TestNumericMax:
    params = NumericMaxParams(field="supervision.supervisor_count", max=2)

    def test_pass(self) -> None:
        ctx = _ctx(supervision=SupervisionFacts(supervisor_count=1))
        assert evaluate_numeric_max(self.params, ctx).status == "pass"

    def test_fail(self) -> None:
        ctx = _ctx(supervision=SupervisionFacts(supervisor_count=3))
        assert evaluate_numeric_max(self.params, ctx).status == "fail"

    def test_unknown(self) -> None:
        ctx = _ctx(supervision=SupervisionFacts(supervisor_count=None))
        assert evaluate_numeric_max(self.params, ctx).status == "unknown"


class TestNumericMinPair:
    params = NumericMinPairParams(
        fields=["coi.per_occurrence", "coi.aggregate"], mins=[100_000, 300_000]
    )

    def test_pass(self) -> None:
        ctx = _ctx(coi=CoiFacts(per_occurrence=100_000, aggregate=300_000))
        assert evaluate_numeric_min_pair(self.params, ctx).status == "pass"

    def test_fail(self) -> None:
        ctx = _ctx(coi=CoiFacts(per_occurrence=50_000, aggregate=300_000))
        assert evaluate_numeric_min_pair(self.params, ctx).status == "fail"

    def test_unknown(self) -> None:
        ctx = _ctx(coi=CoiFacts(per_occurrence=None, aggregate=300_000))
        assert evaluate_numeric_min_pair(self.params, ctx).status == "unknown"


class TestPresenceAll:
    params = PresenceAllParams(
        fields=["coi.carrier", "coi.policy_number", "coi.effective_date", "coi.expiration_date"]
    )

    def test_pass_when_all_present(self) -> None:
        ctx = _ctx(
            coi=CoiFacts(
                carrier="Acme",
                policy_number="P-1",
                effective_date=date(2026, 1, 1),
                expiration_date=date(2027, 1, 1),
            )
        )
        assert evaluate_presence_all(self.params, ctx).status == "pass"

    def test_fail_when_one_missing(self) -> None:
        ctx = _ctx(
            coi=CoiFacts(
                carrier="Acme",
                policy_number=None,
                effective_date=date(2026, 1, 1),
                expiration_date=date(2027, 1, 1),
            )
        )
        assert evaluate_presence_all(self.params, ctx).status == "fail"


class TestHistoryGap:
    params = HistoryGapParams(min_years=5, max_gap_months=6, field="cv.positions")

    def test_pass_when_continuous(self) -> None:
        ctx = _ctx(
            cv=CvFacts(
                positions=[
                    CvPosition(start=date(2021, 1, 1), end=date(2023, 6, 1)),
                    CvPosition(start=date(2023, 6, 1), end=None),
                ]
            )
        )
        assert evaluate_history_gap(self.params, ctx).status == "pass"

    def test_fail_when_gap_exceeds_threshold(self) -> None:
        ctx = _ctx(
            cv=CvFacts(
                positions=[
                    CvPosition(start=date(2021, 1, 1), end=date(2021, 6, 1)),
                    # well over a 6-month gap before the next job starts
                    CvPosition(start=date(2022, 10, 1), end=None),
                ]
            )
        )
        assert evaluate_history_gap(self.params, ctx).status == "fail"

    def test_unknown_when_no_positions(self) -> None:
        ctx = _ctx(cv=CvFacts(positions=[]))
        assert evaluate_history_gap(self.params, ctx).status == "unknown"

    def test_unknown_when_a_position_has_no_start_date(self) -> None:
        ctx = _ctx(cv=CvFacts(positions=[CvPosition(start=None, end=None)]))
        assert evaluate_history_gap(self.params, ctx).status == "unknown"

    def test_fail_when_trailing_gap_after_last_job_ended(self) -> None:
        # Most recent job has a definite end date, well before as_of/target_date
        # - an unexplained gap right up to the present.
        ctx = _ctx(
            cv=CvFacts(positions=[CvPosition(start=date(2021, 1, 1), end=date(2025, 1, 1))])
        )
        assert evaluate_history_gap(self.params, ctx).status == "fail"


class TestChecksum:
    params = ChecksumParams(field="profile.npi", algorithm="npi_luhn_80840")

    def test_pass_on_cms_worked_example(self) -> None:
        # CMS "Requirements for NPI and NPI Check Digit": base 123456789 ->
        # check digit 3 -> NPI 1234567893.
        ctx = _ctx(profile=ProfileFacts(npi="1234567893"))
        assert evaluate_checksum(self.params, ctx).status == "pass"

    def test_fail_on_wrong_check_digit(self) -> None:
        ctx = _ctx(profile=ProfileFacts(npi="1234567890"))
        assert evaluate_checksum(self.params, ctx).status == "fail"

    def test_fail_on_malformed_length(self) -> None:
        ctx = _ctx(profile=ProfileFacts(npi="123456789"))
        assert evaluate_checksum(self.params, ctx).status == "fail"

    def test_unknown_when_missing(self) -> None:
        ctx = _ctx(profile=ProfileFacts(npi=None))
        assert evaluate_checksum(self.params, ctx).status == "unknown"

    def test_fail_when_field_points_at_a_non_string_value(self) -> None:
        # Misconfigured rule pack: `field` resolves to a date, not a string.
        bad_params = ChecksumParams(field="license.expiration_date", algorithm="npi_luhn_80840")
        ctx = _ctx(license=LicenseFacts(expiration_date=date(2027, 1, 1)))
        assert evaluate_checksum(bad_params, ctx).status == "fail"


class TestPathRoute:
    params = PathRouteParams(path="CAQH", fallback="TSCA")

    def test_pass_when_pack_matches(self) -> None:
        ctx = EvalContext(facts=CaseFacts(target_date=AS_OF), as_of=AS_OF, application_path="CAQH")
        assert evaluate_path_route(self.params, ctx).status == "pass"

    def test_fail_when_pack_does_not_match(self) -> None:
        ctx = EvalContext(facts=CaseFacts(target_date=AS_OF), as_of=AS_OF, application_path="TSCA")
        assert evaluate_path_route(self.params, ctx).status == "fail"
