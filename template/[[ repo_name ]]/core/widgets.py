from django import forms


class MapDrawerWidget(forms.Textarea):
    """A shape drawn on a Leaflet map with Geoman, stored as JSON in the textarea.

    The shape is fixed (``shape="POINT"``) or read from a select of the same
    form (``shape_field="shape"``), as the items of the map block do. The
    values are ``{"lat", "lng"}`` for a point, a list of them for a polyline or
    a polygon, ``{"lat", "lng", "radius"}`` for a circle.
    """

    template_name = "core/widgets/map_drawer.html"

    class Media:
        css = {
            "all": (
                "core/src/vendor/leaflet/leaflet.css",
                "core/src/vendor/leaflet-geoman/leaflet-geoman.css",
                "core/src/css/map_drawer.css",
            )
        }
        js = (
            "core/src/vendor/leaflet/leaflet.js",
            "core/src/vendor/leaflet-geoman/leaflet-geoman.min.js",
            "core/src/js/map_drawer.js",
        )

    def __init__(self, attrs=None, shape=None, shape_field=None, height=360):
        super().__init__({"rows": 3, **(attrs or {})})
        self.shape = shape
        self.shape_field = shape_field
        self.height = height

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"].update(
            shape=self.shape, shape_field=self.shape_field, height=self.height
        )
        return context
