"""Typed evidence bundles and scope-safe merge helpers."""

import re
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple, Union


CRIMENO_RE = re.compile(r"\b\d{18}\b")
POLICY_VERSION = "access-policy-v1"


@dataclass(frozen=True)
class EvidenceBundle:
    agent_name: str
    status: str
    claims: Tuple[str, ...]
    rows_or_entities: Tuple[object, ...]
    citations: Tuple[str, ...]
    evidence_signals: Tuple[str, ...]
    confidence: float
    limitations: Tuple[str, ...]
    index_or_model_version: Union[str, Tuple[str, ...]]
    elapsed_ms: int
    policy_version: str = POLICY_VERSION

    @property
    def bundle_id(self):
        return "{0}:{1}:{2}".format(
            self.agent_name,
            self.status,
            self._version_label(),
        )

    def _version_label(self):
        version = self.index_or_model_version
        if isinstance(version, tuple):
            return "+".join(version)
        return version


def _scope_denied(bundle):
    return EvidenceBundle(
        agent_name=bundle.agent_name,
        status="scope_denied",
        claims=(),
        rows_or_entities=(),
        citations=(),
        evidence_signals=(),
        confidence=0.0,
        limitations=("Evidence bundle was removed by access policy.",),
        index_or_model_version=bundle.index_or_model_version,
        elapsed_ms=bundle.elapsed_ms,
        policy_version=bundle.policy_version,
    )


def _iter_strings(value):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for item in value.values():
            for nested in _iter_strings(item):
                yield nested
        return
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        for nested in _iter_strings(value[1]):
            yield nested
        return
    if isinstance(value, Sequence):
        for item in value:
            for nested in _iter_strings(item):
                yield nested


def _authorized_citations(rows_or_entities):
    citations = []
    for item in rows_or_entities:
        for value in _iter_strings(item):
            if CRIMENO_RE.fullmatch(value) and value not in citations:
                citations.append(value)
    return tuple(citations)


def _flatten_limitations(bundles):
    combined = []
    for bundle in bundles:
        for limitation in bundle.limitations:
            if limitation not in combined:
                combined.append(limitation)
    return combined


def _merge_claims(bundles, limitations, authorized_citations):
    claims = []
    seen = {}

    for bundle in bundles:
        for claim in bundle.claims:
            mentioned = set(CRIMENO_RE.findall(str(claim)))
            if not mentioned.issubset(set(authorized_citations)):
                message = "Unsupported case references were removed from evidence."
                if message not in limitations:
                    limitations.append(message)
                continue
            normalized = " ".join(claim.lower().split())
            negative = " not " in " {0} ".format(normalized) or normalized.startswith("not ")
            key = normalized.replace(" not ", " ").replace("not ", "")
            prior = seen.get(key)
            if prior is None:
                seen[key] = negative
                claims.append(claim)
                continue
            if prior != negative:
                claims = [item for item in claims if item.lower() != claim.lower()]
                claims = [item for item in claims if " ".join(item.lower().split()).replace(" not ", " ").replace("not ", "") != key]
                message = "Conflicting claims were removed pending verification."
                if message not in limitations:
                    limitations.append(message)
                continue
            if claim not in claims:
                claims.append(claim)

    return tuple(claims)


def filter_visible_bundle(bundle, is_visible):
    visible = tuple(item for item in bundle.rows_or_entities if is_visible(item))
    if bundle.status == "scope_denied":
        return _scope_denied(bundle)
    if bundle.rows_or_entities and len(visible) != len(bundle.rows_or_entities):
        return _scope_denied(bundle)

    allowed = _authorized_citations(bundle.rows_or_entities)
    citations = tuple(citation for citation in bundle.citations if citation in allowed)
    limitations = list(bundle.limitations)
    if len(citations) != len(bundle.citations):
        message = "Unauthorized citations were removed from the evidence bundle."
        if message not in limitations:
            limitations.append(message)

    return EvidenceBundle(
        agent_name=bundle.agent_name,
        status=bundle.status,
        claims=bundle.claims,
        rows_or_entities=bundle.rows_or_entities,
        citations=citations,
        evidence_signals=bundle.evidence_signals,
        confidence=bundle.confidence,
        limitations=tuple(limitations),
        index_or_model_version=bundle.index_or_model_version,
        elapsed_ms=bundle.elapsed_ms,
        policy_version=bundle.policy_version,
    )


def merge_bundles(bundles):
    valid = []
    for bundle in bundles:
        if not bundle.agent_name or bundle.policy_version != POLICY_VERSION:
            continue
        if bundle.status == "scope_denied":
            continue
        valid.append(bundle)

    if not valid:
        return EvidenceBundle(
            agent_name="Merged Evidence",
            status="scope_denied",
            claims=(),
            rows_or_entities=(),
            citations=(),
            evidence_signals=(),
            confidence=0.0,
            limitations=("No visible evidence bundles were available.",),
            index_or_model_version=(),
            elapsed_ms=0,
            policy_version=POLICY_VERSION,
        )

    rows_or_entities = []
    citations = []
    evidence_signals = []
    model_versions = []
    policy_versions = []
    limitations = _flatten_limitations(valid)

    for bundle in valid:
        rows_or_entities.extend(bundle.rows_or_entities)
        evidence_signals.extend(
            signal for signal in bundle.evidence_signals if signal not in evidence_signals
        )
        label = "{0}@{1}".format(bundle.agent_name, bundle._version_label())
        if label not in model_versions:
            model_versions.append(label)
        if bundle.policy_version not in policy_versions:
            policy_versions.append(bundle.policy_version)

    authorized = set(_authorized_citations(tuple(rows_or_entities)))
    for bundle in valid:
        for citation in bundle.citations:
            if citation in authorized and citation not in citations:
                citations.append(citation)
    if sum(len(bundle.citations) for bundle in valid) != len(citations):
        message = "Unauthorized citations were removed from merged evidence."
        if message not in limitations:
            limitations.append(message)

    claims = _merge_claims(valid, limitations, authorized)
    return EvidenceBundle(
        agent_name="Merged Evidence",
        status="ok",
        claims=claims,
        rows_or_entities=tuple(rows_or_entities),
        citations=tuple(citations),
        evidence_signals=tuple(evidence_signals),
        confidence=max(bundle.confidence for bundle in valid),
        limitations=tuple(limitations),
        index_or_model_version=tuple(model_versions),
        elapsed_ms=max(bundle.elapsed_ms for bundle in valid),
        policy_version=policy_versions[0] if len(policy_versions) == 1 else POLICY_VERSION,
    )
