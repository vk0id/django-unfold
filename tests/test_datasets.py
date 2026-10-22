from html.parser import HTMLParser
from http import HTTPStatus

import pytest
from django.contrib import admin
from django.template.loader import render_to_string
from django.urls import reverse
from example.models import InvoiceItem, Project

from unfold.admin import ModelAdmin
from unfold.datasets import BaseDataset


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
@pytest.mark.parametrize("model", [Project, InvoiceItem])
@pytest.mark.parametrize("allow_add", [False, True])
def test_empty_dataset_add_requires_route_and_permission(
    admin_request, model, allow_add
):
    class DatasetAdmin(ModelAdmin):
        def has_add_permission(self, request):
            return allow_add

    class Dataset(BaseDataset):
        pass

    Dataset.model = model
    Dataset.model_admin = DatasetAdmin
    assert admin.site.is_registered(model) == (model is Project)
    content = Dataset(admin_request, extra_context=None).contents
    assert "No results found" in content
    add_links = []

    class AddLinkParser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "a" and "bg-primary-600" in attrs.get("class", "").split():
                add_links.append(attrs.get("href"))

    AddLinkParser().feed(content)
    expected = (
        [reverse("admin:example_project_add")] if allow_add and model is Project else []
    )
    assert add_links == expected


@pytest.mark.django_db
@pytest.mark.parametrize("allow_add", [False, True])
@pytest.mark.parametrize("has_filters, query", [(True, ""), (False, "invoice")])
def test_empty_results_without_add_route_keeps_reset_filters(
    admin_request, allow_add, has_filters, query
):
    class Dataset(BaseDataset):
        model = InvoiceItem
        model_admin = ModelAdmin

    cl = Dataset(admin_request, extra_context=None).cl
    cl.has_filters = has_filters
    cl.query = query
    content = render_to_string(
        "unfold/helpers/empty_results.html",
        {"cl": cl, "has_add_permission": allow_add},
        request=admin_request,
    )
    assert 'href="?"' in content
    assert "Reset filters" in content
    assert '<a href=""' not in content
