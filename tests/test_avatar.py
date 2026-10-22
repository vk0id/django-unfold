import re

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory

from unfold.sites import UnfoldAdminSite

pytestmark = pytest.mark.django_db


def request_avatar(request):
    return f"/avatars/{request.user.pk}.webp"


def render_navigation(site, request):
    return render_to_string(
        "unfold/helpers/navigation_user.html",
        site.each_context(request),
        request=request,
    )


def test_user_avatar_default_preserves_legacy_url(settings, admin_request):
    settings.UNFOLD = {}
    admin_request.user.avatar_url = "/legacy.webp"

    result = render_navigation(UnfoldAdminSite(), admin_request)

    assert "background-image: url('/legacy.webp')" in result


@pytest.mark.parametrize(
    "callback", [request_avatar, "tests.test_avatar.request_avatar"]
)
def test_user_avatar_callback_uses_current_request(
    settings, admin_request, user_factory, callback
):
    settings.UNFOLD = {"USER_AVATAR": callback}
    other_request = RequestFactory().get("/admin/")
    other_request.user = user_factory()
    site = UnfoldAdminSite()

    first_result = render_navigation(site, admin_request)
    other_result = render_navigation(site, other_request)
    first_url = f"/avatars/{admin_request.user.pk}.webp"
    other_url = f"/avatars/{other_request.user.pk}.webp"

    assert first_url in first_result
    assert other_url not in first_result
    assert other_url in other_result
    assert first_url not in other_result


def test_user_avatar_static_url_is_escaped_once(settings, admin_request):
    settings.UNFOLD = {"USER_AVATAR": "/avatar.webp?v=1&size=small"}
    admin_request.user.avatar_url = "/legacy.webp"

    result = render_navigation(UnfoldAdminSite(), admin_request)

    assert "background-image: url('/avatar.webp?v=1&amp;size=small')" in result
    assert "&amp;amp;" not in result
    assert "/legacy.webp" not in result


def test_user_avatar_respects_custom_site_settings(settings, admin_request):
    settings.UNFOLD = {"USER_AVATAR": "/default-site.webp"}
    settings.OTHER_ADMIN = {"USER_AVATAR": "/other-site.webp"}
    site = UnfoldAdminSite()
    site.settings_name = "OTHER_ADMIN"

    result = render_navigation(site, admin_request)

    assert "/other-site.webp" in result
    assert "/default-site.webp" not in result


@pytest.mark.parametrize("callback_value", [None, ""])
@pytest.mark.parametrize("legacy_url", [None, "/legacy.webp"])
def test_user_avatar_empty_callback_uses_legacy_or_initials(
    settings, admin_request, callback_value, legacy_url
):
    def avatar(request):
        return callback_value

    settings.UNFOLD = {"USER_AVATAR": avatar}
    admin_request.user.avatar_url = legacy_url
    admin_request.user.first_name = "Alice"

    result = render_navigation(UnfoldAdminSite(), admin_request)

    if legacy_url:
        assert "background-image: url('/legacy.webp')" in result
    else:
        assert "background-image" not in result
        assert re.search(r">\s*A\s*</div>", result)


def test_user_avatar_callback_accepts_anonymous_request(settings):
    def avatar(request):
        if request.user.is_authenticated:
            return "/authenticated.webp"
        return None

    settings.UNFOLD = {"USER_AVATAR": avatar}
    request = RequestFactory().get("/admin/login/")
    request.user = AnonymousUser()

    context = UnfoldAdminSite().each_context(request)

    assert context["user_avatar"] is None


def test_avatar_override_does_not_evaluate_legacy_url():
    class UserWithRequiredAvatarSize:
        @property
        def avatar_url(self):
            raise AssertionError("A configured avatar must not evaluate the legacy URL")

    result = render_to_string(
        "unfold/helpers/avatar.html",
        {"user": UserWithRequiredAvatarSize(), "avatar_url": "/configured.webp"},
    )

    assert "background-image: url('/configured.webp')" in result


