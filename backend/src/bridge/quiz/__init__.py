"""Today's five: the daily developer quiz (REQ-DEV-01; D-59; docs/platform/tasks/P22.md section A).

The model drafts five questions from a curated list of official documentation pages (``sources``); plain code decides
whether the draft becomes a set (``checks``); a staff admin approves every set before anyone sees it. ``generate``
builds the one ``quiz_generation`` call and parses its answer, ``run`` makes the call for one Nairobi day (one retry
on a discarded draft) without touching the database, ``policy`` holds the numbers from ``config/policy.yaml`` and
``fakes`` the scripted answers tests use (no provider is ever reached by ``make check``); ``models`` maps the
tables of revision 0009 (sets, questions, attempts, flags, profiles).
"""
