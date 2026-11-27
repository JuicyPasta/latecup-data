"""The tests build in the default state, whatever the repository says on the
day: both switches off (switches.json) and New York the only live area
(areas/*.json, "live"). Turning the country on is an edit of those files and
nothing else, so it must not turn a test red; a test that wants a switch on
asks for it (run.make(..., fields=True, chains=...)).

tests/test_switches.py reads the real files."""
import pytest

from latecup_data import areas as A, switches


@pytest.fixture(autouse=True)
def default_state(monkeypatch):
    monkeypatch.setattr(switches, "load", lambda path=None: dict.fromkeys(switches.NAMES, False))
    monkeypatch.setattr(A, "live", lambda folder=None: [A.first(folder)])
