from http import HTTPStatus

import pytest
from django.contrib import admin
from django.contrib.admin.utils import quote
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from example.models import Project, Task

from unfold.admin import ModelAdmin
from unfold.datasets import BaseDataset


class TaskDatasetAdmin(ModelAdmin):
    list_display = ("name",)

    @admin.action(description="Rename tasks")
    def rename_tasks(self, request, queryset):
        queryset.update(name="Renamed")
        return HttpResponse("Tasks renamed")

    actions = ("rename_tasks", "delete_selected")


class ProjectTasksDataset(BaseDataset):
    model = Task
    model_admin = TaskDatasetAdmin


class ObjectDatasetsAdmin(ModelAdmin):
    fields = ("name", "is_active")
    change_form_datasets = (ProjectTasksDataset,)

    def get_changeform_datasets(self, request, obj=None):
        request.dataset_objects.append(obj)
        if obj is None or not obj.is_active:
            return ()
        return super().get_changeform_datasets(request, obj)


@pytest.fixture
def dataset_request(admin_user):
    def make_request(data=None, query=""):
        factory = RequestFactory()
        path = f"/admin/example/project/1/change/{query}"
        request = factory.get(path) if data is None else factory.post(path, data)
        request.user = admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        request._dont_enforce_csrf_checks = True
        request.dataset_objects = []
        return request

    return make_request


@pytest.fixture
def parent_admin():
    return ObjectDatasetsAdmin(Project, admin.site)


