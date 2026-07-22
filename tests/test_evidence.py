from functions.crime_query.evidence import (
    EvidenceBundle,
    filter_visible_bundle,
    merge_bundles,
)


def test_inaccessible_bundle_is_scope_denied_without_identifiers():
    bundle = EvidenceBundle(
        agent_name="Narrative Retrieval Agent",
        status="ok",
        claims=("hidden",),
        rows_or_entities=((("CrimeNo", "secret"),),),
        citations=("secret",),
        evidence_signals=(),
        confidence=0.8,
        limitations=(),
        index_or_model_version="test",
        elapsed_ms=12,
        policy_version="access-policy-v1",
    )

    filtered = filter_visible_bundle(bundle, lambda item: False)

    assert filtered.status == "scope_denied"
    assert filtered.claims == ()
    assert filtered.citations == ()
    assert filtered.rows_or_entities == ()
    assert filtered.elapsed_ms == 12
    assert "secret" not in " ".join(filtered.limitations)


def test_mixed_visibility_bundle_is_scope_denied_without_leaking_visible_identifiers():
    bundle = EvidenceBundle(
        agent_name="Graph Agent",
        status="ok",
        claims=("linked",),
        rows_or_entities=(
            (("CrimeNo", "111111111111111111"), ("AccusedName", "Visible Person")),
            (("CrimeNo", "222222222222222222"), ("AccusedName", "Hidden Person")),
        ),
        citations=("111111111111111111", "222222222222222222"),
        evidence_signals=("graph",),
        confidence=0.7,
        limitations=(),
        index_or_model_version="graph-v1",
        elapsed_ms=25,
        policy_version="access-policy-v1",
    )

    filtered = filter_visible_bundle(bundle, lambda item: "111111111111111111" in str(item))

    assert filtered.status == "scope_denied"
    assert filtered.claims == ()
    assert filtered.rows_or_entities == ()
    assert filtered.citations == ()
    assert filtered.elapsed_ms == 25
    assert "111111111111111111" not in " ".join(filtered.limitations)
    assert "Visible Person" not in " ".join(filtered.limitations)


def test_merge_bundles_drops_scope_denied_and_unauthorized_citations():
    visible = EvidenceBundle(
        agent_name="Structured Query Agent",
        status="ok",
        claims=("Visible case found",),
        rows_or_entities=((("CrimeNo", "111111111111111111"),),),
        citations=("111111111111111111", "999999999999999999"),
        evidence_signals=("structured",),
        confidence=0.9,
        limitations=(),
        index_or_model_version="structured-v1",
        elapsed_ms=30,
        policy_version="access-policy-v1",
    )
    denied = EvidenceBundle(
        agent_name="Graph Agent",
        status="scope_denied",
        claims=("Hidden graph link",),
        rows_or_entities=((("CrimeNo", "222222222222222222"),),),
        citations=("222222222222222222",),
        evidence_signals=("graph",),
        confidence=0.4,
        limitations=("Dropped by policy",),
        index_or_model_version="graph-v1",
        elapsed_ms=20,
        policy_version="access-policy-v1",
    )

    merged = merge_bundles((visible, denied))

    assert merged.status == "ok"
    assert merged.citations == ("111111111111111111",)
    assert merged.rows_or_entities == visible.rows_or_entities
    assert "999999999999999999" not in " ".join(merged.limitations)
    assert merged.index_or_model_version == (
        "Structured Query Agent@structured-v1",
    )
    assert merged.elapsed_ms == 30
    assert merged.policy_version == "access-policy-v1"


def test_merge_bundles_records_conflicting_claims_without_averaging_them():
    first = EvidenceBundle(
        agent_name="Structured Query Agent",
        status="ok",
        claims=("Case link confirmed",),
        rows_or_entities=((("CrimeNo", "111111111111111111"),),),
        citations=("111111111111111111",),
        evidence_signals=(),
        confidence=0.9,
        limitations=(),
        index_or_model_version="structured-v1",
        elapsed_ms=10,
        policy_version="access-policy-v1",
    )
    second = EvidenceBundle(
        agent_name="Graph Agent",
        status="ok",
        claims=("Case link not confirmed",),
        rows_or_entities=((("CrimeNo", "111111111111111111"),),),
        citations=("111111111111111111",),
        evidence_signals=(),
        confidence=0.2,
        limitations=(),
        index_or_model_version="graph-v1",
        elapsed_ms=15,
        policy_version="access-policy-v1",
    )

    merged = merge_bundles((first, second))

    assert merged.claims == ()
    assert any("Conflicting claims" in limitation for limitation in merged.limitations)
