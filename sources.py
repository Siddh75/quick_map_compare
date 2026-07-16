"""Map-source logic for QuickMapCompare: provider/basemap definitions, provider URL
building, the built-in XYZ tile basemap layer builder, user API key storage, and the
coordinate/zoom helpers those depend on.

Deliberately duplicated from QuickMapLink (URL-building, zoom estimation, coordinate
transforms) rather than shared -- QuickMapCompare is an independent plugin, not a
shared codebase with QuickMapLink.

Kept separate from quick_map_compare.py (which holds the Qt/QGIS widget classes) so
adding or tweaking a map source doesn't require touching the UI code, and vice versa.
"""

import math

from qgis.PyQt.QtCore import QSettings
from qgis.core import (
    QgsProject, QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsRasterLayer,
)

# Bing Maps and Apple Maps are intentionally left out of the viewport source list.
# QuickMapLink already routes both to browser-only mode because Bing's GPU-heavy
# renderer is known to hard-crash QGIS in an embedded QWebEngineView on some
# systems/drivers, and Apple Maps is unreliable when embedded. QuickMapCompare can
# have several embedded web views open at the same time (one per provider tile),
# which only multiplies that risk, so both are excluded outright here rather than
# offered with a warning.
GOOGLE_JS_PROVIDER = "Google Maps (JS)"
WAYMARKED_HIKING_PROVIDER = "Waymarked Trails (Hiking)"

PROVIDERS = [
    "Google Maps", GOOGLE_JS_PROVIDER, "OpenTopoMap", "Wikimedia Maps",
    # Specialized OSM-family layers -- each has its own public demo site using the
    # same hash- or query-based "go to this lat/lon/zoom" convention OpenTopoMap
    # and Wikimedia Maps already use above, so they slot into the same URL-embed
    # webview pattern with no API key needed. (CyclOSM isn't here -- see
    # TILE_BASEMAPS below: its own demo site pops up a recurring "About" modal on
    # every load, so it's rendered as a native tile basemap instead.)
    "OpenSeaMap", "OpenRailwayMap", "OpenSnowMap", WAYMARKED_HIKING_PROVIDER,
    # Weather -- RainViewer and Windy both have free, no-key embeddable web maps.
    # (OpenWeatherMap and NOAA Weather were deliberately left out: OpenWeatherMap
    # needs a paid/keyed tile endpoint and NOAA has no simple public tile/view
    # endpoint to embed the same way.)
    "RainViewer", "Windy",
]

PROVIDER_BASEMAPS = {
    "Google Maps": ["Roadmap", "Satellite", "Terrain"],
    GOOGLE_JS_PROVIDER: ["Roadmap", "Satellite", "Terrain"],
    "OpenTopoMap": ["Topographic"],
    "Wikimedia Maps": ["Standard"],
    "OpenSeaMap": ["Standard"],
    "OpenRailwayMap": ["Standard", "Max Speed", "Signals", "Electrification"],
    "OpenSnowMap": ["Standard"],
    WAYMARKED_HIKING_PROVIDER: ["Standard"],
    "RainViewer": ["Standard"],
    "Windy": ["Standard"],
}
PROVIDER_OVERLAYS = {
    "Google Maps": ["None", "Traffic", "Transit", "Bicycling"],
    GOOGLE_JS_PROVIDER: ["None", "Traffic", "Transit", "Bicycling"],
    "OpenTopoMap": ["None"],
    "Wikimedia Maps": ["None"],
    "OpenSeaMap": ["None"],
    "OpenRailwayMap": ["None"],
    "OpenSnowMap": ["None"],
    WAYMARKED_HIKING_PROVIDER: ["None"],
    "RainViewer": ["None"],
    "Windy": ["Wind", "Rain", "Temperature", "Clouds", "Pressure"],
}

