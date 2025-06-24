import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cogs.math import MathCog
from cogs.potd import PotdCog


def test_convert_tags_math():
    assert MathCog._convert_tags("<math>x+1</math>") == "$x+1$"


def test_convert_tags_asy():
    txt = "pre <asy>draw((0,0)--(1,0));</asy> post"
    expected = "pre [asy]draw((0,0)--(1,0));[/asy] post"
    assert MathCog._convert_tags(txt) == expected


def test_ordinal():
    assert PotdCog._ordinal(1) == "1st"
    assert PotdCog._ordinal(2) == "2nd"
    assert PotdCog._ordinal(3) == "3rd"
    assert PotdCog._ordinal(4) == "4th"
    assert PotdCog._ordinal(11) == "11th"
    assert PotdCog._ordinal(21) == "21st"


def test_convert_tags_case_insensitive():
    assert MathCog._convert_tags("<MATH>x</MATH>") == "$x$"


def test_parse_date():
    d = PotdCog._parse_date("6/24/25")
    assert d.year == 2025 and d.month == 6 and d.day == 24
    assert PotdCog._parse_date("invalid") is None