def test_avatar_component_does_not_use_other_user_callback(
    settings, admin_request, user_factory
):
    settings.UNFOLD = {"USER_AVATAR": request_avatar}
    other_user = user_factory()
    other_user.avatar_url = "/other-user.webp"
    context = UnfoldAdminSite().each_context(admin_request)
    context["user"] = other_user

    result = render_to_string("unfold/helpers/avatar.html", context)

    assert "background-image: url('/other-user.webp')" in result
    assert request_avatar(admin_request) not in result


def test_avatar_legacy_no_argument_method():
    class LegacyUser:
        def avatar_url(self):
            return "/legacy-method.webp"

    result = render_to_string("unfold/helpers/avatar.html", {"user": LegacyUser()})

    assert "background-image: url('/legacy-method.webp')" in result


@pytest.mark.parametrize(
    ("first_name", "expected_initial"), [("Alice", "A"), ("", "B")]
)
def test_avatar_initials_without_configuration(
    settings, user_factory, first_name, expected_initial
):
    settings.UNFOLD = {}
    user = user_factory(username="bob", first_name=first_name, last_name="")

    result = render_to_string("unfold/helpers/avatar.html", {"user": user})

    assert "background-image" not in result
    assert re.search(r">\s*" + expected_initial + r"\s*</div>", result)


@pytest.mark.parametrize(
    ("size", "pixels"), [("", 38), ("md", 34), ("sm", 30), ("xs", 26)]
)
@pytest.mark.parametrize("circle", [False, True])
def test_avatar_override_preserves_badges_and_dimensions(
    user_factory, size, pixels, circle
):
    user = user_factory()
    user.avatar_badge_count = 3
    user.avatar_badge_variant = "danger"
    user.avatar_badge_url = "/alerts/"

    result = render_to_string(
        "unfold/helpers/avatar.html",
        {
            "user": user,
            "avatar_url": "/configured.webp",
            "size": size,
            "circle": circle,
        },
    )

    assert "background-image: url('/configured.webp')" in result
    assert f"h-[{pixels}px]" in result
    assert ("after:rounded-full" in result) == circle
    assert "bg-red-600" in result
    assert '<a href="/alerts/"' in result
    assert re.search(r">\s*3\s*</a>", result)


def test_user_avatar_callback_can_supply_required_size(settings, admin_request):
    def sized_avatar(size):
        return f"/avatar-{size}.webp"

    def avatar(request):
        return request.user.avatar_url("small")

    admin_request.user.avatar_url = sized_avatar
    settings.UNFOLD = {"USER_AVATAR": avatar}

    result = render_navigation(UnfoldAdminSite(), admin_request)

    assert "background-image: url('/avatar-small.webp')" in result


def request_badge_count(request):
    return request.badge_count


@pytest.mark.parametrize("configured_count", [None, 0, 12])
def test_user_badge_count_static_value(settings, admin_request, configured_count):
    settings.UNFOLD = {"USER_BADGE_COUNT": configured_count}
    admin_request.user.avatar_badge_count = 7
    admin_request.user.avatar_badge_url = "/alerts/"

    result = render_navigation(UnfoldAdminSite(), admin_request)

    if configured_count == 0:
        assert 'href="/alerts/"' not in result
    else:
        expected = 7 if configured_count is None else 12
        assert re.search(r">\s*" + str(expected) + r"\s*</a>", result)


@pytest.mark.parametrize(
    "callback", [request_badge_count, "tests.test_avatar.request_badge_count"]
)
@pytest.mark.parametrize("count", [None, 0, 12])
def test_user_badge_count_callback(settings, admin_request, callback, count):
    settings.UNFOLD = {"USER_BADGE_COUNT": callback}
    admin_request.badge_count = count
    admin_request.user.avatar_badge_count = 7
    admin_request.user.avatar_badge_url = "/alerts/"

    result = render_navigation(UnfoldAdminSite(), admin_request)

    if count == 0:
        assert 'href="/alerts/"' not in result
    else:
        expected = 7 if count is None else 12
        assert re.search(r">\s*" + str(expected) + r"\s*</a>", result)


