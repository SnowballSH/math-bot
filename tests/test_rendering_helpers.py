from cogs.math import MathCog


def test_convert_tags_math():
    assert MathCog._convert_tags("<math>x+1</math>") == "$x+1$"


def test_convert_tags_asy():
    txt = "pre <asy>draw((0,0)--(1,0));</asy> post"
    expected = "pre [asy]draw((0,0)--(1,0));[/asy] post"
    assert MathCog._convert_tags(txt) == expected


def test_convert_tags_case_insensitive():
    assert MathCog._convert_tags("<MATH>x</MATH>") == "$x$"
