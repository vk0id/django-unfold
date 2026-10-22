from http import HTTPStatus

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model

from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.contrib.filters.forms import RangeDateForm
from unfold.sites import UnfoldAdminSite


@pytest.mark.django_db
@pytest.mark.parametrize("view", ["changelist", "changeform"])
@pytest.mark.parametrize("nested_view", ["changelist", "changeform"])
@pytest.mark.parametrize("filter_style", ["simple", "field"])
def test_filter_media_uses_each_request(
    admin_user, rf, view, nested_view, filter_style
):
    class FirstForm(RangeDateForm):
        class Media:
            js = ["first-filter.js"]
            css = {"all": ["first-filter.css"]}

    class SecondForm(RangeDateForm):
        class Media:
            js = ["second-filter.js"]
            css = {"all": ["second-filter.css"]}

    class FirstSimpleFilter(admin.SimpleListFilter):
        title = "Filter"
        parameter_name = "filter"
        form_class = FirstForm

        def lookups(self, request, model_admin):
            return [("one", "One"), ("two", "Two")]

        def queryset(self, request, queryset):
            return queryset

    class SecondSimpleFilter(FirstSimpleFilter):
        form_class = SecondForm

    class FirstFieldFilter(RangeDateFilter):
        form_class = FirstForm

    class SecondFieldFilter(RangeDateFilter):
        form_class = SecondForm

    first_request = rf.get("/")
    second_request = rf.get("/")
    first_request.user = second_request.user = admin_user
    nested_responses = []

    class RequestMediaAdmin(ModelAdmin):
        fields = ["username"]
        list_display = ["username"]

        class Media:
            js = ["base-admin.js"]

        def get_list_filter(self, request):
            if filter_style == "simple":
                return [
                    FirstSimpleFilter
                    if request is first_request
                    else SecondSimpleFilter
                ]
            return [
                (
                    "date_joined",
                    FirstFieldFilter if request is first_request else SecondFieldFilter,
                )
            ]

        def get_queryset(self, request):
            if request is first_request and not nested_responses:
                nested_responses.append(invoke(self, second_request, nested_view))
            return super().get_queryset(request)

    def invoke(model_admin, request, view_name):
        if view_name == "changelist":
            return model_admin.changelist_view(request)
        return model_admin.changeform_view(request, str(admin_user.pk))

    model_admin = RequestMediaAdmin(get_user_model(), UnfoldAdminSite())
    first_response = invoke(model_admin, first_request, view)
    assert first_response.status_code == HTTPStatus.OK
    second_response = nested_responses[0]
    assert second_response.status_code == HTTPStatus.OK
    for response, own_name, other_name in (
        (first_response, "first-filter", "second-filter"),
        (second_response, "second-filter", "first-filter"),
    ):
        content = str(response.context_data["media"])
        assert "base-admin.js" in content
        assert f"{own_name}.js" in content
        assert f"{own_name}.css" in content
        assert f"{other_name}.js" not in content
        assert f"{other_name}.css" not in content
    assert not hasattr(model_admin, "request")
    assert "first-filter" not in str(model_admin.media)
    assert "second-filter" not in str(model_admin.media)


@pytest.mark.django_db
def test_filter_media_does_not_change_redirect_responses(admin_user, rf):
    class RedirectAdmin(ModelAdmin):
        def get_list_filter(self, request):
            return []

    request = rf.get("/", {"unknown_lookup": "value"})
    request.user = admin_user
    model_admin = RedirectAdmin(get_user_model(), UnfoldAdminSite())
    response = model_admin.changelist_view(request)
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == "/?e=1"
    assert not hasattr(model_admin, "request")