def parent_selects(queries):
    return [
        query["sql"]
        for query in queries
        if query["sql"].startswith("SELECT")
        and 'FROM "example_project"' in query["sql"]
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("is_active", [True, False])
def test_dataset_selection_reuses_form_object(
    dataset_request, parent_admin, project_factory, is_active
):
    parent = project_factory(is_active=is_active)
    request = dataset_request()
    with CaptureQueriesContext(connection) as queries:
        response = parent_admin.changeform_view(request, quote(str(parent.pk)))
        response.render()

    assert response.status_code == HTTPStatus.OK
    assert request.dataset_objects == [response.context_data["original"]]
    assert request.dataset_objects[0] is response.context_data["original"]
    assert len(parent_selects(queries)) == 1
    datasets = response.context_data["datasets"]
    assert bool(datasets) is is_active
    if is_active:
        assert datasets[0].extra_context == {"object": quote(str(parent.pk))}


@pytest.mark.django_db
def test_add_form_passes_none_without_parent_query(dataset_request, parent_admin):
    request = dataset_request()
    with CaptureQueriesContext(connection) as queries:
        response = parent_admin.changeform_view(request)
        response.render()
    assert request.dataset_objects == [None]
    assert response.context_data["datasets"] == []
    assert parent_selects(queries) == []


@pytest.mark.django_db
def test_legacy_dataset_hook_still_selects_datasets(dataset_request, project_factory):
    class LegacyAdmin(ModelAdmin):
        fields = ("name",)

        def get_changeform_datasets(self, request):
            return (ProjectTasksDataset,)

    request = dataset_request()
    response = LegacyAdmin(Project, admin.site).changeform_view(
        request, str(project_factory().pk)
    )
    response.render()
    assert len(response.context_data["datasets"]) == 1


@pytest.mark.django_db
def test_hook_typeerror_is_not_retried(dataset_request, project_factory):
    class BrokenAdmin(ObjectDatasetsAdmin):
        def get_changeform_datasets(self, request, obj=None):
            request.dataset_objects.append(obj)
            raise TypeError("Hook implementation failed")

    request = dataset_request()
    with pytest.raises(TypeError, match="Hook implementation failed"):
        BrokenAdmin(Project, admin.site).changeform_view(
            request, str(project_factory().pk)
        )
    assert len(request.dataset_objects) == 1
    assert request.dataset_objects[0] is not None


@pytest.mark.django_db
def test_dataset_action_reuses_permission_object(
    dataset_request, parent_admin, project_factory, task_factory
):
    parent = project_factory(is_active=True)
    task = task_factory(project=parent)
    request = dataset_request(
        {
            "_dataset": "ProjectTasksDataset",
            "_selected_action": [task.pk],
            "action": "rename_tasks",
        }
    )
    with CaptureQueriesContext(connection) as queries:
        response = parent_admin.changeform_view(request, str(parent.pk))
    assert response.content == b"Tasks renamed"
    task.refresh_from_db()
    assert task.name == "Renamed"
    assert [obj.pk for obj in request.dataset_objects] == [parent.pk]
    assert len(parent_selects(queries)) == 1


@pytest.mark.django_db
def test_missing_parent_does_not_select_datasets(dataset_request, parent_admin):
    request = dataset_request()
    response = parent_admin.changeform_view(request, "999999")
    assert response.status_code == HTTPStatus.FOUND
    assert request.dataset_objects == []


@pytest.mark.django_db
def test_legacy_optional_argument_keeps_its_default(dataset_request, project_factory):
    class LegacyAdmin(ModelAdmin):
        def get_changeform_datasets(self, request, enabled=False):
            return (ProjectTasksDataset,) if enabled else ()

    request = dataset_request()
    response = LegacyAdmin(Project, admin.site).changeform_view(
        request, str(project_factory().pk)
    )
    assert response.context_data["datasets"] == []


@pytest.mark.django_db
@pytest.mark.parametrize("signature_kind", ["keyword", "positional", "kwargs"])
def test_object_hook_signature_variants(
    dataset_request, project_factory, signature_kind
):
    class KeywordAdmin(ObjectDatasetsAdmin):
        def get_changeform_datasets(self, request, *, obj):
            return super().get_changeform_datasets(request, obj)

    class PositionalAdmin(ObjectDatasetsAdmin):
        def get_changeform_datasets(self, request, obj, /):
            return super().get_changeform_datasets(request, obj)

    class KwargsAdmin(ObjectDatasetsAdmin):
        def get_changeform_datasets(self, request, **kwargs):
            return super().get_changeform_datasets(request, **kwargs)

    admin_class = {
        "keyword": KeywordAdmin,
        "positional": PositionalAdmin,
        "kwargs": KwargsAdmin,
    }[signature_kind]
    request = dataset_request()
    response = admin_class(Project, admin.site).changeform_view(
        request, str(project_factory(is_active=True).pk)
    )
    assert len(response.context_data["datasets"]) == 1
    assert request.dataset_objects[0] is response.context_data["original"]


@pytest.mark.django_db
def test_invalid_form_selection_uses_unsaved_values(
    dataset_request, parent_admin, project_factory
):
    parent = project_factory(is_active=False)
    request = dataset_request({"is_active": "on"})
    with CaptureQueriesContext(connection) as queries:
        response = parent_admin.changeform_view(request, str(parent.pk))
    assert response.context_data["errors"]
    assert len(response.context_data["datasets"]) == 1
    assert request.dataset_objects[0] is response.context_data["original"]
    assert request.dataset_objects[0].is_active is True
    parent.refresh_from_db()
    assert parent.is_active is False
    assert len(parent_selects(queries)) == 1


@pytest.mark.django_db
def test_invalid_save_as_new_passes_none(
    dataset_request, parent_admin, project_factory
):
    parent = project_factory(is_active=True)
    request = dataset_request({"_saveasnew": "1", "is_active": "on"})
    with CaptureQueriesContext(connection) as queries:
        response = parent_admin.changeform_view(request, str(parent.pk))
    assert response.context_data["errors"]
    assert request.dataset_objects == [None]
    assert response.context_data["datasets"] == []
    assert parent_selects(queries) == []


@pytest.mark.django_db
def test_successful_save_does_not_construct_unused_datasets(
    dataset_request, parent_admin, project_factory
):
    parent = project_factory(is_active=True)
    request = dataset_request({"name": "Changed", "is_active": "on"})
    response = parent_admin.changeform_view(request, str(parent.pk))
    assert response.status_code == HTTPStatus.FOUND
    assert request.dataset_objects == []
    parent.refresh_from_db()
    assert parent.name == "Changed"


@pytest.mark.django_db
def test_restricted_parent_queryset_does_not_select_datasets(
    dataset_request, project_factory
):
    class RestrictedAdmin(ObjectDatasetsAdmin):
        def get_queryset(self, request):
            return super().get_queryset(request).filter(is_active=True)

    request = dataset_request()
    response = RestrictedAdmin(Project, admin.site).changeform_view(
        request, str(project_factory(is_active=False).pk)
    )
    assert response.status_code == HTTPStatus.FOUND
    assert request.dataset_objects == []


@pytest.mark.django_db
@pytest.mark.parametrize("is_action", [True, False])
def test_denied_parent_does_not_select_datasets(
    dataset_request, parent_admin, project_factory, regular_user, is_action
):
    from django.core.exceptions import PermissionDenied

    request = dataset_request(
        {"_dataset": "ProjectTasksDataset"} if is_action else None
    )
    request.user = regular_user
    with pytest.raises(PermissionDenied):
        parent_admin.changeform_view(request, str(project_factory(is_active=True).pk))
    assert request.dataset_objects == []


@pytest.mark.django_db
@pytest.mark.parametrize("is_action", [True, False])
def test_disallowed_to_field_does_not_select_datasets(
    dataset_request, parent_admin, project_factory, is_action
):
    from django.contrib.admin.exceptions import DisallowedModelAdminToField

    request = dataset_request(
        {"_dataset": "ProjectTasksDataset", "_to_field": "is_active"}
        if is_action
        else None,
        query="?_to_field=is_active",
    )
    with pytest.raises(DisallowedModelAdminToField):
        parent_admin.changeform_view(request, str(project_factory().pk))
    assert request.dataset_objects == []


@pytest.mark.django_db
@pytest.mark.parametrize("is_action", [True, False])
def test_allowed_to_field_and_escaped_identifier(
    dataset_request, project_factory, task_factory, monkeypatch, is_action
):
    class NamedAdmin(ObjectDatasetsAdmin):
        def to_field_allowed(self, request, to_field):
            return to_field == "name"

    monkeypatch.setattr(
        TaskDatasetAdmin, "to_field_allowed", NamedAdmin.to_field_allowed
    )
    parent = project_factory(name="A/B_42", is_active=True)
    task = task_factory(project=parent)
    request = dataset_request(
        {
            "_dataset": "ProjectTasksDataset",
            "_selected_action": [task.pk],
            "action": "rename_tasks",
            "_to_field": "name",
        }
        if is_action
        else None,
        query="?_to_field=name",
    )
    with CaptureQueriesContext(connection) as queries:
        response = NamedAdmin(Project, admin.site).changeform_view(
            request, quote(parent.name)
        )
    assert len(parent_selects(queries)) == 1
    assert request.dataset_objects[0].pk == parent.pk
    if is_action:
        assert response.content == b"Tasks renamed"
    else:
        assert response.context_data["datasets"][0].extra_context == {
            "object": "A_2FB_5F42"
        }


@pytest.mark.django_db
def test_hidden_dataset_action_cannot_execute(
    dataset_request, parent_admin, project_factory, task_factory
):
    parent = project_factory(is_active=False)
    task = task_factory(project=parent)
    request = dataset_request(
        {
            "_dataset": "ProjectTasksDataset",
            "_selected_action": [task.pk],
            "action": "rename_tasks",
        }
    )
    response = parent_admin.changeform_view(request, str(parent.pk))
    assert response.status_code == HTTPStatus.FOUND
    task.refresh_from_db()
    assert task.name != "Renamed"


@pytest.mark.django_db
def test_action_without_response_retains_parent_form_fallback(
    dataset_request, parent_admin, project_factory, task_factory, monkeypatch
):
    def action_without_response(self, request, queryset):
        queryset.update(name="Renamed")

    monkeypatch.setattr(TaskDatasetAdmin, "response_action", action_without_response)
    parent = project_factory(is_active=True)
    task = task_factory(project=parent)
    request = dataset_request(
        {
            "_dataset": "ProjectTasksDataset",
            "_selected_action": [task.pk],
            "action": "rename_tasks",
        }
    )
    with CaptureQueriesContext(connection) as queries:
        response = parent_admin.changeform_view(request, str(parent.pk))
    assert response.status_code == HTTPStatus.OK
    assert response.context_data["errors"]
    task.refresh_from_db()
    assert task.name == "Renamed"
    # The existing fallback also loads once for authorization and once for the form.
    expected_parent_lookups = 2
    assert len(parent_selects(queries)) == expected_parent_lookups


@pytest.mark.django_db
def test_default_configuration_keeps_datasets_on_add(dataset_request):
    model_admin = ModelAdmin(Project, admin.site)
    model_admin.change_form_datasets = (ProjectTasksDataset,)
    response = model_admin.changeform_view(dataset_request())
    assert len(response.context_data["datasets"]) == 1
    assert response.context_data["datasets"][0].extra_context == {"object": None}


@pytest.mark.django_db
def test_same_admin_does_not_reuse_previous_parent(
    dataset_request, parent_admin, project_factory
):
    first = project_factory(is_active=True)
    second = project_factory(is_active=False)
    first_request = dataset_request()
    second_request = dataset_request()
    first_response = parent_admin.changeform_view(first_request, str(first.pk))
    second_response = parent_admin.changeform_view(second_request, str(second.pk))
    assert first_request.dataset_objects[0].pk == first.pk
    assert second_request.dataset_objects[0].pk == second.pk
    assert len(first_response.context_data["datasets"]) == 1
    assert second_response.context_data["datasets"] == []


@pytest.mark.django_db
def test_legacy_hook_can_delegate_to_super(dataset_request, project_factory):
    class LegacyAdmin(ModelAdmin):
        change_form_datasets = (ProjectTasksDataset,)

        def get_changeform_datasets(self, request):
            return super().get_changeform_datasets(request)

    response = LegacyAdmin(Project, admin.site).changeform_view(
        dataset_request(), str(project_factory().pk)
    )
    assert len(response.context_data["datasets"]) == 1


@pytest.mark.django_db
def test_dataset_selection_retains_extra_context_precedence(
    dataset_request, parent_admin, project_factory
):
    response = parent_admin.changeform_view(
        dataset_request(),
        str(project_factory(is_active=True).pk),
        extra_context={"datasets": "caller value", "custom_value": "retained"},
    )
    assert len(response.context_data["datasets"]) == 1
    assert isinstance(response.context_data["datasets"][0], ProjectTasksDataset)
    assert response.context_data["custom_value"] == "retained"
