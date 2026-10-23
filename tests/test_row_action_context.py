from html.parser import HTMLParser
from http import HTTPStatus

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import NoReverseMatch, path, reverse
from example.models import Project

from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.sites import UnfoldAdminSite

pytestmark = pytest.mark.django_db


class RowParser(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.rows = []
        self.row = None
        self.elements = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "data-row" in attrs.get("class", "").split():
            self.row = []
            self.rows.append(self.row)
        if self.row is not None:
            if tag == "td":
                self.row.append(attrs)
            if tag in ("a", "button"):
                self.elements.append((tag, attrs))

    def handle_endtag(self, tag):
        if tag == "tr":
            self.row = None


class ContextActionsAdmin(ModelAdmin):
    actions = None
    list_display = ("name",)
    list_display_links = None
    ordering = ("pk",)
    actions_row = ("inspect", "copy", "restricted")

    @action(description="Inspect project", icon="visibility")
    def inspect(self, request, object_id):
        return HttpResponse(f"Inspect {object_id}")

    @action(
        description="Copy project",
        icon="content_copy",
        attrs={"data-original": "preserved"},
        extra_options={"register_route": False},
    )
    def copy(self, request, object_id):
        pass

    @action(description="Restricted project", permissions=["restricted"])
    def restricted(self, request, object_id):
        return HttpResponse("Restricted")

    def has_restricted_permission(self, request):
        return False

    def get_row_action_context(self, request, obj, action):
        if obj.name == "Hidden":
            return None
        context = super().get_row_action_context(request, obj, action)
        context["attrs"]["data-project"] = str(obj.pk)
        context["attrs"]["data-request"] = request.headers.get("X-Marker", "default")
        if action.method.original_function_name == "copy":
            context["url"] = None
            context["attrs"]["data-copy-text"] = obj.name
            context["display_in_dropdown"] = request.headers.get("X-Inline") != "1"
            context["title"] = f"Copy {obj.name}"
            context["icon"] = "content_paste"
        return context


@pytest.fixture
def rows_admin(settings):
    settings.UNFOLD = {}
    site = UnfoldAdminSite(name="row_context")
    site.register(Project, ContextActionsAdmin)
    settings.ROOT_URLCONF = (path("rows/", site.urls),)
    return site.get_model_admin(Project)


def render_rows(model_admin, request):
    response = model_admin.changelist_view(request)
    response.render()
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def test_default_hook_resolves_url(rows_admin, project_factory, admin_request):
    project = project_factory()
    context = rows_admin.get_row_action_context(
        admin_request, project, rows_admin.get_unfold_action("inspect")
    )
    assert context["url"] == f"/rows/example/project/{project.pk}/inspect/"
    assert context["title"] == "Inspect project"
    assert context["icon"] == "visibility"


def test_route_registration_is_explicit(rows_admin, project_factory, admin_client):
    project = project_factory()
    url = reverse("row_context:example_project_inspect", args=[project.pk])
    response = admin_client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert response.content.decode() == f"Inspect {project.pk}"
    with pytest.raises(NoReverseMatch):
        reverse("row_context:example_project_copy", args=[project.pk])
    # Django admin may redirect unmatched paths through its object-ID fallback.
    assert (
        admin_client.get(f"/rows/example/project/{project.pk}/copy/").status_code
        == HTTPStatus.FOUND
    )


@pytest.mark.parametrize("inline", [False, True])
def test_copy_button_and_per_object_attributes(
    rows_admin, project_factory, admin_request, inline
):
    first = project_factory(name='First "quoted" <project> & more')
    second = project_factory(name="Second")
    admin_request.META["HTTP_X_MARKER"] = "request-one"
    admin_request.META["HTTP_X_INLINE"] = "1" if inline else "0"
    content = render_rows(rows_admin, admin_request)
    parser = RowParser(content)
    buttons = [attrs for tag, attrs in parser.elements if tag == "button"]
    assert len(buttons) == len(parser.rows) == 2  # noqa: PLR2004
    assert [attrs["data-copy-text"] for attrs in buttons] == [first.name, second.name]
    assert [attrs["data-project"] for attrs in buttons] == [
        str(first.pk),
        str(second.pk),
    ]
    assert all(attrs["type"] == "button" for attrs in buttons)
    assert all("href" not in attrs and "hx-get" not in attrs for attrs in buttons)
    assert all(attrs["data-original"] == "preserved" for attrs in buttons)
    assert all(attrs["data-request"] == "request-one" for attrs in buttons)
    assert "content_paste" in content
    assert "Copy First &quot;quoted&quot; &lt;project&gt; &amp; more" in content
    assert "Restricted project" not in content
    links = [attrs for tag, attrs in parser.elements if tag == "a"]
    assert {attrs["href"] for attrs in links} == {
        f"/rows/example/project/{first.pk}/inspect/",
        f"/rows/example/project/{second.pk}/inspect/",
    }


def test_hidden_actions_keep_column_alignment(
    rows_admin, project_factory, admin_request
):
    project_factory(name="Visible")
    project_factory(name="Hidden")
    parser = RowParser(render_rows(rows_admin, admin_request))
    assert [len(row) for row in parser.rows] == [2, 2]
    assert all("field-actions_holder" in row[-1]["class"] for row in parser.rows)


def test_all_hidden_actions_remove_column(rows_admin, project_factory, admin_request):
    project_factory(name="Hidden")
    content = render_rows(rows_admin, admin_request)
    assert "field-actions_holder" not in content
    assert [len(row) for row in RowParser(content).rows] == [1]


def test_context_attributes_do_not_leak_between_calls(
    rows_admin, project_factory, admin_request
):
    project = project_factory(name="First")
    copy_action = rows_admin.get_unfold_action("copy")
    first = rows_admin.get_row_action_context(admin_request, project, copy_action)
    first["attrs"]["changed"] = "only-first"
    other_request = RequestFactory().get("/", HTTP_X_MARKER="second")
    other_request.user = admin_request.user
    second = rows_admin.get_row_action_context(other_request, project, copy_action)
    assert second["attrs"]["data-request"] == "second"
    assert "changed" not in second["attrs"]
    assert copy_action.method.attrs == {"data-original": "preserved"}


def test_existing_get_actions_row_override_is_respected(
    rows_admin, project_factory, admin_request, monkeypatch
):
    project_factory(name="Visible")
    original = rows_admin.get_actions_row

    def only_copy(request):
        return [
            item
            for item in original(request)
            if item.method.original_function_name == "copy"
        ]

    monkeypatch.setattr(rows_admin, "get_actions_row", only_copy)
    parser = RowParser(render_rows(rows_admin, admin_request))
    assert [tag for tag, attrs in parser.elements] == ["button"]


def test_custom_parent_url_without_child_route(
    rows_admin, project_factory, admin_request, admin_client, settings, monkeypatch
):
    project = project_factory(name="Visible")

    def parent_view(request, parent_id, child_id):
        return HttpResponse(f"Parent {parent_id}, child {child_id}")

    settings.ROOT_URLCONF = (
        path(
            "parent/<int:parent_id>/child/<int:child_id>/",
            parent_view,
            name="parent-action",
        ),
        path("rows/", rows_admin.admin_site.urls),
    )
    original = rows_admin.get_row_action_context

    def parent_context(request, obj, action):
        context = original(request, obj, action)
        if action.method.original_function_name == "copy":
            context["url"] = reverse("parent-action", args=[42, obj.pk])
        return context

    monkeypatch.setattr(rows_admin, "get_row_action_context", parent_context)
    parser = RowParser(render_rows(rows_admin, admin_request))
    custom_url = f"/parent/42/child/{project.pk}/"
    assert any(
        tag == "a" and attrs.get("href") == custom_url for tag, attrs in parser.elements
    )
    response = admin_client.get(custom_url)
    assert response.content.decode() == f"Parent 42, child {project.pk}"


def test_permission_filtering_runs_before_context_hook(
    rows_admin, project_factory, admin_request, admin_client, monkeypatch
):
    first = project_factory(name="First")
    second = project_factory(name="Second")
    calls = []
    original = rows_admin.get_row_action_context

    def record_context(request, obj, action):
        assert request is admin_request
        calls.append((obj.pk, action.method.original_function_name))
        return original(request, obj, action)

    monkeypatch.setattr(rows_admin, "get_row_action_context", record_context)
    render_rows(rows_admin, admin_request)
    assert calls == [
        (first.pk, "inspect"),
        (first.pk, "copy"),
        (second.pk, "inspect"),
        (second.pk, "copy"),
    ]
    response = admin_client.get(
        reverse("row_context:example_project_restricted", args=[first.pk])
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("inline", [False, True])
def test_button_attributes_preserve_boolean_values(
    rows_admin, project_factory, admin_request, monkeypatch, inline
):
    project_factory(name="Visible")
    original = rows_admin.get_row_action_context

    def custom_context(request, obj, action):
        context = original(request, obj, action)
        if action.method.original_function_name == "copy":
            context["display_in_dropdown"] = not inline
            context["attrs"].update({"disabled": True, "hidden": False})
        return context

    monkeypatch.setattr(rows_admin, "get_row_action_context", custom_context)
    parser = RowParser(render_rows(rows_admin, admin_request))
    button = next(attrs for tag, attrs in parser.elements if tag == "button")
    assert "disabled" in button
    assert "hidden" not in button


@pytest.mark.parametrize("inline", [False, True])
def test_action_attributes_are_not_duplicated(
    rows_admin, project_factory, admin_request, inline
):
    project_factory(name="Visible")
    admin_request.META["HTTP_X_INLINE"] = "1" if inline else "0"
    content = render_rows(rows_admin, admin_request)
    assert content.count('data-copy-text="Visible"') == 1


def test_hidden_row_contains_no_actions(rows_admin, project_factory, admin_request):
    visible = project_factory(name="Visible")
    hidden = project_factory(name="Hidden")
    parser = RowParser(render_rows(rows_admin, admin_request))
    assert [len(row) for row in parser.rows] == [2, 2]
    assert {attrs["data-project"] for tag, attrs in parser.elements} == {
        str(visible.pk)
    }
    assert all(
        attrs.get("data-project") != str(hidden.pk) for tag, attrs in parser.elements
    )


def test_default_context_can_render_without_any_registered_urls(
    admin_request, project_factory
):
    model_admin = ContextActionsAdmin(Project, UnfoldAdminSite(name="not_registered"))
    project = project_factory(name="Visible")
    context = model_admin.get_row_action_context(
        admin_request, project, model_admin.get_unfold_action("copy")
    )
    assert context["url"] is None
    assert context["attrs"]["data-copy-text"] == "Visible"


def test_legacy_template_context_keeps_action_declarations(
    rows_admin, project_factory, admin_request
):
    from unfold.templatetags.unfold_list import result_list

    project_factory(name="Visible")
    response = rows_admin.changelist_view(admin_request)
    context = result_list(
        {**response.context_data, "request": admin_request}, response.context_data["cl"]
    )
    declarations = context["actions_row"]
    assert isinstance(declarations, list)
    assert declarations[0]["raw_path"] == "row_context:example_project_inspect"
    assert declarations[0]["title"] == "Inspect project"


@pytest.mark.parametrize("inline", [False, True])
def test_legacy_helper_accepts_raw_path_context(rows_admin, project_factory, inline):
    from django.template.loader import render_to_string

    project = project_factory()
    content = render_to_string(
        "unfold/helpers/actions_row.html",
        {
            "instance_pk": project.pk,
            "actions": [
                {
                    "raw_path": "row_context:example_project_inspect",
                    "title": "Legacy inspect",
                    "display_in_dropdown": not inline,
                    "attrs": {},
                }
            ],
        },
    )
    assert f'href="/rows/example/project/{project.pk}/inspect/"' in content
    assert "Legacy inspect" in content


def test_legacy_declaration_postprocessing_is_preserved(
    rows_admin, project_factory, admin_request
):
    project = project_factory(name="Visible")
    response = rows_admin.changelist_view(admin_request)
    declaration = response.context_data["actions_row"][0]
    declaration["title"] = "Updated inspect"
    declaration["icon"] = "star"
    declaration["attrs"]["data-legacy"] = "preserved"
    declaration["raw_path"] = "row_context:example_project_change"
    response.context_data["actions_row"][1]["attrs"]["data-legacy"] = "copy-legacy"
    del response.context_data["actions_row"][1]["attrs"]["data-original"]
    response.render()
    content = response.content.decode()
    assert "Updated inspect" in content
    assert "star" in content
    assert 'data-legacy="preserved"' in content
    assert f'href="/rows/example/project/{project.pk}/change/"' in content
    parser = RowParser(content)
    button = next(attrs for tag, attrs in parser.elements if tag == "button")
    assert button["data-legacy"] == "copy-legacy"
    assert button["data-project"] == str(project.pk)
    assert button["data-copy-text"] == "Visible"
    assert "data-original" not in button


@pytest.mark.parametrize("inline", [False, True])
def test_action_css_classes_extend_existing_styles(
    rows_admin, project_factory, admin_request, monkeypatch, inline
):
    project_factory(name="Visible")
    original = rows_admin.get_row_action_context

    def custom_context(request, obj, action):
        context = original(request, obj, action)
        if action.method.original_function_name == "copy":
            context["display_in_dropdown"] = not inline
            context["attrs"]["class"] = "copy-handler"
        return context

    monkeypatch.setattr(rows_admin, "get_row_action_context", custom_context)
    parser = RowParser(render_rows(rows_admin, admin_request))
    button = next(attrs for tag, attrs in parser.elements if tag == "button")
    classes = button["class"].split()
    assert "copy-handler" in classes
    assert "items-center" in classes


def test_dialog_keeps_row_url_and_buttons_do_not_open_dialogs(
    rows_admin, project_factory, admin_request, monkeypatch
):
    project = project_factory(name="Visible")
    original = rows_admin.get_row_action_context

    def with_dialog(request, obj, action):
        context = original(request, obj, action)
        context["dialog"] = {"title": "Confirm action"}
        return context

    monkeypatch.setattr(rows_admin, "get_row_action_context", with_dialog)
    parser = RowParser(render_rows(rows_admin, admin_request))
    link = next(attrs for tag, attrs in parser.elements if tag == "a")
    assert (
        link["href"] == link["hx-get"] == f"/rows/example/project/{project.pk}/inspect/"
    )
    assert link["hx-target"] == "#modal-content"
    button = next(attrs for tag, attrs in parser.elements if tag == "button")
    assert "hx-get" not in button
    assert "x-on:htmx:after-on-load" not in button