def test_user_badge_count_uses_current_request(settings, admin_request, user_factory):
    settings.UNFOLD = {"USER_BADGE_COUNT": request_badge_count}
    admin_request.badge_count = 3
    admin_request.user.avatar_badge_url = "/alerts/"
    other_request = RequestFactory().get("/admin/")
    other_request.user = user_factory()
    other_request.user.avatar_badge_url = "/alerts/"
    other_request.badge_count = 5
    site = UnfoldAdminSite()

    first_result = render_navigation(site, admin_request)
    other_result = render_navigation(site, other_request)

    assert re.search(r">\s*3\s*</a>", first_result)
    assert not re.search(r">\s*5\s*</a>", first_result)
    assert re.search(r">\s*5\s*</a>", other_result)
    assert not re.search(r">\s*3\s*</a>", other_result)


def test_user_badge_count_custom_site_preserves_zero(settings, admin_request):
    settings.UNFOLD = {"USER_BADGE_COUNT": 12}
    settings.OTHER_ADMIN = {"USER_BADGE_COUNT": 0}
    admin_request.user.avatar_badge_count = 7
    admin_request.user.avatar_badge_url = "/alerts/"
    site = UnfoldAdminSite()
    site.settings_name = "OTHER_ADMIN"

    result = render_navigation(site, admin_request)

    assert 'href="/alerts/"' not in result


def test_user_badge_count_callback_accepts_anonymous_request(settings):
    def count(request):
        if request.user.is_authenticated:
            return 12
        return None

    settings.UNFOLD = {"USER_BADGE_COUNT": count}
    request = RequestFactory().get("/admin/login/")
    request.user = AnonymousUser()

    context = UnfoldAdminSite().each_context(request)

    assert context["user_badge_count"] is None


@pytest.mark.parametrize("count", [0, 12])
def test_badge_count_override_does_not_evaluate_legacy_count(count):
    class UserWithoutLegacyCountAccess:
        avatar_url = "/avatar.webp"

        @property
        def avatar_badge_count(self):
            raise AssertionError(
                "A configured count must not evaluate the legacy count"
            )

    result = render_to_string(
        "unfold/helpers/avatar.html",
        {"user": UserWithoutLegacyCountAccess(), "badge_count": count},
    )

    if count:
        assert re.search(r">\s*12\s*</div>", result)
    else:
        assert not re.search(r">\s*0\s*</div>", result)


def test_zero_badge_count_preserves_variant_only_badge(settings, admin_request):
    settings.UNFOLD = {"USER_BADGE_COUNT": 0}
    admin_request.user.avatar_badge_count = 7
    admin_request.user.avatar_badge_variant = "danger"
    admin_request.user.avatar_badge_url = "/alerts/"

    result = render_navigation(UnfoldAdminSite(), admin_request)

    assert 'href="/alerts/"' in result
    assert "bg-red-600" in result
    assert not re.search(r">\s*[07]\s*</a>", result)


def test_badge_count_legacy_no_argument_method():
    class LegacyUser:
        avatar_url = "/legacy.webp"

        def avatar_badge_count(self):
            return 7

    result = render_to_string("unfold/helpers/avatar.html", {"user": LegacyUser()})

    assert re.search(r">\s*7\s*</div>", result)


def test_badge_count_component_does_not_use_other_user_callback(
    settings, admin_request, user_factory
):
    settings.UNFOLD = {"USER_BADGE_COUNT": 12}
    other_user = user_factory()
    other_user.avatar_badge_count = 7
    context = UnfoldAdminSite().each_context(admin_request)
    context["user"] = other_user

    result = render_to_string("unfold/helpers/avatar.html", context)

    assert re.search(r">\s*7\s*</div>", result)
    assert not re.search(r">\s*12\s*</div>", result)


def test_user_badge_count_text_is_escaped(settings, admin_request):
    settings.UNFOLD = {"USER_BADGE_COUNT": "<b>7</b>"}
    admin_request.user.avatar_badge_url = "/alerts/"

    result = render_navigation(UnfoldAdminSite(), admin_request)

    assert "&lt;b&gt;7&lt;/b&gt;" in result
    assert "<b>7</b>" not in result
