from html.parser import HTMLParser

import pytest
from django.template import RequestContext, Template
from django.utils.functional import lazy
from django.utils.safestring import mark_safe
from example.admin import UserAdmin
from example.models import User

from unfold.decorators import display
from unfold.sites import UnfoldAdminSite
from unfold.utils import display_for_label


class LabelParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.labels = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "span" and "rounded-default" in dict(attrs).get("class", ""):
            self.labels.append({"attrs": dict(attrs), "text": ""})
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag

    def handle_data(self, data):
        if self.stack and self.labels:
            self.labels[-1]["text"] += data


@pytest.mark.parametrize("limit", [0, -1, True, False, 2.5, "12", [], {}])
def test_label_max_length_rejects_invalid_values(limit):
    with pytest.raises(ValueError, match="label_max_length"):
        display(label=True, label_max_length=limit)(lambda obj: "Example")


@pytest.mark.parametrize(
    "caption, limit, expected, title",
    [
        ("Awaiting review", 9, "Awaiting…", "Awaiting review"),
        ("Ready", 5, "Ready", None),
        ("Ready", 6, "Ready", None),
        ("Ready", 1, "…", "Ready"),
        ("Approval", None, "Approval", None),
        ("Very long", 5, "Very…", "Very long"),
        ("Approval 😀", 9, "Approval…", "Approval 😀"),
        (123456, 4, "123…", "123456"),
    ],
)
def test_label_max_length_caption(caption, limit, expected, title):
    result = display_for_label(caption, "-", True, label_max_length=limit)
    label = LabelParser(result).labels[0]
    assert label["text"].strip() == expected
    assert label["attrs"].get("title") == title


def test_label_max_length_multiple_captions():
    result = display_for_label(
        ["Ready", "Awaiting review"], "-", True, label_max_length=8
    )
    labels = LabelParser(result).labels
    assert [item["text"].strip() for item in labels] == ["Ready", "Awaitin…"]
    assert labels[0]["attrs"].get("title") is None
    assert labels[1]["attrs"]["title"] == "Awaiting review"


def test_label_max_length_mapped_caption():
    result = display_for_label(
        ("pending", "Awaiting review"), "-", {"pending": "warning"}, label_max_length=9
    )
    label = LabelParser(result).labels[0]
    assert label["text"].strip() == "Awaiting…"
    assert "bg-orange-100" in label["attrs"]["class"]
    assert label["attrs"]["title"] == "Awaiting review"


def test_label_max_length_escapes_caption_and_title():
    caption = '<script>alert("quoted")</script>'
    result = display_for_label(caption, "-", True, label_max_length=9)
    label = LabelParser(result).labels[0]
    assert label["text"].strip() == "<script>…"
    assert label["attrs"]["title"] == caption
    assert "<script>" not in result
    assert "&quot;" in result


def test_label_max_length_safe_html_remains_balanced():
    caption = mark_safe('<strong>Awaiting "review"</strong>')
    result = display_for_label(caption, "-", True, label_max_length=9)
    parser = LabelParser(result)
    assert not parser.stack
    label = parser.labels[0]
    assert label["text"].strip() == "Awaiting…"
    assert label["attrs"]["title"] == 'Awaiting "review"'
    assert "<strong>" in result


def test_label_max_length_lazy_caption():
    caption = lazy(lambda: "Awaiting review", str)()
    result = display_for_label(caption, "-", True, label_max_length=9)
    label = LabelParser(result).labels[0]
    assert label["text"].strip() == "Awaiting…"
    assert label["attrs"]["title"] == "Awaiting review"


@pytest.mark.parametrize("value", [None, "", [], ()])
def test_label_max_length_empty_values(value):
    assert display_for_label(value, "-", True, label_max_length=8).strip() == "-"


@pytest.mark.django_db
@pytest.mark.parametrize("linked", [False, True])
def test_label_max_length_admin_list(user_factory, rf, linked):
    class LabelAdmin(UserAdmin):
        list_display = ["caption"]
        list_display_links = ["caption"] if linked else []
        list_filter = []

        @display(label=True, label_max_length=9)
        def caption(self, obj):
            return "Awaiting review"

    request = rf.get("/")
    request.user = user_factory(is_superuser=True, is_staff=True)
    model_admin = LabelAdmin(User, UnfoldAdminSite())
    cl = model_admin.get_changelist_instance(request)
    cl.formset = None
    html = Template("{% load unfold_list %}{% unfold_result_list cl %}").render(
        RequestContext(request, {"cl": cl, "opts": User._meta})
    )
    assert 'title="Awaiting review"' in html
    assert "Awaiting…" in html


@pytest.mark.parametrize("caption", ["Cafe\u0301", mark_safe("<b>Cafe\u0301</b>")])
def test_label_max_length_combining_character_boundary(caption):
    result = display_for_label(caption, "-", True, label_max_length=4)
    label = LabelParser(result).labels[0]
    assert label["text"].strip() == "Cafe\u0301"
    assert label["attrs"].get("title") is None


def test_label_max_length_lazy_safe_html():
    caption = lazy(lambda: mark_safe('<b>Awaiting "review"</b>'), str)()
    result = display_for_label(caption, "-", True, label_max_length=9)
    label = LabelParser(result).labels[0]
    assert label["text"].strip() == "Awaiting…"
    assert label["attrs"]["title"] == 'Awaiting "review"'
    assert "<b>" in result


def test_label_max_length_keeps_default_markup():
    value = ["Ready", "Awaiting review"]
    assert display_for_label(value, "-", True) == display_for_label(
        value, "-", True, label_max_length=None
    )
