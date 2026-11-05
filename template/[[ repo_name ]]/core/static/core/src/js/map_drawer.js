/* The map drawer of the admin: one shape per field, drawn with Leaflet-Geoman.
 *
 * The textarea of the widget keeps the value as JSON, as the models validate
 * it and the public maps read it:
 *   POINT              {"lat": .., "lng": ..}
 *   POLYLINE, POLYGON  [{"lat": .., "lng": ..}, ...]
 *   CIRCLE             {"lat": .., "lng": .., "radius": ..}
 * Points written by hand as [lat, lng] are read too.
 *
 * In an inline (the items of a map block) the shape comes from the select of
 * the same row, and the other rows are shown in grey around it.
 */
(function () {
    "use strict";

    const L = window.L;
    const DEFAULT_VIEW = { center: [42.5, 12.5], zoom: 5 };
    const DEFAULT_COLOR = "#2a5aa8";
    const CONTEXT_COLOR = "#8a94a3";
    const TOOLS = { POINT: "Marker", POLYLINE: "Line", POLYGON: "Polygon", CIRCLE: "Circle" };
    const IT = {
        tooltips: {
            placeMarker: "Clicca per mettere il punto",
            placeMarkerTouch: "Tocca la mappa per mettere il punto",
            firstVertex: "Clicca per mettere il primo vertice",
            continueLine: "Clicca per aggiungere un vertice",
            finishLine: "Clicca sull'ultimo vertice per finire",
            finishPoly: "Clicca sul primo vertice per chiudere la forma",
            startCircle: "Clicca per mettere il centro del cerchio",
            finishCircle: "Clicca per fissare il raggio",
        },
        actions: {
            finish: "Fine",
            cancel: "Annulla",
            removeLastVertex: "Togli l'ultimo vertice",
        },
        buttonTitles: {
            drawMarkerButton: "Metti il punto",
            drawPolyButton: "Disegna il poligono",
            drawLineButton: "Disegna la linea",
            drawCircleButton: "Disegna il cerchio",
            deleteButton: "Cancella la forma",
        },
    };

    const drawers = [];

    // the basemap of the site when it has one, OpenStreetMap otherwise
    const addBasemap = (map) => {
        if (window.core && window.core.maps) {
            window.core.maps.street(map, map.getContainer());
            return;
        }
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }).addTo(map);
    };

    const round = (number) => Math.round(number * 1e6) / 1e6;
    const toLatLng = (point) =>
        Array.isArray(point) ? L.latLng(point[0], point[1]) : L.latLng(point.lat, point.lng);
    const fromLatLng = (latlng) => ({ lat: round(latlng.lat), lng: round(latlng.lng) });

    const pinIcon = (color) =>
        L.divIcon({
            className: "map-drawer__pin-icon",
            // the 24px pin turned by 45°: its tip is 17px below the centre
            iconSize: [0, 0],
            iconAnchor: [0, 17],
            html: `<span class="map-drawer__pin" style="background-color: ${color}"></span>`,
        });

    const parse = (text) => {
        if (!text.trim()) return null;
        return JSON.parse(text);
    };

    // The Leaflet layer of a stored value; throws on a value of another shape.
    const layerFor = (shape, value, color, context) => {
        const options = context
            ? { color: CONTEXT_COLOR, weight: 2, opacity: 0.7, fillOpacity: 0.1, interactive: false, pmIgnore: true }
            : { color, weight: 3, fillOpacity: 0.2 };
        if (shape === "POINT") {
            return L.marker(toLatLng(value), {
                icon: pinIcon(context ? CONTEXT_COLOR : color),
                interactive: !context,
                pmIgnore: context,
            });
        }
        if (shape === "POLYLINE") return L.polyline(value.map(toLatLng), options);
        if (shape === "POLYGON") return L.polygon(value.map(toLatLng), options);
        if (shape === "CIRCLE") {
            const radius = Number(value.radius);
            if (!(radius > 0)) throw new Error("A circle needs a radius.");
            return L.circle(toLatLng(value), { ...options, radius });
        }
        throw new Error(`Unknown shape ${shape}.`);
    };

    const valueOf = (shape, layer) => {
        if (shape === "POINT") return fromLatLng(layer.getLatLng());
        if (shape === "POLYLINE") return layer.getLatLngs().map(fromLatLng);
        if (shape === "POLYGON") return layer.getLatLngs()[0].map(fromLatLng);
        return { ...fromLatLng(layer.getLatLng()), radius: Math.round(layer.getRadius()) };
    };

    // A search box on Nominatim, run on Enter only, as its usage policy asks.
    const SearchControl = L.Control.extend({
        options: { position: "topright" },

        initialize(drawer, options) {
            L.setOptions(this, options);
            this.drawer = drawer;
        },

        onAdd() {
            const texts = this.drawer.root.dataset;
            const box = L.DomUtil.create("div", "map-drawer__search");
            const form = L.DomUtil.create("div", "map-drawer__search-form", box);
            const input = L.DomUtil.create("input", "form-control form-control-sm", form);
            input.type = "search";
            input.placeholder = texts.searchPlaceholder;
            input.setAttribute("aria-label", texts.searchPlaceholder);
            const button = L.DomUtil.create("button", "btn btn-sm btn-primary", form);
            button.type = "button";
            button.textContent = texts.searchLabel;
            const results = L.DomUtil.create("ul", "map-drawer__results", box);
            results.hidden = true;

            const message = (text) => {
                results.replaceChildren();
                const item = L.DomUtil.create("li", "map-drawer__message", results);
                item.textContent = text;
                results.hidden = false;
            };

            const search = () => {
                const query = input.value.trim();
                if (!query) return;
                const url = new URL("https://nominatim.openstreetmap.org/search");
                url.search = new URLSearchParams({
                    format: "jsonv2",
                    limit: "5",
                    q: query,
                    "accept-language": document.documentElement.lang || "it",
                });
                fetch(url)
                    .then((response) => {
                        if (!response.ok) throw new Error(response.statusText);
                        return response.json();
                    })
                    .then((places) => {
                        if (!places.length) {
                            message(texts.searchEmpty);
                            return;
                        }
                        results.replaceChildren();
                        places.forEach((place) => {
                            const item = L.DomUtil.create("li", "", results);
                            const choice = L.DomUtil.create("button", "", item);
                            choice.type = "button";
                            choice.textContent = place.display_name;
                            choice.addEventListener("click", () => {
                                results.hidden = true;
                                this.drawer.goTo(place);
                            });
                        });
                        results.hidden = false;
                    })
                    .catch(() => message(texts.searchError));
            };

            input.addEventListener("keydown", (event) => {
                if (event.key !== "Enter") return;
                // Enter would save the admin form
                event.preventDefault();
                search();
            });
            input.addEventListener("search", () => {
                if (!input.value) results.hidden = true;
            });
            button.addEventListener("click", search);
            L.DomEvent.disableClickPropagation(box);
            L.DomEvent.disableScrollPropagation(box);
            return box;
        },
    });

    class Drawer {
        constructor(root) {
            this.root = root;
            this.textarea = root.querySelector("textarea");
            this.raw = root.querySelector(".map-drawer__raw");
            this.rawToggle = root.querySelector(".map-drawer__raw-toggle");
            this.rawToggle.addEventListener("click", () => this.showRaw(this.raw.hidden));
            this.form = this.textarea.form || document;
            // "items-0-coordinates" -> "items-0-": the other fields of the row
            this.prefix = this.textarea.name.replace(/[^-]*$/, "");
            this.shapeSelect = root.dataset.shapeField
                ? this.form.querySelector(`[name="${this.prefix}${root.dataset.shapeField}"]`)
                : null;
            this.colorInput = this.shapeSelect
                ? this.form.querySelector(`[name="${this.prefix}color"]`)
                : null;
            // the rows of the same inline see each other
            this.group = this.shapeSelect ? this.prefix.replace(/\d+-$/, "") : null;
            this.layer = null;
            this.fitted = false;

            // the wheel scrolls the form until the map is clicked
            this.map = L.map(root.querySelector(".map-drawer__map"), {
                ...DEFAULT_VIEW,
                scrollWheelZoom: false,
            });
            this.map.on("click focus", () => this.map.scrollWheelZoom.enable());
            this.map.on("mouseout blur", () => this.map.scrollWheelZoom.disable());
            addBasemap(this.map);
            this.context = L.featureGroup().addTo(this.map);
            if (document.documentElement.lang === "it") {
                this.map.pm.setLang("iai-it", IT, "it");
            }
            this.map.addControl(new SearchControl(this));

            this.map.on("pm:create", (event) => {
                this.replaceLayer(event.layer);
                this.write();
            });
            this.map.on("pm:remove", (event) => {
                if (event.layer !== this.layer) return;
                this.layer = null;
                this.write();
                this.startDrawing();
            });
            this.textarea.addEventListener("change", () => this.read());
            if (this.shapeSelect) {
                this.shapeSelect.addEventListener("change", () => {
                    // the coordinates of another shape are of no use
                    this.textarea.value = "";
                    this.read();
                });
            }
            if (this.colorInput) {
                this.colorInput.addEventListener("input", () => this.restyle());
                this.colorInput.addEventListener("change", () => this.restyle());
            }

            // hidden in a tab or a closed accordion, the map has no size yet
            new ResizeObserver(() => {
                const container = this.map.getContainer();
                if (!container.offsetWidth || !container.offsetHeight) return;
                this.map.invalidateSize();
                if (!this.fitted) {
                    this.fitted = true;
                    this.fit();
                }
            }).observe(this.map.getContainer());

            this.read();
        }

        get shape() {
            return this.shapeSelect ? this.shapeSelect.value : this.root.dataset.shape;
        }

        get color() {
            const color = this.colorInput && this.colorInput.value;
            return /^#[0-9a-f]{6}$/i.test(color || "") ? color : DEFAULT_COLOR;
        }

        // Shows the value of the textarea; a value it can't draw opens the textarea.
        read() {
            if (this.layer) this.layer.remove();
            this.layer = null;
            let value = null;
            try {
                value = parse(this.textarea.value);
                if (value) this.replaceLayer(layerFor(this.shape, value, this.color, false));
            } catch (error) {
                this.showRaw(true);
            }
            this.setTools();
            if (!this.layer) this.startDrawing();
            if (this.fitted) this.fit();
            refreshGroup(this.group);
        }

        showRaw(show) {
            this.raw.hidden = !show;
            this.rawToggle.setAttribute("aria-expanded", String(show));
        }

        write() {
            this.textarea.value = this.layer ? JSON.stringify(valueOf(this.shape, this.layer)) : "";
            refreshGroup(this.group);
        }

        replaceLayer(layer) {
            if (this.layer && this.layer !== layer) this.layer.remove();
            this.layer = layer;
            layer.addTo(this.map);
            // always editable: vertices, radius and the whole shape can be dragged
            layer.pm.enable({ draggable: true });
            layer.on("pm:edit pm:dragend", () => this.write());
            this.map.pm.disableDraw();
        }

        setTools() {
            const tool = TOOLS[this.shape];
            const color = this.color;
            this.map.pm.setGlobalOptions({
                continueDrawing: false,
                markerStyle: { icon: pinIcon(color) },
                pathOptions: { color, weight: 3, fillOpacity: 0.2 },
                templineStyle: { color },
                hintlineStyle: { color, dashArray: [5, 5] },
            });
            this.map.pm.removeControls();
            this.map.pm.addControls({
                position: "topleft",
                drawMarker: tool === "Marker",
                drawPolyline: tool === "Line",
                drawPolygon: tool === "Polygon",
                drawCircle: tool === "Circle",
                drawCircleMarker: false,
                drawRectangle: false,
                drawText: false,
                editMode: false,
                dragMode: false,
                cutPolygon: false,
                rotateMode: false,
                removalMode: true,
            });
        }

        startDrawing() {
            const tool = TOOLS[this.shape];
            if (tool) this.map.pm.enableDraw(tool);
        }

        restyle() {
            this.setTools();
            if (!this.layer) return;
            if (this.shape === "POINT") this.layer.setIcon(pinIcon(this.color));
            else this.layer.setStyle({ color: this.color });
        }

        fit() {
            if (this.layer && this.shape === "POINT") {
                this.map.setView(this.layer.getLatLng(), 15);
            } else if (this.layer) {
                this.map.fitBounds(this.layer.getBounds(), { padding: [30, 30], maxZoom: 16 });
            } else if (this.context.getLayers().length) {
                this.map.fitBounds(this.context.getBounds(), { padding: [30, 30], maxZoom: 15 });
            } else {
                this.map.setView(DEFAULT_VIEW.center, DEFAULT_VIEW.zoom);
            }
        }

        // A place found by the search: a point goes there, the other shapes are drawn around it.
        goTo(place) {
            const latlng = L.latLng(Number(place.lat), Number(place.lon));
            if (this.shape === "POINT") {
                this.replaceLayer(layerFor("POINT", latlng, this.color, false));
                this.write();
                this.map.setView(latlng, 16);
                return;
            }
            const [south, north, west, east] = place.boundingbox.map(Number);
            this.map.fitBounds([[south, west], [north, east]], { maxZoom: 16 });
        }

        // The shapes of the other rows, in grey.
        showContext(others) {
            this.context.clearLayers();
            others.forEach((other) => {
                try {
                    const value = parse(other.textarea.value);
                    if (value) this.context.addLayer(layerFor(other.shape, value, null, true));
                } catch (error) {
                    // a row being fixed by hand is left out
                }
            });
            this.context.bringToBack();
        }
    }

    function refreshGroup(group) {
        if (!group) return;
        const members = drawers.filter((drawer) => drawer.group === group);
        members.forEach((drawer) => drawer.showContext(members.filter((other) => other !== drawer)));
    }

    function init(container) {
        const groups = new Set();
        container.querySelectorAll("[data-map-drawer]").forEach((root) => {
            const textarea = root.querySelector("textarea");
            // the empty row an inline clones when adding another
            if (root.dataset.mapDrawerReady || textarea.name.includes("__prefix__")) return;
            root.dataset.mapDrawerReady = "true";
            const drawer = new Drawer(root);
            drawers.push(drawer);
            groups.add(drawer.group);
        });
        groups.forEach(refreshGroup);
    }

    document.addEventListener("DOMContentLoaded", () => init(document));
    document.addEventListener("formset:added", (event) => init(event.target));
})();
