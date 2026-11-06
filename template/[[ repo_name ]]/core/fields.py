from django import forms
from django.db import models
from django.utils.translation import gettext_lazy as _

from .widgets import MapDrawerWidget


class MapShapeFormField(forms.JSONField):
    """A shape drawn on the map of the admin, stored as JSON."""

    widget = MapDrawerWidget

    def prepare_value(self, value):
        # without a shape the textarea stays empty, not the JSON "null"
        if value is None:
            return ""
        return super().prepare_value(value)


class AltTextField(models.TextField):
    """The alternative text of an image, edited in a short textarea."""

    def formfield(self, **kwargs):
        formfield = super().formfield(**kwargs)
        formfield.widget.attrs["rows"] = 3
        return formfield


class SubjectLocationField(models.CharField):
    """Coordinates edited by the draggable pin on the image preview."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("verbose_name", _("subject coordinates"))
        kwargs.setdefault("max_length", 7)
        kwargs.setdefault("default", "50,50")
        kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        return super().formfield(**{
            **kwargs,
            "widget": forms.HiddenInput,
            "empty_value": self.get_default(),
        })
