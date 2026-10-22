import sys

import pytest
from django.utils.translation import gettext_lazy as _
from django.utils.translation import override
from djmoney.models.fields import MoneyField
from djmoney.money import Money

from unfold.utils import (
    display_for_field,
    display_for_label,
    prettify_json,
    prettify_traceback,
)


@pytest.mark.parametrize(
    "colors, color_class",
    [
        ({}, "bg-base-500/8"),
        ({"raw-state": "success"}, "bg-green-100"),
        ({"raw-state": None}, "bg-base-500/8"),
    ],
)
@pytest.mark.parametrize("text", ["Display label", _("Display label")])
def test_display_for_label_tuple_preserves_text(colors, color_class, text):
    result = display_for_label(("raw-state", text), "-", colors)

    assert "Display label" in result
    assert "raw-state" not in result
    assert color_class in result


def test_display_for_label_tuple_escapes_text_without_color():
    result = display_for_label(("raw-state", "<script>alert(1)</script>"), "-", {})

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
    assert "<script>" not in result


@pytest.mark.parametrize(
    "value, colors, expected, count",
    [
        ("Active", True, ["Active"], 1),
        ("Active", {"Active": "success"}, ["Active", "bg-green-100"], 1),
        (["First", "Second"], True, ["First", "Second"], 2),
        (("First", "Second"), True, ["First", "Second"], 2),
        ([], True, ["-"], 0),
    ],
)
def test_display_for_label_existing_formats(value, colors, expected, count):
    result = display_for_label(value, "-", colors)

    for text in expected:
        assert text in result
    assert result.count("<span") == count


def test_display_for_field_money():
    """Test that display_for_field correctly formats MoneyField values."""

    # Test with USD currency
    money_value = Money(100, "USD")
    result = display_for_field(money_value, MoneyField(), empty_value_display="-")
    assert result == "$100.00"

    # Test with EUR currency
    money_value_eur = Money(50, "EUR")
    result_eur = display_for_field(
        money_value_eur, MoneyField(), empty_value_display="-"
    )
    assert result_eur == "€50.00"

    # Test with None value
    result_none = display_for_field(None, MoneyField(), empty_value_display="-")
    assert result_none == "-"

    with override("de"):
        # Test with USD currency
        money_value = Money(100, "USD")
        result = display_for_field(money_value, MoneyField(), empty_value_display="-")
        assert result == "100,00\xa0$"

        # Test with EUR currency
        money_value_eur = Money(50, "EUR")
        result_eur = display_for_field(
            money_value_eur, MoneyField(), empty_value_display="-"
        )
        assert result_eur == "50,00\xa0€"

        # Test with None value
        result_none = display_for_field(None, MoneyField(), empty_value_display="-")
        assert result_none == "-"


def test_utils_prettify_json():
    json_value = {"key": "value"}
    result = prettify_json(json_value, None)
    assert '<div class="highlight">' in result


def test_utils_prettify_json_pygments_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "pygments", None)
    result = prettify_json(None, None)
    assert result is None


def test_utils_prettify_traceback():
    traceback = 'Traceback (most recent call last):\n  File "test_utils.py", line 1, in <module>\n    assert 0\nAssertionError'
    result = prettify_traceback(traceback)
    assert '<div class="highlight">' in result


def test_utils_prettify_traceback_pygments_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "pygments", None)
    result = prettify_traceback(None)
    assert result is None
