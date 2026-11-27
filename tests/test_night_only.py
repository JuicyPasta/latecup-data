"""The publish guard does not believe a week that is open only between midnight and 05:00.

OpenStreetMap had OneZo Tapioca in Cambridge (n11538149918) as "Mo-Su 00:00-02:00" on 2026-11-27: noon to
2 AM, most likely. The national build read it as open two hours a night and put it on the late map.
"""
from latecup_data import build as B, hours as H


def test_a_week_open_only_after_midnight_is_not_believed():
    assert B.suspicious(H.parse("Mo-Su 00:00-02:00")) == "open only between midnight and 05:00"
    assert B.suspicious([[[0, 120]], [], [], [], [[30, 300]], [], []]) == "open only between midnight and 05:00"


def test_a_late_week_is_believed_however_it_is_written():
    assert B.suspicious(H.parse("Mo-Su 12:00-02:00")) is None             # the same shop, as it probably is
    assert B.suspicious([[[1320, 1560]]] * 7) is None                     # 22:00 to 02:00, written on its own day
    assert B.suspicious([[[0, 120], [720, 1440]]] * 7) is None            # ... and written as a tail and an evening
    assert B.suspicious([[[0, 1440]]] * 7) is None                        # open 24 hours
    assert B.suspicious([[[0, 330]]] * 7) is None                         # runs past 05:00: an early bakery, not a slip


def test_an_empty_week_is_somebody_elses_question():
    assert B.suspicious([[], [], [], [], [], [], []]) is None
