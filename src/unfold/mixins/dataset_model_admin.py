from inspect import Parameter, signature
from typing import Any

from django.contrib import messages
from django.contrib.admin import ModelAdmin, helpers
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.options import TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.contrib.admin.views import main
from django.contrib.admin.views.main import IGNORED_PARAMS
from django.core.exceptions import PermissionDenied
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.translation import gettext_lazy as _

from unfold.datasets import BaseDataset


class DatasetModelAdminMixin(ModelAdmin):
    change_form_datasets: list[type[BaseDataset]] | tuple[type[BaseDataset], ...] = ()

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        self.request = request
        if request.method == "POST" and "_dataset" in request.POST:
            obj = self._check_dataset_action_permissions(request, object_id)
            rendered_datasets = self._get_rendered_datasets(request, object_id, obj)

            selected = request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)

            if not selected or helpers.ACTION_CHECKBOX_NAME not in request.POST:
                messages.warning(
                    request,
                    _(
                        "Items must be selected in order to perform actions on them. No items have been changed."
                    ),
                )
                return HttpResponseRedirect(request.get_full_path())

            dataset = None
            for item in rendered_datasets:
                if item.id == request.POST["_dataset"]:
                    dataset = item

            if not dataset:
                messages.warning(
                    request,
                    _("Dataset not found. No action performed."),
                )
                return HttpResponseRedirect(request.get_full_path())

            response = dataset.model_admin_instance.response_action(
                request, queryset=dataset.cl.get_queryset(request)
            )

            if response:
                return response

        return super().changeform_view(request, object_id, form_url, extra_context)

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: Model | None = None,
    ) -> HttpResponse:
        context["datasets"] = self._get_rendered_datasets(
            request, context.get("object_id"), obj
        )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def get_changeform_datasets(
        self, request: HttpRequest, obj: Model | None = None
    ) -> list[type[BaseDataset]] | tuple[type[BaseDataset], ...]:
        return self.change_form_datasets

    def _get_changeform_datasets(
        self, request: HttpRequest, obj: Model | None
    ) -> list[type[BaseDataset]] | tuple[type[BaseDataset], ...]:
        hook = self.get_changeform_datasets
        hook_signature = signature(hook)
        # Inspect argument support without catching errors from the hook itself.
        try:
            hook_signature.bind(request, obj=obj)
        except TypeError:
            obj_parameter = hook_signature.parameters.get("obj")
            if obj_parameter and obj_parameter.kind == Parameter.POSITIONAL_ONLY:
                return hook(request, obj)
            return hook(request)
        return hook(request, obj=obj)

    def _get_rendered_datasets(
        self, request: HttpRequest, object_id: str | None, obj: Model | None
    ) -> list[BaseDataset]:
        datasets = self._get_changeform_datasets(request, obj)

        # Monkeypatch IGNORED_PARAMS to add dataset page and search arguments into ignored params
        ignored_params = []
        for dataset in datasets:
            ignored_params.append(f"{dataset.model._meta.model_name}-q")
            ignored_params.append(f"{dataset.model._meta.model_name}-p")
            ignored_params.append("_changelist_filters")

        main.IGNORED_PARAMS = (*IGNORED_PARAMS, *ignored_params)

        return [
            dataset(request=request, extra_context={"object": object_id})
            for dataset in datasets
        ]

    def _check_dataset_action_permissions(
        self, request: HttpRequest, object_id: str | None
    ) -> Model | None:
        to_field = request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))

        if to_field and not self.to_field_allowed(request, to_field):
            raise DisallowedModelAdminToField(
                f"The field {to_field} cannot be referenced."
            )

        obj = None

        if _add := object_id is None:
            if not self.has_add_permission(request):
                raise PermissionDenied
        else:
            obj = self.get_object(request, unquote(object_id), to_field)

        if not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied

        return obj
