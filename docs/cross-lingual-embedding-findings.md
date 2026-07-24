# Cross-lingual embedding capability findings

Status: local contract implemented; live capability probe pending the
deployment's confirmed QuickML embedding endpoint.

The application uses QuickMLMultilingualProvider with:

- request batch: JSON texts plus configured model;
- response: JSON embeddings, one numeric vector per input;
- validation: exact vector count, consistent positive dimension, non-zero
  vectors, finite request timeout, and configured batch limit;
- output report: status, model, dimension, batch size, and latency only.

Run the redacted probe after configuring the endpoint in the Catalyst
environment:

    QUICKML_EMBEDDINGS_ENDPOINT='https://<confirmed-embedding-endpoint>' \
    QUICKML_ORG_ID='<organization-id>' \
    python -m tools.probe_embeddings --language-fixture

No token, narrative, request header, or response body is written to this
document or printed by the probe. A failed probe blocks enabling the live
QuickML provider, but the deterministic local provider remains available for
offline tests and replay.
