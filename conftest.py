"""Test-wide setup that must run BEFORE any backend module is imported.

The live workspace is a persistent FILE by default (`config.RECORD_STORE_PATH`) so booked
meetings, submitted claims and triaged threads survive a server restart. The test suite
imports the FastAPI app, and the shared store is built at import time — so without this,
`pytest` would write its records straight into the real workspace and leave them there
(it did: a run left six "Sync" meetings behind before this file existed).

Forcing (not defaulting) the in-memory store keeps tests isolated and reproducible, and
matches CLAUDE.md §3.4 — evaluation and tests never depend on accumulated local state.
pytest imports conftest.py before collecting test modules, which is what makes this work.
"""
import os

os.environ["RECORD_STORE_PATH"] = ":memory:"
