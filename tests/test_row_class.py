from html.parser import HTMLParser
from http import HTTPStatus

import pytest
from django.contrib.admin import ModelAdmin as DjangoModelAdmin
from django.template import Context, RequestContext, Template
from django.urls import path, reverse
from example.models import Project

from unfold.admin import ModelAdmin
from unfold.datasets import BaseDataset
from unfold.sections import BaseSection
from unfold.sites import UnfoldAdminSite

pytestmark = pytest.mark.django_db


class ProjectRowAdmin(ModelAdmin):
    actions = []
    list_display = ("name",)
    list_display_links = None

    def get_row_class(self, request, obj):
        if obj.name == "Plain project":
            return ""
        prefix = request.headers.get("X-Row-Prefix", "default")
        return f"request-{prefix} project-{obj.pk}"


class RowParser(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.rows = []
        self.current_row = None
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.current_row = {"attrs": attrs, "text": "", "inputs": []}
            self.rows.append(self.current_row)
        if tag == "input" and self.current_row is not None:
            self.current_row["inputs"].append(attrs)

    def handle_endtag(self, tag):
        if tag == "tr":
            self.current_row = None

    def handle_data(self, data):
        if self.current_row is not None:
            self.current_row["text"] += data

    @property
    def data_rows(self):
        return [
            row
            for row in self.rows
            if "data-row" in row["attrs"].get("class", "").split()
        ]


def render_list(model_admin, request, editable=False):
    cl = model_admin.get_changelist_instance(request)
    if editable:
        formset = model_admin.get_changelist_formset(request)
        cl.formset = formset(queryset=cl.result_list)
    else:
        cl.formset = None
    return Template("{% load unfold_list %}{% unfold_result_list cl %}").render(
        RequestContext(request, {"cl": cl, "opts": Project._meta})
    )


@pytest.mark.parametrize("editable", [False, True])
def test_row_class_uses_request_and_object(
    settings, admin_request, project_factory, editable
):
    settings.UNFOLD = {}
    first = project_factory(name="First project")
    second = project_factory(name="Second project")
    admin_request.META["HTTP_X_ROW_PREFIX"] = "staff"
    model_admin = ProjectRowAdmin(Project, UnfoldAdminSite())
    if editable:
        model_admin.list_editable = ("name",)

    rows = RowParser(render_list(model_admin, admin_request, editable)).data_rows

    for project in (first, second):
        expected_class = f"data-row relative request-staff project-{project.pk}"
        row = next(row for row in rows if row["attrs"]["class"] == expected_class)
        if editable:
            assert any(field.get("value") == project.name for field in row["inputs"])
        else:
            assert project.name in row["text"]


def test_row_class_empty_result_does_not_inherit_previous_class(
    settings, admin_request, project_factory
):
    settings.UNFOLD = {}
    project_factory(name="Highlighted project")
    project_factory(name="Plain project")
    model_admin = ProjectRowAdmin(Project, UnfoldAdminSite())

    rows = RowParser(render_list(model_admin, admin_request)).data_rows

    plain_row = next(row for row in rows if "Plain project" in row["text"])
    highlighted = next(row for row in rows if "Highlighted project" in row["text"])
    assert plain_row["attrs"]["class"] == "data-row relative"
    assert "request-default" in highlighted["attrs"]["class"]


@pytest.mark.parametrize("admin_class", [DjangoModelAdmin, ModelAdmin])
@pytest.mark.parametrize("editable", [False, True])
def test_row_class_default_preserves_existing_classes(
    settings, admin_request, project_factory, admin_class, editable
):
    class PlainAdmin(admin_class):
        actions = []
        list_display = ("name",)
        list_display_links = None

    settings.UNFOLD = {}
    project_factory()
    model_admin = PlainAdmin(Project, UnfoldAdminSite())
    if editable:
        model_admin.list_editable = ("name",)

    rows = RowParser(render_list(model_admin, admin_request, editable)).data_rows

    assert len(rows) == 1
    assert rows[0]["attrs"]["class"] == "data-row relative"


def test_row_class_works_in_dataset(settings, admin_request, project_factory):
    class ProjectDataset(BaseDataset):
        model = Project
        model_admin = ProjectRowAdmin

    settings.UNFOLD = {}
    project = project_factory()
    admin_request.META["HTTP_X_ROW_PREFIX"] = "dataset"

    rows = RowParser(ProjectDataset(admin_request, None).contents).data_rows

    assert len(rows) == 1
    expected = f"data-row relative request-dataset project-{project.pk}"
    assert rows[0]["attrs"]["class"] == expected


def test_row_class_works_in_changelist_view(settings, admin_client, project_factory):
    settings.UNFOLD = {}
    project = project_factory()
    site = UnfoldAdminSite(name="row_admin")
    site.register(Project, ProjectRowAdmin)
    settings.ROOT_URLCONF = (path("rows/", site.urls),)

    response = admin_client.get(
        reverse("row_admin:example_project_changelist"), HTTP_X_ROW_PREFIX="view"
    )
    rows = RowParser(response.content.decode()).data_rows

    assert response.status_code == HTTPStatus.OK
    expected = f"data-row relative request-view project-{project.pk}"
    assert rows[0]["attrs"]["class"] == expected


def test_row_class_is_escaped_in_attribute(settings, admin_request, project_factory):
    class EscapedRowAdmin(ProjectRowAdmin):
        def get_row_class(self, request, obj):
            return 'custom" data-injected="yes'

    settings.UNFOLD = {}
    project_factory()
    model_admin = EscapedRowAdmin(Project, UnfoldAdminSite())

    content = render_list(model_admin, admin_request)
    row = RowParser(content).data_rows[0]

    assert "&quot;" in content
    assert row["attrs"]["class"] == 'data-row relative custom" data-injected="yes'
    assert "data-injected" not in row["attrs"]


def test_row_class_runs_once_per_displayed_object(
    settings, admin_request, project_factory
):
    calls = []

    class CountingAdmin(ProjectRowAdmin):
        def get_row_class(self, request, obj):
            calls.append((request, obj.pk))
            return "counted-row"

    settings.UNFOLD = {}
    first = project_factory()
    second = project_factory()
    model_admin = CountingAdmin(Project, UnfoldAdminSite())

    rows = RowParser(render_list(model_admin, admin_request)).data_rows

    assert all(row["attrs"]["class"] == "data-row relative counted-row" for row in rows)
    assert sorted(pk for _, pk in calls) == sorted([first.pk, second.pk])
    assert all(request is admin_request for request, _ in calls)


def test_row_class_does_not_apply_to_section_rows(
    settings, admin_request, project_factory
):
    class RelatedSection(BaseSection):
        def render(self):
            return "Related details"

    settings.UNFOLD = {}
    project_factory()
    model_admin = ProjectRowAdmin(Project, UnfoldAdminSite())
    model_admin.list_sections = (RelatedSection,)

    content = render_list(model_admin, admin_request)
    rows = RowParser(content)

    assert "Related details" in content
    assert "request-default" in rows.data_rows[0]["attrs"]["class"]
    section_rows = [row for row in rows.rows if row not in rows.data_rows]
    assert all(
        "request-default" not in row["attrs"].get("class", "") for row in section_rows
    )


def test_row_class_supports_explicit_request_in_plain_context(
    settings, admin_request, project_factory
):
    settings.UNFOLD = {}
    project = project_factory()
    admin_request.META["HTTP_X_ROW_PREFIX"] = "context"
    model_admin = ProjectRowAdmin(Project, UnfoldAdminSite())
    cl = model_admin.get_changelist_instance(admin_request)
    cl.formset = None

    content = Template("{% load unfold_list %}{% unfold_result_list cl %}").render(
        Context({"cl": cl, "opts": Project._meta, "request": admin_request})
    )
    rows = RowParser(content).data_rows

    expected = f"data-row relative request-context project-{project.pk}"
    assert rows[0]["attrs"]["class"] == expected


def test_row_class_is_not_called_for_empty_results(settings, admin_request):
    class EmptyAdmin(ProjectRowAdmin):
        def get_row_class(self, request, obj):
            raise AssertionError("No row class should be requested without an object")

    settings.UNFOLD = {}
    model_admin = EmptyAdmin(Project, UnfoldAdminSite())

    rows = RowParser(render_list(model_admin, admin_request)).data_rows

    assert not rows
