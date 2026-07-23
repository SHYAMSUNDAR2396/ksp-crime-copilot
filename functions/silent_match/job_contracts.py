"""Validated payload contracts for silent-match scheduled/event jobs.

The Advanced I/O handler authenticates the caller and injects the trusted
policy identity before calling the API.  These validators therefore support a
``reject_identity`` switch: direct job adapters reject client identity fields,
while the API receives the already-authenticated internal envelope.
"""
import datetime as dt
import re


VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_CHANGED_CASES = 1000
_SCAN_FIELDS = frozenset({"date_window", "anchor_case_id", "trigger_source", "employee_id"})
_INDEX_FIELDS = frozenset({"index_version", "changed_case_ids", "trigger_source", "employee_id"})
_PROJECTION_FIELDS = frozenset({"projection_version", "changed_case_ids", "trigger_source", "employee_id"})


class JobContractError(ValueError):
    """Raised when a scheduled or post-ingestion payload is malformed."""


def _copy_payload(payload):
    if not isinstance(payload, dict):
        raise JobContractError("job payload must be an object")
    return dict(payload)


def _check_fields(payload, allowed, reject_identity):
    unknown = set(payload) - allowed
    if unknown:
        raise JobContractError("unsupported job field: {0}".format(sorted(unknown)[0]))
    if reject_identity and "employee_id" in payload:
        raise JobContractError("job payload must not contain employee_id")


def _positive_id(value, field):
    if isinstance(value, bool):
        raise JobContractError("{0} must be a positive integer".format(field))
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise JobContractError("{0} must be a positive integer".format(field))
    if result < 1 or str(value).strip() != str(result):
        # Accept JSON integers and canonical numeric strings only.  This
        # prevents values such as 1.5 or whitespace-padded IDs from crossing
        # into a Catalyst query literal.
        if not isinstance(value, int) or result < 1:
            raise JobContractError("{0} must be a positive integer".format(field))
    return result


def _case_ids(value):
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise JobContractError("changed_case_ids must be a list")
    if len(value) > MAX_CHANGED_CASES:
        raise JobContractError("changed_case_ids exceeds the maximum batch size")
    result = tuple(_positive_id(item, "case id") for item in value)
    if len(set(result)) != len(result):
        raise JobContractError("changed_case_ids must not contain duplicates")
    return result


def _date(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise JobContractError("{0} must be YYYY-MM-DD".format(field))
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise JobContractError("{0} must be a real calendar date".format(field))
    return parsed


def _date_window(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise JobContractError("date_window must be an ordered date window")
    start, end = _date(value[0], "date_window start"), _date(value[1], "date_window end")
    if start > end:
        raise JobContractError("date_window must be an ordered date window")
    return (start.isoformat(), end.isoformat())


def _check_trigger(trigger, expected):
    if trigger not in (None, expected):
        raise JobContractError("trigger_source must be {0}".format(expected))


def validate_scan_payload(payload, reject_identity=True):
    """Validate and normalize the batch/live scan selector contract."""
    payload = _copy_payload(payload)
    _check_fields(payload, _SCAN_FIELDS, reject_identity)
    date_window = payload.get("date_window")
    anchor_case_id = payload.get("anchor_case_id")
    if (date_window is None) == (anchor_case_id is None):
        raise JobContractError("provide exactly one scan selector")
    trigger = payload.get("trigger_source") or "batch"
    if date_window is not None:
        _check_trigger(trigger, "batch")
        normalized_window = _date_window(date_window)
        normalized_anchor = None
    else:
        _check_trigger(trigger, "live")
        normalized_window = None
        normalized_anchor = _positive_id(anchor_case_id, "anchor_case_id")
    return {
        "date_window": normalized_window,
        "anchor_case_id": normalized_anchor,
        "trigger_source": trigger,
    }


def _validate_version(payload, field):
    version = str(payload.get(field) or "").strip()
    if not VERSION_RE.fullmatch(version):
        raise JobContractError("a valid {0} is required".format(field.replace("_", " ")))
    return version


def _validate_versioned(payload, fields, version_field, reject_identity):
    payload = _copy_payload(payload)
    _check_fields(payload, fields, reject_identity)
    trigger = payload.get("trigger_source") or "scheduled"
    _check_trigger(trigger, "scheduled")
    return {
        version_field: _validate_version(payload, version_field),
        "changed_case_ids": _case_ids(payload.get("changed_case_ids")),
        "trigger_source": trigger,
    }


def validate_index_payload(payload, reject_identity=True):
    return _validate_versioned(payload, _INDEX_FIELDS, "index_version", reject_identity)


def validate_graph_projection_payload(payload, reject_identity=True):
    return _validate_versioned(
        payload, _PROJECTION_FIELDS, "projection_version", reject_identity,
    )
