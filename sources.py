"""Map-source logic for QuickMapCompare: provider/basemap definitions, provider URL
building, the built-in XYZ tile basemap layer builder, and the coordinate/zoom
helpers those depend on.

Deliberately duplicated from QuickMapLink (URL-building, zoom estimation, coordinate
transforms) rather than shared -- QuickMapCompare is an independent plugin, not a
shared codebase with QuickMapLink.

Kept separate from quick_map_compare.py (which holds the Qt/QGIS widget classes) so
adding or tweaking a map source doesn't require touching the UI code, and vice versa.
"""

import math

from qgis.core import (
    QgsProject, QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsRasterLayer,
)

# Bing Maps and Apple Maps are intentionally left out of the *Web Map Providers*
# (embedded webview) list. QuickMapLink already routes both to browser-only mode
# because Bing's GPU-heavy renderer is known to hard-crash QGIS in an embedded
# QWebEngineView on some systems/drivers, and Apple Maps is unreliable when
# embedded. QuickMapCompare can have several embedded web views open at the same
# time (one per provider tile), which only multiplies that risk, so both are
# excluded outright here rather than offered with a warning. Bing's aerial tiles
# are still available below as a native "WMS/XYZ tiles" basemap (see
# TILE_BASEMAPS) -- that route renders via QgsMapCanvas, not a webview, so it
# doesn't carry the same crash risk; Apple Maps has no equivalent public tile
# endpoint to offer that way.

PROVIDERS = [
    "Google Maps", "Wikimedia Maps",
    # Specialized OSM-family layers -- each has its own public demo site using the
    # same hash- or query-based "go to this lat/lon/zoom" convention Wikimedia Maps
    # already uses above, so they slot into the same URL-embed webview pattern
    # with no API key needed.
    "OpenRailwayMap", "OpenSnowMap",
]

PROVIDER_BASEMAPS = {
    "Google Maps": ["Roadmap", "Satellite", "Terrain"],
    "Wikimedia Maps": ["Standard"],
    "OpenRailwayMap": ["Standard", "Max Speed", "Signals", "Electrification"],
    "OpenSnowMap": ["Standard"],
}
PROVIDER_OVERLAYS = {
    "Google Maps": ["None", "Traffic", "Transit", "Bicycling"],
    "Wikimedia Maps": ["None"],
    "OpenRailwayMap": ["None"],
    "OpenSnowMap": ["None"],
}

