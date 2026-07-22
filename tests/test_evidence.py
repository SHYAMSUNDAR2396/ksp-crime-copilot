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
        model_or_index_version="test",
        policy_version="access-policy-v1",
    )

    filtered = filter_visible_bundle(bundle, lambda item: False)

    assert filtered.status == "scope_denied"
    assert filtered.claims == ()
    assert filtered.citations == ()
    assert filtered.rows_or_entities == ()
    assert "secret" not in " ".join(filtered.limitations)


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
        model_or_index_version="structured-v1",
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
        model_or_index_version="graph-v1",
        policy_version="access-policy-v1",
    )

    merged = merge_bundles((visible, denied))

    assert merged.status == "ok"
    assert merged.citations == ("111111111111111111",)
    assert merged.rows_or_entities == visible.rows_or_entities
    assert "999999999999999999" not in " ".join(merged.limitations)
    assert merged.model_or_index_version == (
        "Structured Query Agent@structured-v1",
    )
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
        model_or_index_version="structured-v1",
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
        model_or_index_version="graph-v1",
        policy_version="access-policy-v1",
    )

    merged = merge_bundles((first, second))

    assert merged.claims == ()
    assert any("Conflicting claims" in limitation for limitation in merged.limitations)
