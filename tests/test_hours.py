import pytest

from latecup_data import hours as H

ALL = lambda spans: [spans] * 7  # noqa: E731


@pytest.mark.parametrize("text,table", [
    ("24/7", ALL([[0, 1440]])),
    ("Mo-Su 08:00-20:00", ALL([[480, 1200]])),
    ("08:00-20:00", ALL([[480, 1200]])),
    ("Mo-Fr 07:00-19:00; Sa-Su 08:00-18:00", [[[420, 1140]]] * 5 + [[[480, 1080]]] * 2),
    ("Mo-Fr 07:00-19:00; Sa, Su 08:00-18:00", [[[420, 1140]]] * 5 + [[[480, 1080]]] * 2),
    ("Mo-Fr 07:00-19:00, Sa-Su 08:00-18:00", [[[420, 1140]]] * 5 + [[[480, 1080]]] * 2),
    ("Mo-Th 08:00-24:00; Fr-Sa 08:00-01:00; Su 09:00-22:00",
     [[[480, 1440]]] * 4 + [[[480, 1500]]] * 2 + [[[540, 1320]]]),
    ("Su-Th 07:00-00:00; Fr-Sa 07:00-02:00", [[[420, 1440]]] * 4 + [[[420, 1560]]] * 2 + [[[420, 1440]]]),
    ("Mo-Sa 09:00-13:00,14:00-21:00", [[[540, 780], [840, 1260]]] * 6 + [[]]),
    ("Mo-Fr 08:00-17:00; We off", [[[480, 1020]]] * 2 + [[]] + [[[480, 1020]]] * 2 + [[], []]),
    ("Mo-Su 08:00-22:00; PH off", ALL([[480, 1320]])),
    ("Mo-Fr,PH 08:00-22:00", [[[480, 1320]]] * 5 + [[], []]),
    ("Mo-Su 08:00-22:00; Dec 25 off; Jan 1 off", ALL([[480, 1320]])),
    ("mo-fr 7:00-21:00", [[[420, 1260]]] * 5 + [[], []]),
    ("Mon-Fri 07:00-21:00", [[[420, 1260]]] * 5 + [[], []]),
    ("Fr-Mo 10:00-22:00", [[[600, 1320]]] + [[]] * 3 + [[[600, 1320]]] * 3),
    ("Mo-Su 08:00-17:00, We-Sa 17:00-22:00", [[[480, 1020]]] * 2 + [[[480, 1320]]] * 4 + [[[480, 1020]]]),
    ("Mo-Su 00:00-24:00", ALL([[0, 1440]])),
    ("Mo-Fr 06:00-26:00", [[[360, 1560]]] * 5 + [[], []]),
    ("Mo closed, Tu-Su 08:00-20:00", [[]] + [[[480, 1200]]] * 6),
    ("Mo-Fr 08:00–20:00", [[[480, 1200]]] * 5 + [[], []]),          # an en dash
    ("Mo-Su 08:00-20:00;", ALL([[480, 1200]])),
])
def test_parse(text, table):
    assert H.parse(text) == table


@pytest.mark.parametrize("text", [
    "", "  ", "unknown", "Mo-Su unknown",
    "Mo-Su sunrise-sunset", "Mo-Fr 07:00-(sunset-03:00)",
    "Mo-Fr 17:00-23:00+", "Mo-Su 00:00+", "Mo-Su 08:00",
    'Mo-Su 08:00-16:00 "cafe" || Mo-Su 17:00-23:00 "bar"',
    'Mo-Fr 08:00-20:00 "kitchen closes at 19"',
    "Jun-Aug Mo-Su 08:00-22:00; Sep-May Mo-Su 08:00-18:00",
    "Mo-Fr 07:00-18:00; Nov Th[4] off",
    "week 1-26 Mo-Su 08:00-20:00",
    "06:00-22:00;05:30-22:00",
    "Mo-Fr",
    "Mo-Fr 10:00-10:00",
    "Mo-Fr 08:00-20:00 off",
    "Mo-Fr 25:00-26:00",
    "Mo-Fr 08:00-20:61",
    "by appointment",
    "Mo-Fr 8am-8pm",
    "Mo[1] 08:00-20:00",
])
def test_not_certain(text):
    with pytest.raises(H.Unparsed):
        H.parse(text)


def test_spill_is_clipped_at_the_next_opening():
    # Fri runs to 09:00 Saturday on paper, but Saturday opens at 08:00: one chain
    table = H.parse("Fr 20:00-09:00; Sa 08:00-12:00")
    assert table[4] == [[1200, 1920]] and table[5] == [[480, 720]]


def test_stretches_follow_the_chain():
    assert H.stretches(H.parse("24/7")) == [(0, 0, 10080)]
    table = H.parse("Fr 18:00-24:00; Sa 00:00-03:00")
    assert H.stretches(table) == [(4, 1080, 1620)]
    # Sunday night wraps into Monday morning
    table = H.parse("Su 20:00-24:00; Mo 00:00-02:00")
    assert H.stretches(table) == [(6, 1200, 1560)]


@pytest.mark.parametrize("text,close,late", [
    ("Mo-Su 07:00-19:00", 1140, False),
    ("Mo-Su 07:00-19:59", 1199, False),
    ("Mo-Th 07:00-19:00; Fr 07:00-20:00", 1200, True),
    ("Mo-Su 07:00-23:00", 1380, True),
    ("Mo-Su 07:00-02:00", 1560, True),
    ("Mo-Su 00:00-02:00,10:00-18:00", 1560, True),   # open after midnight: late
    ("Mo-Su 04:00-12:00", 1740, True),               # open before 05:00: an all-night spot by the app's rule
    ("Mo-Su 05:00-12:00", 720, False),
    ("24/7", 1740, True),
    ("Mo-Su 18:00-06:00", 1740, True),
])
def test_latest_close(text, close, late):
    table = H.parse(text)
    assert H.latest_close(table) == close
    assert H.is_late(table) is late


def test_is_24_7():
    assert H.is_24_7(H.parse("24/7"))
    assert H.is_24_7(H.parse("Mo-Su 00:00-24:00"))
    assert not H.is_24_7(H.parse("Mo-Sa 00:00-24:00"))


def test_normalize_merges_and_sorts():
    assert H.normalize([[[600, 700], [480, 620]], [], [], [], [], [], []])[0] == [[480, 700]]
