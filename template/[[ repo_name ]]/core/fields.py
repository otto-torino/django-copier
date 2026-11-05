from django import forms

from .widgets import MapDrawerWidget


class MapShapeFormField(forms.JSONField):
    """A shape drawn on the map of the admin, stored as JSON."""

    widget = MapDrawerWidget

    def prepare_value(self, value):
        # without a shape the textarea stays empty, not the JSON "null"
        if value is None:
            return ""
        return super().prepare_value(value)
