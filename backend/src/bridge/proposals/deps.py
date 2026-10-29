"""Request dependencies of the proposal routes: the Tier-2 key wrapper, the object store, the attachment scanner, the
moderation pre-screen and the teaser embedder (``EMBEDDER``; REQ-PROP-04). Each is built from settings on first use
and kept on ``app.state`` (tests install their own there). A missing key or a refused scanner answers 503
``not_configured``: nothing is stored unencrypted or unscanned (fail closed)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from bridge.config import ConfigurationError, Settings
from bridge.crypto.envelope import KeyWrapper, key_wrapper_from_settings
from bridge.errors import ApiError
from bridge.llm import registry as registry_module
from bridge.llm.embeddings import Embedder, embedder_from_settings
from bridge.proposals.prescreen import PreScreen, RulesPreScreen
from bridge.storage.objects import ObjectStore, object_store_from_settings
from bridge.storage.scanner import Scanner, scanner_from_settings

NOT_CONFIGURED = "not_configured"


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_key_wrapper(request: Request) -> KeyWrapper:
    wrapper: KeyWrapper | None = getattr(request.app.state, "key_wrapper", None)
    if wrapper is None:
        try:
            wrapper = key_wrapper_from_settings(_settings(request))
        except ConfigurationError as exc:
            raise ApiError(503, NOT_CONFIGURED, "Proposals cannot be saved on this server yet.") from exc
        request.app.state.key_wrapper = wrapper
    return wrapper


def get_object_store(request: Request) -> ObjectStore:
    store: ObjectStore | None = getattr(request.app.state, "object_store", None)
    if store is None:
        store = object_store_from_settings(_settings(request))
        request.app.state.object_store = store
    return store


def get_scanner(request: Request) -> Scanner:
    scanner: Scanner | None = getattr(request.app.state, "scanner", None)
    if scanner is None:
        try:
            scanner = scanner_from_settings(_settings(request))
        except ConfigurationError as exc:
            raise ApiError(503, NOT_CONFIGURED, "Attachments cannot be scanned on this server yet.") from exc
        request.app.state.scanner = scanner
    return scanner


def get_prescreen(request: Request) -> PreScreen:
    prescreen: PreScreen | None = getattr(request.app.state, "prescreen", None)
    if prescreen is None:
        prescreen = RulesPreScreen()
        request.app.state.prescreen = prescreen
    return prescreen


def get_embedder(request: Request) -> Embedder:
    """The configured embedder (``EMBEDDER``: the fake in dev, tests and the demo; bge-m3 loads on first use)."""
    embedder: Embedder | None = getattr(request.app.state, "embedder", None)
    if embedder is None:
        settings = _settings(request)
        embedder = embedder_from_settings(settings, registry_module.load(settings.llm_models_file).embeddings)
        request.app.state.embedder = embedder
    return embedder


WrapperDep = Annotated[KeyWrapper, Depends(get_key_wrapper)]
StoreDep = Annotated[ObjectStore, Depends(get_object_store)]
ScannerDep = Annotated[Scanner, Depends(get_scanner)]
PreScreenDep = Annotated[PreScreen, Depends(get_prescreen)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