# Built-in raster tile basemaps -- unlike the "provider" entries above, these
# aren't websites to embed; they're plain XYZ tile services with no view of
# their own. They're rendered natively via QgsMapCanvas exactly like a
# QGIS-layer viewport (see ViewportTileWidget._build_basemap_body /
# _make_xyz_raster_layer): pixel-perfect setExtent() sync, no webview/GPU crash
# risk, and no per-provider zoom-estimation math needed at all.
#
# Each entry has a "styles" dict of {style name: tile URL template}. Entries
# with only one style (most of them) don't show a settings-gear icon on their
# tile; entries with more than one (currently "Google Maps" and "CartoDB") do,
# opening a small dialog to switch between them without removing/re-adding the
# tile (see ViewportTileWidget._rebuild_basemap_layer).
TILE_BASEMAPS = {
    "Esri World Hillshade": {
        "styles": {
            "Standard": "https://services.arcgisonline.com/arcgis/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
        },
        "zmax": 16,
    },
    "Esri World Topographic": {
        "styles": {
            "Standard": "https://services.arcgisonline.com/arcgis/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        },
        "zmax": 19,
    },
    "USGS Topo": {
        "styles": {
            "Standard": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        },
        "zmax": 16,
    },
    # Not Terrain/Relief sources, but rendered the same way for the same reason:
    # both OpenStreetMap.org and CyclOSM's own demo sites pop up their own modals/
    # UI chrome on every page load, which reappears on every sync since that's a
    # page reload -- their public tile services sidestep that (and the webview/
    # reload entirely). OpenStreetMap was previously offered as a webview provider
    # and was removed at that point; it's back here as a native tile layer instead.
    "OpenStreetMap": {
        "styles": {
            "Standard": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        },
        "zmax": 19,
    },
    "CyclOSM": {
        "styles": {
            "Standard": "https://a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
        },
        "zmax": 20,
    },
    # Native tile version of Google Maps -- no API key, no webview chrome/popups,
    # pixel-perfect setExtent() sync like any other basemap here. Kept as a
    # single entry with a style picker (via the settings-gear icon) rather than
    # four separate basemap entries. This is independent of the "Google Maps"
    # *Web Map Provider* above (that one's a real maps.google.com page embed);
    # either can be used, whichever fits.
    "Google Maps": {
        "styles": {
            "Roadmap": "https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
            "Satellite": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            "Terrain": "https://mt1.google.com/vt/lyrs=t&x={x}&y={y}&z={z}",
            "Hybrid": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        },
        "zmax": 20,
    },
    "CartoDB": {
        "styles": {
            "Light": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
            "Dark": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
            "Voyager": "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        },
        "zmax": 20,
    },
    "Esri Ocean": {
        "styles": {
            "Standard": "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
        },
        "zmax": 13,
    },
    "Esri NatGeo": {
        "styles": {
            "Standard": "https://server.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}",
        },
        "zmax": 16,
    },
    "Esri Light Gray": {
        "styles": {
            "Standard": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        },
        "zmax": 16,
    },
    # Uses Bing's quadkey tile addressing ("{q}") rather than {z}/{x}/{y} --
    # QGIS's XYZ tile source supports this token natively. "a" in the URL path
    # selects Bing's aerial imagery layer specifically.
    "Bing Maps (Aerial)": {
        "styles": {
            "Standard": "http://ecn.t3.tiles.virtualearth.net/tiles/a{q}.jpeg?g=1",
        },
        "zmax": 19,
    },
}


def _make_xyz_raster_layer(name, style=None):
    """Build a QgsRasterLayer for one of the built-in TILE_BASEMAPS entries, using
    the given style name (falls back to the entry's first/only style if the given
    one isn't found). QGIS's "wms" provider handles plain XYZ tile URLs via a
    "type=xyz&url=..." data source string -- the {z}/{x}/{y}/{q} tokens are
    substituted by QGIS itself and must stay literal, and none of these URLs
    contain "&", so no percent-encoding is needed."""
    config = TILE_BASEMAPS.get(name)
    if config is None:
        return None

    styles = config["styles"]
    url = styles.get(style) if style in styles else next(iter(styles.values()))
    zmax = config.get("zmax", 19)
    uri = f"type=xyz&url={url}&zmax={zmax}&zmin=0"
    return QgsRasterLayer(uri, name, "wms")


def _basemap_styles(name):
    """List of style names for a TILE_BASEMAPS entry, in definition order."""
    return list(TILE_BASEMAPS.get(name, {}).get("styles", {}).keys())


def _basemap_has_style_options(name):
    """True if this basemap has more than one style to choose from (currently
    "Google Maps" and "CartoDB") -- everything else is a single fixed tile
    service, so a settings icon offering nothing to change would just be
    clutter."""
    return len(_basemap_styles(name)) > 1


def _provider_has_style_options(provider):
    """True if this provider actually has more than one basemap or overlay choice
    -- Wikimedia Maps, OpenSnowMap etc. each only have a single style, so a
    settings icon offering nothing to change would just be clutter."""
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
    if provider == "Wikimedia Maps":
        return _build_wikimedia_url(latitude, longitude, zoom)
    elif provider == "OpenRailwayMap":
        return _build_openrailwaymap_url(latitude, longitude, zoom, basemap)
    elif provider == "OpenSnowMap":
        return _build_opensnowmap_url(latitude, longitude, zoom)
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


def _build_wikimedia_url(latitude, longitude, zoom):
    # https://maps.wikimedia.org -- single default OSM-based style.
    zoom = round(max(0, min(18, zoom)))
    return f"https://maps.wikimedia.org/#{zoom}/{latitude}/{longitude}"


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
