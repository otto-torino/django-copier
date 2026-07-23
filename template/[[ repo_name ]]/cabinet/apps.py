from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CabinetConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"

    name = "cabinet"
    verbose_name = _("Cabinet media library")

    def ready(self):
        from pages.admin import PageAdmin

        from .models import PageContentMultiAttachment

        PageAdmin.register(PageContentMultiAttachment)
