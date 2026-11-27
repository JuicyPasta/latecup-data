"""The tests build in the default state, whatever the repository says on the
day: both switches off (switches.json), New York the only live area
(areas/*.json, "live"), and none of the repository's own visitors' records
(visitors/, which the hourly job writes to without anybody reviewing it).
Turning the country on is an edit of those files and nothing else, so it
must not turn a test red; a test that wants a switch on asks for it
(run.make(..., fields=True, chains=...)), and one that wants visitors'
records hands a folder to build.load_visitors or points build.ROOT at one.

tests/test_switches.py reads the real switches.json and area files."""
import pytest

from latecup_data import areas as A, build as B, switches

REPOSITORY = B.ROOT
_load_visitors = B.load_visitors


@pytest.fixture(autouse=True)
def default_state(monkeypatch):
    monkeypatch.setattr(switches, "load", lambda path=None: dict.fromkeys(switches.NAMES, False))
    monkeypatch.setattr(A, "live", lambda folder=None: [A.first(folder)])

    def load_visitors(folder=None, area=None):
        if folder is None and B.ROOT == REPOSITORY:
            return {}, []
        return _load_visitors(folder, area)
    monkeypatch.setattr(B, "load_visitors", load_visitors)
