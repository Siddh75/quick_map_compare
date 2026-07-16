# QuickMapCompare QGIS Plugin

[![License: GPL v2+](https://img.shields.io/badge/License-GPL%20v2+-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)
![QGIS Version](https://img.shields.io/badge/QGIS-%3E%3D%203.16-brightgreen.svg)

Build a grid of side-by-side "viewports" in a single dockable panel to compare QGIS layers and web map providers at once, with per-viewport live sync to the main map canvas.

This is a standalone plugin, independent from [QuickMapLink](https://github.com/Siddh75/quick_map_link) (which opens a single location in an external web map from the canvas right-click menu). QuickMapCompare reuses the same idea of web map providers, but for side-by-side comparison rather than a single "open this location" action. The two plugins share no code — provider URL-building, zoom estimation, and coordinate transforms are duplicated independently in each.

## Features

*   **A grid of viewports in one dockable panel:** click "Add Viewport" to append a new tile; tiles arrange themselves in a roughly square grid (1→1×1, 2→1×2, 4→2×2, 5→2×3, ...) that reflows automatically as tiles are added or removed.
*   **Resizable viewports:** tiles sit in nested splitters (a vertical splitter of horizontal rows), so you can drag the dividers between tiles to resize them, the same way you'd resize QGIS's own panels.
*   **Three kinds of viewport:**
    *   **QGIS layer:** rendered natively via QGIS's own `QgsMapCanvas` — the same embeddable widget QGIS's own "Panels > New Map View" uses.
    *   **Basemap tile layer:** built-in XYZ tile basemaps rendered natively via `QgsMapCanvas`, not a webview — OpenStreetMap, CyclOSM, Esri World Hillshade, Esri World Topographic, USGS Topo, Stamen Terrain. No GPU/webview crash risk, no site chrome/popups, and sync is just as pixel-perfect as a QGIS layer.
    *   **Web map provider:** Google Maps, Google Maps (JS), OpenTopoMap, Wikimedia Maps, OpenSeaMap, OpenRailwayMap, OpenSnowMap, Waymarked Trails (Hiking), RainViewer, or Windy, embedded via a webview.
*   **Floating overlay controls:** each tile has a semi-transparent bar over the top of its content (it doesn't take up separate space) — Sync, Change source, and (when relevant) Style settings icons at the top-left, Close at the top-right. Hover the bar to see what the tile is currently showing.
*   **Per-viewport Sync toggle:** when enabled, that viewport live-follows the main QGIS map canvas as you pan and zoom. When disabled, it stays static. Layer and basemap-tile viewports sync instantly (same rendering engine, pixel-perfect `setExtent()`); provider viewports sync with a short debounce (~400ms) since each update reloads a web page.
*   **Per-tile style settings:** provider viewports that actually have more than one basemap or overlay choice (Google Maps, Google Maps (JS), OpenRailwayMap, Windy) show a settings (gear) icon opening a small dialog with those options; providers with only one style (OpenTopoMap, Wikimedia Maps, OpenSeaMap, OpenSnowMap, Waymarked Trails, RainViewer) don't show a settings icon.
*   **Mouse-cursor crosshair:** every viewport shows a small crosshair tracking where the QGIS canvas mouse cursor currently falls — pixel-perfect for layer and basemap-tile viewports (same rendering engine), computed via web-mercator math against each tile's last-set center/zoom for provider viewports (same technique QuickMapLink uses for its webview).
*   **Change source / remove:** each tile can swap what it's showing, or be removed entirely — the grid reflows to fill the gap.
*   **Swipe Compare:** layer and basemap-tile viewports have an "Add to Swipe Compare" icon in their overlay bar, cycling off → horizontal → vertical → off on each click. With one armed, hold **S** and move the mouse over the main QGIS canvas to swipe between the live canvas and that viewport — composited directly onto the canvas itself, no separate window.

## Swipe Compare

Click the "Add to Swipe Compare" icon on a layer or basemap-tile viewport's overlay bar to cycle it through three states: **off → horizontal → vertical → off** (arming one un-arms whichever other tile had it armed — there's only one active target at a time). Click on the main canvas so it has focus, then press and hold **S** and move the mouse:

*   **Horizontal mode** (a vertical divider, dragged left/right): everything to the left of the cursor is replaced by the armed viewport's content.
*   **Vertical mode** (a horizontal divider, dragged up/down): everything above the cursor is replaced instead.

Release S to go back to the normal canvas view.

Web map provider viewports (Google Maps, OpenTopoMap, and the rest) don't offer the icon — there's no reliable way to composite an external web page's rendering onto the live QGIS canvas at interactive, press-and-drag speed the way a `QgsMapCanvas`-based viewport allows, so rather than offer something flaky, they're excluded from swipe entirely.

Under the hood, an event filter installed on `iface.mapCanvas()` handles the key press/release and mouse move, and a transparent child widget parented directly onto the canvas's viewport paints the armed viewport's content over the appropriate side of the divider — ordinary parent/child Qt compositing, so the untouched portion simply shows the real canvas through it with no special translucency setup needed. The armed viewport's content itself comes from a same-size, same-extent `QgsMapCanvas` "mirror" rendered once when S is first pressed (moving the mouse afterward just repositions the divider, no re-render needed) — the mirror waits for its render job to actually finish before grabbing a snapshot of it, since QGIS renders asynchronously and grabbing too early can catch a stale or blank frame, most noticeably right after switching which viewport is armed.

## Google Maps vs Google Maps (JS)

**Google Maps** embeds the ordinary `maps.google.com` web page via a URL — no API key needed, but it's still Google's own web UI: search bar, sign-in prompt, "Heavy traffic in this area" popups, etc, none of which can be suppressed since it's just a normal page load.

**Google Maps (JS)** instead drives the [Google Maps JavaScript API](https://developers.google.com/maps/documentation/javascript) directly with `disableDefaultUI` and every individual control switched off, so the tile shows nothing but the map. This requires your own Google Maps JavaScript API key:

1.  Get a key from the [Google Cloud Console](https://console.cloud.google.com/google/maps-apis) (enable the "Maps JavaScript API").
2.  In QGIS: `Plugins` → `QuickMapCompare` → `Set Google Maps API Key…`, paste it in.
3.  Add a viewport with source "Google Maps (JS)" (or use the settings gear icon on an existing tile to switch its basemap/overlay style).

Note: because the key is used from an embedded QGIS webview rather than a real website, an **HTTP-referrer-restricted** key won't work here — use an unrestricted key (fine for personal/local use) or an **IP-restricted** key instead. The key is stored locally via `QSettings`, not committed anywhere.

## Basemap tile layers

OpenStreetMap, CyclOSM, Esri World Hillshade, Esri World Topographic, and USGS Topo are all free, public XYZ tile services that need no key — pick "Basemap tile layer" when adding a viewport. OpenStreetMap and CyclOSM are here (rather than as webview providers) specifically because their own demo websites pop up their own UI/modals on every page load, which would reappear on every sync since a sync is a page reload for a webview provider; the native tile layer sidesteps that entirely.

**Stamen Terrain** is the exception: Stamen's tiles are now hosted by Stadia Maps, and non-localhost use (which QGIS always is) needs either domain authentication or an API key. Get a free key from [Stadia Maps](https://stadiamaps.com/) and set it via `Plugins` → `QuickMapCompare` → `Set Stadia Maps API Key…`. Without a key, the tile will most likely fail to load — it's included because it was explicitly requested, but expect to need that key.

## Specialized and weather map providers

OpenSeaMap (nautical charts), OpenRailwayMap (rail infrastructure, with Standard/Max Speed/Signals/Electrification styles), OpenSnowMap (ski pistes), and Waymarked Trails (Hiking) are all free public OSM-family sites with no API key needed.

RainViewer (live radar) and Windy (wind/rain/temperature/clouds/pressure, via the gear icon) are both free, no-key embeddable weather maps.

Two weather sources were deliberately **not** added: OpenWeatherMap needs a paid/keyed tile endpoint, and NOAA Weather has no simple public tile or view endpoint to embed the same way the others do. Raw elevation datasets (Copernicus DEM, SRTM, ALOS AW3D30, FABDEM, NASADEM) were also left out — they're data, not interactive web maps, so they don't fit this plugin's "map provider" model; if you have one loaded as a QGIS layer already, use a QGIS-layer viewport for it instead.

## Why Bing Maps and Apple Maps aren't offered

QuickMapLink already restricts Bing Maps to browser-only opening (its GPU-heavy renderer is known to hard-crash QGIS in an embedded `QWebEngineView` on some systems/drivers) and Apple Maps is unreliable when embedded. QuickMapCompare can have several embedded web views open simultaneously — one per provider tile — which only multiplies that risk, so both providers are left out of the viewport source list entirely for this plugin, rather than offered with a warning.

## Installation

No public repository yet — install manually:

1.  Copy the `quick_map_compare` folder into your QGIS plugins directory:
    *   Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
    *   macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
    *   Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
2.  Restart QGIS, then go to `Plugins` → `Manage and Install Plugins...` → `Installed` and enable **QuickMapCompare**.

## Usage

1.  Click the **Add Viewport** icon in the toolbar (or `Plugins` menu). The first click creates the QuickMapCompare dock panel.
2.  Choose a source for the new tile: a layer from the current project, a built-in basemap tile layer, or one of the map providers.
3.  Toggle the **sync icon** (top-left of a tile) to have it live-follow the main QGIS canvas; toggle it off to freeze that tile's view.
4.  Use the **change-source icon** to swap what a tile shows, the **gear icon** (when shown) to change its basemap/overlay style, or the **✕** icon to remove it.
5.  Drag the divider between any two tiles to resize them.

## Requirements

*   QGIS 3.16+.
*   `QtWebEngine` (preferred) or `QtWebKit` for provider viewports. If neither is available in your QGIS build, provider tiles are disabled gracefully — layer and basemap-tile viewports still work.
*   A Google Maps JavaScript API key, only if you use the "Google Maps (JS)" provider (see above).
*   A Stadia Maps API key, only if you use the "Stamen Terrain" basemap tile layer (see above).

## Notes on Qt5/Qt6 compatibility

This plugin uses scoped Qt enums (e.g. `QDockWidget.DockWidgetFeature.DockWidgetClosable`, `Qt.DockWidgetArea.BottomDockWidgetArea`) and a defensive `QAction` import (`QtGui` first, `QtWidgets` fallback), so it's written to work on both PyQt5 (QGIS 3.x) and PyQt6 (QGIS 4.x). It does not use a compiled Qt resource module (`pyrcc5`-generated `resources.py`) for its icons — icons are loaded directly from disk.

## License

GPL v2+ — see [LICENSE](LICENSE).
