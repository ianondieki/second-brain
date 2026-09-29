"""The provenance fixtures (local test TSA, signing key, key wrapper, evidence store, sessions), so the proposal tests
can run the registration pipeline on what the API publishes."""

from tests.integration.provenance.conftest import (  # noqa: F401
    kek,
    local_tsa,
    sessions,
    signer,
    store,
    tsa,
    wrapper,
)