# Built-in raster tile basemaps (Terrain/Relief group) -- unlike the "provider"
# entries above, these aren't websites to embed; they're plain XYZ tile services
# with no view of their own. They're rendered natively via QgsMapCanvas exactly
# like a QGIS-layer viewport (see ViewportTileWidget._build_basemap_body /
# _make_xyz_raster_layer): pixel-perfect setExtent() sync, no webview/GPU crash
# risk, and no per-provider zoom-estimation math needed at all.
TILE_BASEMAPS = {
    "Esri World Hillshade": {
        "url": "https://services.arcgisonline.com/arcgis/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
        "zmax": 16,
    },
    "Esri World Topographic": {
        "url": "https://services.arcgisonline.com/arcgis/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "zmax": 19,
    },
    "USGS Topo": {
        "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        "zmax": 16,
    },
    # Stamen's tiles moved to Stadia Maps hosting; non-localhost use (which QGIS
    # always is) needs either domain auth or an API key -- see get_stadia_api_key /
    # the "Set Stadia Maps API Key..." Plugins-menu action. Without a key this will
    # likely fail to load, hence "(where still available)" in the original request.
    "Stamen Terrain": {
        "url": "https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}.png",
        "zmax": 18,
        "needs_stadia_key": True,
    },
    # Not Terrain/Relief sources, but rendered the same way for the same reason:
    # both OpenStreetMap.org and CyclOSM's own demo sites pop up their own modals/
    # UI chrome on every page load, which reappears on every sync since that's a
    # page reload -- their public tile services sidestep that (and the webview/
    # reload entirely). OpenStreetMap was previously offered as a webview provider
    # and was removed at that point; it's back here as a native tile layer instead.
    "OpenStreetMap": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "zmax": 19,
    },
    "CyclOSM": {
        "url": "https://a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
        "zmax": 20,
    },
}

# Settings keys for user-supplied API keys (see QuickMapComparePlugin.set_google_api_key
# / set_stadia_api_key). Same QSettings organization QuickMapLink uses, distinct
# application name so the two plugins' settings don't collide.
SETTINGS_ORG = "MyOrganization"
SETTINGS_APP = "QuickMapCompare Settings"
GOOGLE_JS_API_KEY_SETTING = "google_js_api_key"
STADIA_API_KEY_SETTING = "stadia_maps_api_key"


def get_google_js_api_key():
    return QSettings(SETTINGS_ORG, SETTINGS_APP).value(GOOGLE_JS_API_KEY_SETTING, "", type=str)


def set_google_js_api_key(key):
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(GOOGLE_JS_API_KEY_SETTING, key)


def get_stadia_api_key():
    return QSettings(SETTINGS_ORG, SETTINGS_APP).value(STADIA_API_KEY_SETTING, "", type=str)


def set_stadia_api_key(key):
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(STADIA_API_KEY_SETTING, key)


def _make_xyz_raster_layer(name):
    """Build a QgsRasterLayer for one of the built-in TILE_BASEMAPS entries. QGIS's
    "wms" provider handles plain XYZ tile URLs via a "type=xyz&url=..." data source
    string -- the {z}/{x}/{y} tokens are substituted by QGIS itself and must stay
    literal, and none of these URLs contain "&", so no percent-encoding is needed."""
    config = TILE_BASEMAPS.get(name)
    if config is None:
        return None

    url = config["url"]
    if config.get("needs_stadia_key"):
        key = get_stadia_api_key()
        if key:
            url = f"{url}?api_key={key}"

    zmax = config.get("zmax", 19)
    uri = f"type=xyz&url={url}&zmax={zmax}&zmin=0"
    return QgsRasterLayer(uri, name, "wms")


def _provider_has_style_options(provider):
    """True if this provider actually has more than one basemap or overlay choice
    -- OpenTopoMap and Wikimedia Maps each only have a single style, so a settings
    icon offering nothing to change would just be clutter."""
    return len(PROVIDER_BASEMAPS.get(provider, [])) > 1 or len(PROVIDER_OVERLAYS.get(provider, [])) > 1


