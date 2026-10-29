"""Fixtures of the problem and research tests (REQ-RES-01, REQ-RES-02), and This week's module database for the trend
tests (REQ-DEV-02: ``tests/integration/events/conftest.py``)."""

from tests.integration.events.conftest import as_user, week, week_url
from tests.integration.problems.research_rig import research_world

__all__ = ["as_user", "research_world", "week", "week_url"]
