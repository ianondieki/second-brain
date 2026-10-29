"""Tests never read a developer's ``backend/.env`` (P16-E1 item 7; ``make demo`` writes one with
``PAYMENT_PROVIDER=fake`` and the demo's URLs). In the test process the root conftest turns ``Settings``' env file
off; a test that starts ``python -m <module>`` runs it through ``python_module`` so the child does the same (the
child's settings then come from the environment the test passes, as in CI)."""

from __future__ import annotations

import sys


def python_module(module: str) -> list[str]:
    """The command running ``module`` as ``python -m`` does, with ``backend/.env`` unread."""
    code = (
        "import runpy; from bridge.config import Settings; Settings.model_config['env_file'] = None;"
        f" runpy.run_module({module!r}, run_name='__main__', alter_sys=True)"
    )
    return [sys.executable, "-c", code]