def get_wgs84_point(map_point, project_crs):
    """Transform a QgsPointXY in project coordinates to (latitude, longitude) in
    WGS84 -- duplicated from QuickMapLink's _map_point_to_wgs84."""
    if project_crs.authid() != "EPSG:4326":
        transform = QgsCoordinateTransform(
            project_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        map_point = transform.transform(map_point)
    return map_point.y(), map_point.x()


def get_canvas_center_wgs84(main_canvas):
    project_crs = QgsProject.instance().crs()
    center = main_canvas.extent().center()
    return get_wgs84_point(center, project_crs)


def estimate_zoom_level(main_canvas, tile_width_px):
    """Approximate a web-mercator zoom level for a viewport tile_width_px pixels wide
    that shows the same geographic extent (width-wise) as the main QGIS canvas --
    duplicated/adapted from QuickMapLink's estimate_zoom_level, parameterized on the
    tile's own pixel width so a tile sized differently than the main canvas still
    ends up showing roughly the same area rather than a fixed zoom."""
    extent = main_canvas.extent()
    project_crs = QgsProject.instance().crs()

    if project_crs.authid() != "EPSG:4326":
        transform = QgsCoordinateTransform(
            project_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        extent = transform.transformBoundingBox(extent)

    width_deg = extent.width()
    tile_width_px = tile_width_px or 400

    if width_deg <= 0:
        return 15.0

    # At zoom z, a 256px tile covers 360 degrees / 2^z of longitude.
    return math.log2(360.0 * tile_width_px / (256.0 * width_deg))


def _mercator_pixel(latitude, longitude, zoom):
    """Standard spherical web-mercator pixel position (256px tiles) for a lat/lon
    at an integer zoom -- duplicated from QuickMapLink's _CursorOverlay helper.
    The *difference* between two such pixel positions is a reliable on-screen
    offset for any of the Leaflet/Google-style providers here, regardless of
    which one is actually showing."""
    scale = 256 * (2 ** zoom)
    x = (longitude + 180.0) / 360.0 * scale
    lat_rad = math.radians(max(min(latitude, 85.05112878), -85.05112878))
    merc_y = math.log(math.tan(math.pi / 4 + lat_rad / 2))
    y = (0.5 - merc_y / (2 * math.pi)) * scale
    return x, y


def build_provider_url(provider, basemap, overlay, latitude, longitude, zoom):
    if provider == "OpenTopoMap":
        return _build_opentopomap_url(latitude, longitude, zoom)
    elif provider == "Wikimedia Maps":
        return _build_wikimedia_url(latitude, longitude, zoom)
    elif provider == "OpenSeaMap":
        return _build_openseamap_url(latitude, longitude, zoom)
    elif provider == "OpenRailwayMap":
        return _build_openrailwaymap_url(latitude, longitude, zoom, basemap)
    elif provider == "OpenSnowMap":
        return _build_opensnowmap_url(latitude, longitude, zoom)
    elif provider == WAYMARKED_HIKING_PROVIDER:
        return _build_waymarked_trails_url(latitude, longitude, zoom)
    elif provider == "RainViewer":
        return _build_rainviewer_url(latitude, longitude, zoom)
    elif provider == "Windy":
        return _build_windy_url(latitude, longitude, zoom, overlay)
    else:
        return _build_google_url(latitude, longitude, zoom, basemap, overlay)  # default


def _build_google_url(latitude, longitude, zoom, basemap, overlay):
    # https://developers.google.com/maps/documentation/urls/get-started#map-action
    basemap_param = {"Roadmap": "roadmap", "Satellite": "satellite", "Terrain": "terrain"}.get(
        basemap, "roadmap")
    layer_param = {"None": "none", "Traffic": "traffic", "Transit": "transit", "Bicycling": "bicycling"}.get(
        overlay, "none")
    zoom = round(max(0, min(21, zoom)))
    return (f"https://www.google.com/maps/@?api=1&map_action=map&center={latitude},{longitude}"
            f"&zoom={zoom}&basemap={basemap_param}&layer={layer_param}")


def _build_opentopomap_url(latitude, longitude, zoom):
    # https://opentopomap.org -- single topographic/contour style, tiles top out ~z17.
    zoom = round(max(0, min(17, zoom)))
    return f"https://opentopomap.org/#map={zoom}/{latitude}/{longitude}"


def _build_wikimedia_url(latitude, longitude, zoom):
    # https://maps.wikimedia.org -- single default OSM-based style.
    zoom = round(max(0, min(18, zoom)))
    return f"https://maps.wikimedia.org/#{zoom}/{latitude}/{longitude}"


def _build_openseamap_url(latitude, longitude, zoom):
    # https://map.openseamap.org -- nautical charts/marks over an OSM base.
    zoom = round(max(0, min(18, zoom)))
    return f"https://map.openseamap.org/?zoom={zoom}&lat={latitude}&lon={longitude}"


_OPENRAILWAYMAP_STYLES = {
    "Standard": "standard",
    "Max Speed": "maxspeed",
    "Signals": "signals",
    "Electrification": "electrification",
}


def _build_openrailwaymap_url(latitude, longitude, zoom, basemap):
    # https://www.openrailwaymap.org -- several render styles selectable via ?style=.
    style = _OPENRAILWAYMAP_STYLES.get(basemap, "standard")
    zoom = round(max(0, min(19, zoom)))
    return f"https://www.openrailwaymap.org/?style={style}&lat={latitude}&lon={longitude}&zoom={zoom}"


def _build_opensnowmap_url(latitude, longitude, zoom):
    # https://www.opensnowmap.org -- ski piste map; embed.html drops the site's own chrome.
    zoom = round(max(0, min(18, zoom)))
    return f"https://www.opensnowmap.org/embed.html?zoom={zoom}&lat={latitude}&lon={longitude}"


def _build_waymarked_trails_url(latitude, longitude, zoom):
    # https://hiking.waymarkedtrails.org -- hiking-route overlay on an OSM base.
    zoom = round(max(0, min(18, zoom)))
    return f"https://hiking.waymarkedtrails.org/#map={zoom}/{latitude}/{longitude}/0"


def _build_rainviewer_url(latitude, longitude, zoom):
    # https://www.rainviewer.com -- live radar; "loc" is lat,lon,zoom. The radar
    # tiles themselves top out around z7-8, but the page accepts a closer zoom.
    zoom = round(max(0, min(18, zoom)))
    return f"https://www.rainviewer.com/map.html?loc={latitude},{longitude},{zoom}"


_WINDY_OVERLAYS = {
    "Wind": "wind",
    "Rain": "rain",
    "Temperature": "temp",
    "Clouds": "clouds",
    "Pressure": "pressure",
}


def _build_windy_url(latitude, longitude, zoom, overlay):
    # community.windy.com/topic/77 -- lat, lon, zoom must come first and in that
    # order; everything else is optional. No API key needed for the free embed
    # widget (unlike Windy's Point Forecast / Map Forecast APIs).
    overlay_param = _WINDY_OVERLAYS.get(overlay, "wind")
    zoom = round(max(0, min(18, zoom)))
    return (f"https://embed.windy.com/embed2.html?lat={latitude}&lon={longitude}&zoom={zoom}"
            f"&detailLat={latitude}&detailLon={longitude}&overlay={overlay_param}"
            f"&level=surface&type=map&location=coordinates&metricWind=default&metricTemp=default")


# "Google Maps" (above) embeds the ordinary maps.google.com web page via the URL
# scheme -- simple and needs no API key, but it's still Google's own web UI: search
# bar, sign-in prompt, "Heavy traffic in this area" popups, etc, which can't be
# suppressed since it's just a normal page load. "Google Maps (JS)" instead drives
# the Google Maps JavaScript API directly with disableDefaultUI and every individual
# control switched off, so the tile shows nothing but the map. Requires a Google
# Maps JavaScript API key (see get_google_js_api_key / the "Set Google Maps API
# Key..." Plugins-menu action) -- unlike the URL-scheme provider, this one calls a
# billed Google API.
_GOOGLE_JS_MAP_TYPES = {"Roadmap": "roadmap", "Satellite": "satellite", "Terrain": "terrain"}
_GOOGLE_JS_OVERLAY_LAYERS = {
    "Traffic": "TrafficLayer",
    "Transit": "TransitLayer",
    "Bicycling": "BicyclingLayer",
}


def _build_google_js_html(latitude, longitude, zoom, basemap, overlay, api_key):
    if not api_key:
        return (
            "<html><body style=\"margin:0;height:100%;display:flex;align-items:center;"
            "justify-content:center;text-align:center;padding:12px;"
            "font-family:sans-serif;color:#888;\">"
            "No Google Maps JavaScript API key set.<br>"
            "Plugins &gt; QuickMapCompare &gt; Set Google Maps API Key&hellip;"
            "</body></html>")

    map_type_id = _GOOGLE_JS_MAP_TYPES.get(basemap, "roadmap")
    overlay_layer_class = _GOOGLE_JS_OVERLAY_LAYERS.get(overlay)
    overlay_js = f"new google.maps.{overlay_layer_class}().setMap(map);" if overlay_layer_class else ""
    zoom = round(max(0, min(21, zoom)))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>html, body, #map {{ height: 100%; margin: 0; padding: 0; }}</style>
</head>
<body>
<div id="map"></div>
<script>
function initMap() {{
  const map = new google.maps.Map(document.getElementById("map"), {{
    center: {{ lat: {latitude}, lng: {longitude} }},
    zoom: {zoom},
    mapTypeId: "{map_type_id}",
    disableDefaultUI: true,
    zoomControl: false,
    streetViewControl: false,
    mapTypeControl: false,
    fullscreenControl: false,
    rotateControl: false,
    scaleControl: false,
    keyboardShortcuts: false
  }});
  {overlay_js}
}}
</script>
<script src="https://maps.googleapis.com/maps/api/js?key={api_key}&callback=initMap" async defer></script>
</body>
</html>"""
