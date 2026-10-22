from html.parser import HTMLParser

import pytest
from django.template import Template
from django.template.context import RequestContext
from django.utils.translation import gettext_lazy
from example.models import User

from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.sites import UnfoldAdminSite
from unfold.utils import display_for_label


class LabelParser(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.labels = []
        self.in_label = False
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "span" and "uppercase" in classes:
            self.labels.append({"classes": classes, "text": ""})
            self.in_label = True

    def handle_endtag(self, tag):
        if tag == "span":
            self.in_label = False

    def handle_data(self, data):
        if self.in_label:
            self.labels[-1]["text"] += data.strip()


@pytest.mark.parametrize(
    ("variant", "color_class"),
    [
        ("default", "bg-base-500/8"),
        ("primary", "bg-primary-100"),
        ("success", "bg-green-100"),
        ("info", "bg-blue-100"),
        ("warning", "bg-orange-100"),
        ("danger", "bg-red-100"),
    ],
)
def test_label_pair_variant(variant, color_class):
    labels = LabelParser(
        display_for_label([("state", "Status")], "-", {"state": variant})
    ).labels

    assert len(labels) == 1
    assert labels[0]["text"] == "Status"
    assert color_class in labels[0]["classes"]


def test_label_pairs_have_individual_colors_from_keys():
    labels = LabelParser(
        display_for_label(
            [("active", "Same caption"), ("revoked", "Same caption")],
            "-",
            {"active": "success", "revoked": "danger"},
        )
    ).labels

    assert [label["text"] for label in labels] == ["Same caption", "Same caption"]
    assert "bg-green-100" in labels[0]["classes"]
    assert "bg-red-100" in labels[1]["classes"]


@pytest.mark.parametrize("mapping", [{}, {"other": "danger"}, {"state": None}])
def test_label_pairs_keep_captions_without_a_color(mapping):
    labels = LabelParser(display_for_label([("state", "Status")], "-", mapping)).labels

    assert labels[0]["text"] == "Status"
    assert "bg-base-500/8" in labels[0]["classes"]


def test_label_pair_lazy_caption():
    labels = LabelParser(
        display_for_label(
            [("active", gettext_lazy("Active"))], "-", {"active": "success"}
        )
    ).labels

    assert labels[0]["text"] == "Active"
    assert "bg-green-100" in labels[0]["classes"]


def test_label_pairs_escape_captions():
    result = display_for_label(
        [("state", '<script>alert("x")</script>'), ("other", "A & B")],
        "-",
        {"state": "success"},
    )

    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert "A &amp; B" in result


@pytest.mark.parametrize("configuration", [True, {}, {"active": "success"}])
def test_empty_label_pair_list(configuration):
    assert display_for_label([], "-", configuration).strip() == "-"


@pytest.mark.parametrize(
    ("value", "configuration", "texts", "color_class"),
    [
        ("Active", True, ["Active"], "bg-base-500/8"),
        (["A", "B"], True, ["A", "B"], "bg-base-500/8"),
        (("A", "B"), True, ["A", "B"], "bg-base-500/8"),
        ([("active", "Active")], True, ["('active', 'Active')"], "bg-base-500/8"),
        ("active", {"active": "success"}, ["active"], "bg-green-100"),
        (("active", "Active"), {"active": "success"}, ["Active"], "bg-green-100"),
        (("active", ["A", "B"]), {"active": "success"}, ["A", "B"], "bg-green-100"),
    ],
)
def test_legacy_labels_keep_their_meaning(value, configuration, texts, color_class):
    labels = LabelParser(display_for_label(value, "-", configuration)).labels

    assert [label["text"] for label in labels] == texts
    assert all(color_class in label["classes"] for label in labels)


@pytest.mark.django_db
def test_label_pairs_in_changelist(rf, user_factory):
    class LabelAdmin(ModelAdmin):
        list_display = ["display_labels"]

        @display(label={"user": "info", "active": "success"})
        def display_labels(self, obj):
            return [("user", obj.username), ("active", "Active")]

    user = user_factory(username="label-user", is_staff=True, is_superuser=True)
    request = rf.get("/")
    request.user = user
    model_admin = LabelAdmin(User, UnfoldAdminSite())
    cl = model_admin.get_changelist_instance(request)
    cl.formset = None
    rendered = Template("{% load unfold_list %}{% unfold_result_list cl %}").render(
        RequestContext(request, {"cl": cl, "opts": User._meta})
    )
    labels = LabelParser(rendered).labels

    assert [label["text"] for label in labels] == ["label-user", "Active"]
    assert "bg-blue-100" in labels[0]["classes"]
    assert "bg-green-100" in labels[1]["classes"]
