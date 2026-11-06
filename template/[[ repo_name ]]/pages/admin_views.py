import json

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import View

from pages.copying import duplicate_block
from pages.models import Page, PageContent


def form_tabs(fieldsets):
    """The tabs Baton makes of the fieldsets of a form, as (label, anchor):
    the first fieldset names them in its classes and is the main tab, each
    other one is the fieldset with the class of its tab. Baton opens the tab
    of the anchor of the address."""
    if not fieldsets:
        return []
    (main_title, main), others = fieldsets[0], fieldsets[1:]
    titles = {
        cls.removeprefix("tab-fs-"): title
        for title, options in others
        for cls in options.get("classes", ())
        if cls.startswith("tab-fs-")
    }
    tabs = [(main_title, "#main-tab")]
    for cls in main.get("classes", ()):
        name = cls.removeprefix("baton-tab-fs-")
        if cls.startswith("baton-tab-fs-") and name in titles:
            tabs.append((titles[name], f"#fs-{name}"))
    return tabs


class EditPageContentsView(PermissionRequiredMixin, View):
    permission_required = ["pages.add_page", "pages.change_page"]

    def get(self, request, id):
        page = get_object_or_404(Page, id=id)
        page_admin = admin.site._registry[Page]
        change_url = reverse("admin:pages_page_change", args=[page.pk])
        context = {
            "site_header": mark_safe(settings.BATON.get("SITE_HEADER", None)),
            # the header of the page form, so that the two read as one page
            "title": _("Change %s") % Page._meta.verbose_name,
            "subtitle": str(page),
            "is_popup": False,
            "has_permission": True,
            "site_url": reverse("home"),
            "page": page,
            "page_admin": page_admin,
            "page_tabs": [
                (label, f"{change_url}{anchor}")
                for label, anchor in form_tabs(page_admin.get_fieldsets(request, page))
            ],
            "history_url": reverse("admin:pages_page_history", args=[page.pk]),
            "view_on_site_url": reverse(
                "admin:view_on_site",
                args=[ContentType.objects.get_for_model(Page).pk, page.pk],
            ),
        }

        return render(
            request,
            "admin/pages/change_content.html",
            context,
        )


class SaveContentBlocksPositionView(PermissionRequiredMixin, View):
    permission_required = ["pages.add_page", "pages.change_page"]

    @transaction.atomic
    def post(self, request, pk):
        page = get_object_or_404(Page, pk=pk)
        try:
            data = json.loads(request.body)
            order = data["order"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)

        if not isinstance(order, list):
            return JsonResponse({"error": "Order must be a list."}, status=400)

        block_ids = []
        for item in order:
            block_id = item.get("id") if isinstance(item, dict) else None
            try:
                block_id = int(block_id)
            except (TypeError, ValueError):
                return JsonResponse({"error": "Invalid content block ID."}, status=400)
            if block_id in block_ids:
                return JsonResponse(
                    {"error": "Duplicate content block ID."},
                    status=400,
                )
            block_ids.append(block_id)

        blocks = {
            block.pk: block
            for block in PageContent.objects.filter(page=page, pk__in=block_ids)
        }
        if len(blocks) != len(block_ids):
            return JsonResponse(
                {"error": "A content block does not belong to this page."},
                status=400,
            )

        for position, block_id in enumerate(block_ids):
            content_block = blocks[block_id]
            content_block.position = position
            content_block.save()

        return JsonResponse({"saved": True})


class ToggleContentBlockView(PermissionRequiredMixin, View):
    """Turns a block of the page on or off, from the list of the contents."""

    permission_required = ["pages.add_page", "pages.change_page"]

    def post(self, request, pk, block_pk):
        block = get_object_or_404(PageContent, pk=block_pk, page_id=pk)
        block.enabled = not block.enabled
        block.save()
        return JsonResponse({"enabled": block.enabled})


class DuplicateContentBlockView(PermissionRequiredMixin, View):
    """A copy of a block of the page, right after it."""

    permission_required = ["pages.add_page", "pages.change_page"]

    def post(self, request, pk, block_pk):
        block = get_object_or_404(PageContent, pk=block_pk, page_id=pk)
        copy = duplicate_block(block)
        messages.success(request, _("The block has been copied as “%(name)s”.") % {"name": copy.name})
        return redirect(reverse("admin:pages_page_edit_content", kwargs={"id": pk}) + f"#block-row-{copy.pk}")
