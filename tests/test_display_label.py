import pytest
from django.test import SimpleTestCase

from unfold.utils import display_for_label


@pytest.mark.parametrize("values", [["Partner", "Priority"], ("Partner", "Priority")])
def test_multiple_labels_have_a_wrapping_container(values):
    result = display_for_label(values, "-", True)

    SimpleTestCase().assertInHTML(
        '<div class="flex flex-wrap gap-1">'
        '<span class="inline-block font-semibold rounded-default text-[11px] uppercase '
        "whitespace-nowrap h-6 leading-6 px-2 bg-base-500/8 text-base-700 "
        'dark:bg-base-500/20 dark:text-base-200">Partner</span>'
        '<span class="inline-block font-semibold rounded-default text-[11px] uppercase '
        "whitespace-nowrap h-6 leading-6 px-2 bg-base-500/8 text-base-700 "
        'dark:bg-base-500/20 dark:text-base-200">Priority</span>'
        "</div>",
        result,
    )


@pytest.mark.parametrize("value", ["Partner", ("partner", "Partner")])
def test_single_label_keeps_its_color_and_has_no_container(value):
    result = display_for_label(value, "-", {"Partner": "success", "partner": "success"})

    assert "<div" not in result
    assert result.count("<span") == 1
    assert "bg-green-100" in result
    assert ">Partner</span>" in "".join(line.strip() for line in result.splitlines())


@pytest.mark.parametrize("value", [[], (), "", None])
def test_empty_labels_keep_the_existing_placeholder(value):
    assert display_for_label(value, "-", True).strip() == "-"


def test_multiple_labels_escape_text():
    result = display_for_label(["<script>alert(1)</script>", "A & B"], "-", True)

    assert "<script>" not in result
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
    assert "A &amp; B" in result
