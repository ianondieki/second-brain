"""The research agent, prototype (REQ-RES-01, REQ-RES-02; docs/spec/06 6.5; PLAN §8 P11).

The model drafts problem cards from short public excerpts saved in the repository (``sources``: fetched once at build
time with URL and date; no search or fetch at runtime); plain code decides (``checks``); a staff admin approves before
a card shows (``review``). ``pipeline`` runs one run, ``synthesis`` is its one model call, ``policy`` holds the
numbers from ``config/policy.yaml``, ``tasks`` and ``runtime`` are the job's parts (``bridge.jobs.research``).
"""
