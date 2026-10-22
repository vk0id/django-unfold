import subprocess
import sys
from html.parser import HTMLParser
from http import HTTPStatus

import pytest
from django.contrib.admin import ModelAdmin as DjangoModelAdmin
from django.http import HttpResponse
from django.urls import path, reverse
from example.models import Project

from unfold.admin import ModelAdmin
from unfold.datasets import BaseDataset
from unfold.decorators import action
from unfold.sites import UnfoldAdminSite

pytestmark = pytest.mark.django_db


class RowActionsAdmin(ModelAdmin):
    actions = []
    actions_row = ("inspect_project", "review_project", "restricted_project")
    list_display = ("name",)
    list_display_links = None

    @action(
        description="Inspect project",
        icon="visibility",
        extra_options={"display_in_dropdown": False},
    )
    def inspect_project(self, request, object_id):
        return HttpResponse(f"Project {object_id}")

    @action(
        description="Review project",
        permissions=["review"],
        attrs={"data-action": "review"},
        dialog={"title": "Review project", "description": "Review this project"},
    )
    def review_project(self, request, object_id):
        return HttpResponse(f"Review {object_id}")

    @action(description="Restricted project", permissions=["restricted"])
    def restricted_project(self, request, object_id):
        return HttpResponse("Restricted")

    def has_review_permission(self, request):
        return request.user.is_superuser

    def has_restricted_permission(self, request):
        return False


class ProjectRowsDataset(BaseDataset):
    model = Project
    model_admin = RowActionsAdmin
    tab = True


class TableParser(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.action_cells = 0
        self.links = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "td" and "field-actions_holder" in attrs.get("class", "").split():
            self.action_cells += 1
        if tag == "a":
            self.links.append(attrs)


@pytest.fixture
def dataset_rows(settings, admin_request):
    settings.UNFOLD = {}
    site = UnfoldAdminSite(name="dataset_admin")
    site.register(Project, RowActionsAdmin)
    settings.ROOT_URLCONF = (path("rows/", site.urls),)
    dataset = ProjectRowsDataset(admin_request, None)
    dataset.model_admin_instance.admin_site = site
    return dataset


def test_dataset_row_actions_link_to_each_row(
    dataset_rows, project_factory, admin_client
):
    first = project_factory(name="First project")
    second = project_factory(name="Second project")
    projects = (first, second)

    content = dataset_rows.contents
    result = TableParser(content)

    assert "visibility" in content
    assert result.action_cells == len(projects)
    for project in projects:
        inspect_url = reverse(
            "dataset_admin:example_project_inspect_project", args=[project.pk]
        )
        review_url = reverse(
            "dataset_admin:example_project_review_project", args=[project.pk]
        )
        inline = next(link for link in result.links if link.get("href") == inspect_url)
        dropdown = next(link for link in result.links if link.get("href") == review_url)
        assert inline["href"] == inspect_url
        assert dropdown["data-action"] == "review"
        assert dropdown["hx-get"] == review_url
        assert dropdown["hx-target"] == "#modal-content"
        response = admin_client.get(inspect_url)
        assert response.status_code == HTTPStatus.OK
        expected = f"Project {project.pk}"
        assert response.content.decode() == expected


def test_dataset_row_actions_match_changelist(
    dataset_rows, project_factory, admin_client
):
    project = project_factory()
    dataset = TableParser(dataset_rows.contents)
    response = admin_client.get(reverse("dataset_admin:example_project_changelist"))
    changelist = TableParser(response.content.decode())
    inspect_url = reverse(
        "dataset_admin:example_project_inspect_project", args=[project.pk]
    )
    review_url = reverse(
        "dataset_admin:example_project_review_project", args=[project.pk]
    )

    assert response.status_code == HTTPStatus.OK
    assert dataset.action_cells == changelist.action_cells == 1
    for url in (inspect_url, review_url):
        dataset_link = next(link for link in dataset.links if link.get("href") == url)
        changelist_link = next(
            link for link in changelist.links if link.get("href") == url
        )
        assert dataset_link == changelist_link


@pytest.mark.parametrize("is_superuser", [False, True])
def test_dataset_row_actions_filter_permissions(
    dataset_rows, project_factory, is_superuser
):
    project = project_factory()
    dataset_rows.request.user.is_superuser = is_superuser

    content = dataset_rows.contents
    result = TableParser(content)
    review_url = reverse(
        "dataset_admin:example_project_review_project", args=[project.pk]
    )

    assert result.action_cells == 1
    assert any(link.get("href") == review_url for link in result.links) == is_superuser
    assert "Restricted project" not in content


def test_dataset_row_action_endpoint_enforces_permissions(
    dataset_rows, project_factory, admin_client, staff_user
):
    project = project_factory()
    admin_client.force_login(staff_user)

    response = admin_client.get(
        reverse("dataset_admin:example_project_review_project", args=[project.pk])
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("row_actions", [(), ("restricted_project",)])
def test_dataset_row_actions_without_allowed_actions_have_no_column(
    dataset_rows, project_factory, row_actions
):
    project_factory()
    dataset_rows.model_admin_instance.actions_row = row_actions

    result = TableParser(dataset_rows.contents)

    assert result.action_cells == 0


@pytest.mark.parametrize("model_admin_class", [DjangoModelAdmin, ModelAdmin])
def test_dataset_without_row_actions_keeps_unregistered_model_support(
    admin_request, project_factory, model_admin_class
):
    class PlainProjectAdmin(model_admin_class):
        actions = []
        list_display = ("name",)
        list_display_links = None

    class PlainDataset(BaseDataset):
        model = Project
        model_admin = PlainProjectAdmin

    project_factory(name="Unregistered table")
    dataset = PlainDataset(admin_request, None)
    site = UnfoldAdminSite(name="unregistered")
    dataset.model_admin_instance.admin_site = site

    content = dataset.contents

    assert "Unregistered table" in content
    assert TableParser(content).action_cells == 0
    assert not site.is_registered(Project)


def test_dataset_row_actions_remain_stable_across_renders(
    dataset_rows, project_factory
):
    project_factory()

    first = TableParser(dataset_rows.contents)
    second = TableParser(dataset_rows.contents)

    assert first.action_cells == second.action_cells == 1
    assert first.links == second.links


def test_dataset_can_be_imported_before_admin():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; "
            "settings.configure(INSTALLED_APPS=['django.contrib.auth', "
            "'django.contrib.contenttypes'], SECRET_KEY='import-order-test'); "
            "import django; django.setup(); "
            "from unfold.datasets import BaseDataset",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
