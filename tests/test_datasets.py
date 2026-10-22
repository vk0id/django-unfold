from http import HTTPStatus

import pytest
from django.contrib import admin
from django.contrib.admin.views import main
from django.urls import reverse
from example.admin import ProjectDataset, ProjectDatasetModelAdmin
from example.models import FilterUser, Project


def test_datasets_no_selected_items(admin_client):
    response = admin_client.post(
        reverse("admin:example_user_change", args=[1]),
        {
            "_dataset": "ProjectDataset",
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert (
        "Items must be selected in order to perform actions on them. No items have been changed."
        in response.content.decode()
    )


def test_datasets_no_dataset_found(admin_client, project_factory):
    project = project_factory(name="Test Project")

    response = admin_client.post(
        reverse("admin:example_user_change", args=[1]),
        {
            "_selected_action": [project.pk],
            "_dataset": "NonExistingDataset",
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert "Dataset not found. No action performed." in response.content.decode()


def test_datasets_success_action(admin_client, project_factory):
    project = project_factory(name="Test Project")

    response = admin_client.post(
        reverse("admin:example_user_change", args=[1]),
        {
            "_selected_action": [project.pk],
            "_dataset": "ProjectDataset",
            "action": "delete_selected",
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK


def test_datasets_delete_selected_confirmation(admin_client, project_factory):
    project1 = project_factory(name="Test Project")
    project2 = project_factory(name="Another Project")

    response = admin_client.post(
        reverse("admin:example_user_change", args=[1]),
        {
            "_selected_action": [project1.pk, project2.pk],
            "_dataset": "ProjectDataset",
            "action": "delete_selected",
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert 'name="_dataset"' in content
    assert "ProjectDataset" in content
    assert project1.name in content
    assert project2.name in content

    response = admin_client.post(
        reverse("admin:example_user_change", args=[1]),
        {
            "_selected_action": [project1.pk, project2.pk],
            "_dataset": "ProjectDataset",
            "action": "delete_selected",
            "post": "yes",
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert Project.objects.all().count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("with_dataset", [False, True])
def test_changeform_preserves_global_ignored_parameters(
    admin_client, admin_user, monkeypatch, with_dataset
):
    model_admin = admin.site._registry[type(admin_user)]
    initial = (*main.IGNORED_PARAMS, "external_ignored_parameter")
    monkeypatch.setattr(main, "IGNORED_PARAMS", initial)
    monkeypatch.setattr(
        model_admin, "change_form_datasets", [ProjectDataset] if with_dataset else []
    )
    response = admin_client.get(
        reverse("admin:example_user_change", args=[admin_user.pk])
    )
    assert response.status_code == HTTPStatus.OK
    assert main.IGNORED_PARAMS == initial


@pytest.mark.django_db
@pytest.mark.parametrize("parameter", ["project-q", "project-p"])
def test_dataset_parameters_do_not_change_other_changelists(
    admin_client, admin_user, monkeypatch, parameter
):
    initial = tuple(
        p for p in main.IGNORED_PARAMS if p not in {"project-q", "project-p"}
    )
    monkeypatch.setattr(main, "IGNORED_PARAMS", initial)
    url = reverse("admin:example_user_changelist")
    before = admin_client.get(url, {parameter: "1"})
    assert before.status_code == HTTPStatus.FOUND
    response = admin_client.get(
        reverse("admin:example_user_change", args=[admin_user.pk])
    )
    assert response.status_code == HTTPStatus.OK
    after = admin_client.get(url, {parameter: "1"})
    assert after.status_code == before.status_code
    assert after.url == before.url


@pytest.mark.django_db
@pytest.mark.parametrize("search", [False, True])
def test_dataset_search_and_pagination_without_global_parameters(
    admin_client, admin_user, project_factory, monkeypatch, search
):
    project_factory(name="First target")
    second = project_factory(name="Second target")
    project_factory(name="Other")
    monkeypatch.setattr(ProjectDatasetModelAdmin, "list_per_page", 1)
    monkeypatch.setattr(ProjectDatasetModelAdmin, "ordering", ("pk",))
    page = 2
    data = {"project-p": str(page), "_changelist_filters": "is_active__exact=1"}
    if search:
        data["project-q"] = "target"
    response = admin_client.get(
        reverse("admin:example_user_change", args=[admin_user.pk]), data
    )
    assert response.status_code == HTTPStatus.OK
    cl = response.context_data["datasets"][0].cl
    assert cl.result_count == (2 if search else 3)
    assert list(cl.result_list) == [second]
    assert cl.page_num == page


@pytest.mark.django_db
def test_overlapping_changeforms_preserve_ignored_parameters(
    admin_client, admin_user, monkeypatch
):
    initial = (*main.IGNORED_PARAMS, "external_ignored_parameter")
    monkeypatch.setattr(main, "IGNORED_PARAMS", initial)
    inner_admin = admin.site._registry[FilterUser]
    monkeypatch.setattr(inner_admin, "change_form_datasets", [])
    observed = []
    original = ProjectDatasetModelAdmin.get_queryset

    def get_queryset(self, request):
        if not observed:
            observed.append(main.IGNORED_PARAMS)
            inner = admin_client.get(
                reverse("admin:example_filteruser_change", args=[admin_user.pk])
            )
            assert inner.status_code == HTTPStatus.OK
            observed.append(main.IGNORED_PARAMS)
        return original(self, request)

    monkeypatch.setattr(ProjectDatasetModelAdmin, "get_queryset", get_queryset)
    response = admin_client.get(
        reverse("admin:example_user_change", args=[admin_user.pk])
    )
    assert response.status_code == HTTPStatus.OK
    assert observed == [initial, initial]
    assert main.IGNORED_PARAMS == initial
