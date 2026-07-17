# QuickMapCompare QGIS Plugin

[![License: GPL v2+](https://img.shields.io/badge/License-GPL%20v2+-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)
![QGIS Version](https://img.shields.io/badge/QGIS-%3E%3D%203.16-brightgreen.svg)

Build a grid of side-by-side "viewports" in a single dockable panel to compare QGIS layers and web maps at once, with per-viewport live sync to the main map canvas.

This is a standalone plugin, independent from [QuickMapLink](https://github.com/Siddh75/quick_map_link) (which opens a single location in an external web map from the canvas right-click menu). QuickMapCompare reuses the same idea of web map providers, but for side-by-side comparison rather than a single "open this location" action. The two plugins share no code — provider URL-building, zoom estimation, and coordinate transforms are duplicated independently in each.

## Features

*   **A grid of viewports in one dockable panel:** click "Add Viewport" to append a new tile; tiles arrange themselves in a roughly square grid (1→1×1, 2→1×2, 4→2×2, 5→2×3, ...) that reflows automatically as tiles are added or removed.
*   **Resizable viewports:** tiles sit in nested splitters (a vertical splitter of horizontal rows), so you can drag the dividers between tiles to resize them, the same way you'd resize QGIS's own panels.
*   **Three kinds of viewport:**
    *   **QGIS layer:** rendered natively via QGIS's own `QgsMapCanvas` — the same embeddable widget QGIS's own "Panels > New Map View" uses.
    *   **WMS/XYZ tiles:** built-in XYZ tile basemaps rendered natively via `QgsMapCanvas`, not a webview — OpenStreetMap, CyclOSM, Esri World Hillshade, Esri World Topographic, USGS Topo, Esri Ocean, Esri NatGeo, Esri Light Gray, CartoDB (Light/Dark/Voyager), Google Maps (Roadmap/Satellite/Terrain/Hybrid), and Bing Maps (Aerial). No GPU/webview crash risk, no site chrome/popups, no API key, and sync is just as pixel-perfect as a QGIS layer.
    *   **Web Map Providers:** Google Maps, Wikimedia Maps, OpenRailwayMap, or OpenSnowMap, embedded via a webview.
*   **Floating overlay controls:** each tile has a semi-transparent bar over the top of its content (it doesn't take up separate space) — Sync, Change source, and (when relevant) Style settings icons at the top-left, Close at the top-right. Hover the bar to see what the tile is currently showing.
*   **Per-viewport Sync toggle:** when enabled, that viewport live-follows the main QGIS map canvas as you pan and zoom. When disabled, it stays static. Layer and WMS/XYZ-tile viewports sync instantly (same rendering engine, pixel-perfect `setExtent()`); provider viewports sync with a short debounce (~400ms) since each update reloads a web page.
*   **Per-tile style settings:** sources with more than one style show a settings (gear) icon opening a small dialog to switch between them — for Web Map Providers that's Google Maps (Roadmap/Satellite/Terrain + Traffic/Transit/Bicycling overlays) and OpenRailwayMap (Standard/Max Speed/Signals/Electrification); for WMS/XYZ tiles that's the native Google Maps entry (Roadmap/Satellite/Terrain/Hybrid) and CartoDB (Light/Dark/Voyager). Sources with only one style don't show a settings icon.
*   **Mouse-cursor crosshair:** every viewport shows a small crosshair tracking where the QGIS canvas mouse cursor currently falls — pixel-perfect for layer and WMS/XYZ-tile viewports (same rendering engine), computed via web-mercator math against each tile's last-set center/zoom for provider viewports (same technique QuickMapLink uses for its webview).
*   **Change source / remove:** each tile can swap what it's showing, or be removed entirely — the grid reflows to fill the gap.
*   **Swipe Compare:** layer and WMS/XYZ-tile viewports have an "Add to Swipe Compare" icon in their overlay bar, cycling off → horizontal → vertical → off on each click. With one armed, hold **S** and move the mouse over the main QGIS canvas to swipe between the live canvas and that viewport — composited directly onto the canvas itself, no separate window.

## Swipe Compare

Click the "Add to Swipe Compare" icon on a layer or WMS/XYZ-tile viewport's overlay bar to cycle it through three states: **off → horizontal → vertical → off** (arming one un-arms whichever other tile had it armed — there's only one active target at a time). Click on the main canvas so it has focus, then press and hold **S** and move the mouse:

*   **Horizontal mode** (a vertical divider, dragged left/right): everything to the left of the cursor is replaced by the armed viewport's content.
*   **Vertical mode** (a horizontal divider, dragged up/down): everything above the cursor is replaced instead.

Release S to go back to the normal canvas view.

Web Map Provider viewports (Google Maps, Wikimedia Maps, and the rest) don't offer the icon — there's no reliable way to composite an external web page's rendering onto the live QGIS canvas at interactive, press-and-drag speed the way a `QgsMapCanvas`-based viewport allows, so rather than offer something flaky, they're excluded from swipe entirely.

Under the hood, an event filter installed on `iface.mapCanvas()` handles the key press/release and mouse move, and a transparent child widget parented directly onto the canvas's viewport paints the armed viewport's content over the appropriate side of the divider — ordinary parent/child Qt compositing, so the untouched portion simply shows the real canvas through it with no special translucency setup needed. The armed viewport's content itself comes from a same-size, same-extent `QgsMapCanvas` "mirror" rendered once when S is first pressed (moving the mouse afterward just repositions the divider, no re-render needed) — the mirror waits for its render job to actually finish before grabbing a snapshot of it, since QGIS renders asynchronously and grabbing too early can catch a stale or blank frame, most noticeably right after switching which viewport is armed.

## WMS/XYZ tiles

All of these are free, public XYZ tile services that need no API key — pick "WMS/XYZ tiles" when adding a viewport:

*   **OpenStreetMap** and **CyclOSM** — rendered as native tiles (rather than as webview providers) specifically because their own demo websites pop up their own UI/modals on every page load, which would reappear on every sync since a sync is a page reload for a webview provider; the native tile layer sidesteps that entirely.
*   **Esri World Hillshade**, **Esri World Topographic**, **USGS Topo** — terrain/relief basemaps.
*   **Esri Ocean**, **Esri NatGeo**, **Esri Light Gray** — additional Esri ArcGIS Online basemaps (bathymetry/ocean, National Geographic style, and a muted light-gray reference base).
*   **CartoDB** — a single entry with three styles (**Light**, **Dark**, **Voyager**), switchable via the tile's settings-gear icon.
*   **Google Maps** — a single entry with four styles (**Roadmap**, **Satellite**, **Terrain**, **Hybrid**), switchable via the settings-gear icon. This is a native tile layer, independent of the webview "Google Maps" Web Map Provider below — no API key, no site chrome, pixel-perfect sync either way.
*   **Bing Maps (Aerial)** — Bing's aerial imagery tiles, addressed via Bing's own quadkey (`{q}`) tile scheme rather than the usual `{z}/{x}/{y}`, which QGIS's XYZ tile source supports natively.

## Web Map Providers

**Google Maps** embeds the ordinary `maps.google.com` web page via a URL — no API key needed, but it's still Google's own web UI: search bar, sign-in prompt, "Heavy traffic in this area" popups, etc, none of which can be suppressed since it's just a normal page load. (See [WMS/XYZ tiles](#wmsxyz-tiles) above for a chrome-free native alternative.)

**Wikimedia Maps**, **OpenRailwayMap** (rail infrastructure, with Standard/Max Speed/Signals/Electrification styles), and **OpenSnowMap** (ski pistes) are free public OSM-family sites with no API key needed.

Windy, RainViewer, Waymarked Trails (Hiking), OpenSeaMap, and OpenTopoMap were previously offered here but have been removed after proving unreliable. Two weather sources were also deliberately **not** added in the first place: OpenWeatherMap needs a paid/keyed tile endpoint, and NOAA Weather has no simple public tile or view endpoint to embed the same way the others do. Raw elevation datasets (Copernicus DEM, SRTM, ALOS AW3D30, FABDEM, NASADEM) were also left out — they're data, not interactive web maps, so they don't fit this plugin's "web map provider" model; if you have one loaded as a QGIS layer already, use a QGIS-layer viewport for it instead.

## Bing Maps and Apple Maps

QuickMapLink already restricts Bing Maps to browser-only opening (its GPU-heavy renderer is known to hard-crash QGIS in an embedded `QWebEngineView` on some systems/drivers), and QuickMapCompare can have several embedded web views open simultaneously — one per provider tile — which only multiplies that risk. So Bing is left out of the **Web Map Providers** (webview) list entirely, rather than offered with a warning. It's still available as a native **Bing Maps (Aerial)** entry under [WMS/XYZ tiles](#wmsxyz-tiles), since that route renders via `QgsMapCanvas` rather than an embedded browser and doesn't carry the same risk.

Apple Maps is unreliable when embedded and has no simple public tile endpoint to offer natively either, so it isn't offered at all.

## Installation

Not yet on the official QGIS plugin repository — install manually:

1.  Download this repository (clone it, or download the ZIP and unzip it) and copy the `quick_map_compare` folder into your QGIS plugins directory:
    *   Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
    *   macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
    *   Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
2.  Restart QGIS, then go to `Plugins` → `Manage and Install Plugins...` → `Installed` and enable **QuickMapCompare**.

## Usage

### 1. Add your first viewport

Click the **Add Viewport** icon (toolbar or `Plugins` → `QuickMapCompare` → `Add Viewport`). The first click also creates the QuickMapCompare dock panel, docked at the bottom of the QGIS window by default (drag its title bar to move or float it, like any QGIS panel).

A dialog asks what the tile should show — pick one of the three source kinds:

*   **QGIS layer** — any layer already in your current project.
*   **WMS/XYZ tiles** — a built-in XYZ basemap (OpenStreetMap, CyclOSM, Esri hillshade/topo, USGS Topo, Esri Ocean/NatGeo/Light Gray, CartoDB, Google Maps, Bing Maps Aerial). No API key needed (see [WMS/XYZ tiles](#wmsxyz-tiles)).
*   **Web Map Providers** — an embedded web map (Google Maps, Wikimedia Maps, OpenRailwayMap, OpenSnowMap). Only shown if your QGIS build has `QtWebEngine`/`QtWebKit`.

The new tile appears already synced to whatever the main QGIS canvas is currently showing.

### 2. Add more tiles to build a comparison grid

Repeat **Add Viewport** for each thing you want to compare side by side. Tiles arrange themselves automatically into a roughly square grid (1→1×1, 2→1×2, 4→2×2, 5→2×3, ...), reflowing every time you add or remove one. Drag the divider between any two tiles to resize them — sizes reset the next time the tile count changes.

### 3. The overlay bar on each tile

Hover any tile to see its floating control bar (it overlaps the content rather than taking up its own row). From left to right:

| Icon | Does what |
| --- | --- |
| **Sync** (toggle) | On: this tile live-follows the main canvas as you pan/zoom. Off: it freezes wherever it was. Layer/WMS-XYZ tiles update instantly; provider tiles update ~400ms after you stop moving, since each update reloads a web page. |
| **Change source** | Reopens the same source picker as Add Viewport, so you can swap this tile to a different layer, WMS/XYZ tile, or Web Map Provider without losing its place in the grid. |
| **Settings** (gear, only shown when relevant) | Tiles with more than one style — Google Maps and OpenRailwayMap among Web Map Providers, or Google Maps and CartoDB among WMS/XYZ tiles — get a small dialog to change that style. |
| **Add to Swipe Compare** (only shown for layer/WMS-XYZ tiles) | Arms this tile for the on-canvas swipe gesture — see [Swipe Compare](#swipe-compare) below. |
| **✕** | Removes the tile; the grid reflows to fill the gap. |

### 4. Compare against the main canvas directly (Swipe Compare)

For a layer or WMS/XYZ tile, click its **Add to Swipe Compare** icon (cycles off → horizontal → vertical → off), click on the main QGIS canvas so it has focus, then **press and hold S** and move the mouse — the main canvas is replaced by that tile's content on one side of the cursor, letting you drag a divider back and forth to compare. Release S to return to normal. Full details, including why provider tiles aren't offered here, in [Swipe Compare](#swipe-compare).

### A worked example

Comparing your own data against a basemap:

1.  **Add Viewport** → *QGIS layer* → pick your project layer (e.g. a parcels layer).
2.  **Add Viewport** again → *WMS/XYZ tiles* → *OpenStreetMap*. You now have a 1×2 grid, both tiles synced to the main canvas.
3.  Pan/zoom the main QGIS canvas — both tiles follow instantly.
4.  Click **Add to Swipe Compare** on the OpenStreetMap tile, click the main canvas, then hold **S** and move the mouse to reveal your parcels layer directly over the live canvas without needing the side-by-side tile at all.

## Requirements

*   QGIS 3.16+.
*   `QtWebEngine` (preferred) or `QtWebKit` for provider viewports. If neither is available in your QGIS build, provider tiles are disabled gracefully — layer and WMS/XYZ-tile viewports still work.

## Notes on Qt5/Qt6 compatibility

This plugin uses scoped Qt enums (e.g. `QDockWidget.DockWidgetFeature.DockWidgetClosable`, `Qt.DockWidgetArea.BottomDockWidgetArea`) and a defensive `QAction` import (`QtGui` first, `QtWidgets` fallback), so it's written to work on both PyQt5 (QGIS 3.x) and PyQt6 (QGIS 4.x). It does not use a compiled Qt resource module (`pyrcc5`-generated `resources.py`) for its icons — icons are loaded directly from disk.

## License

GPL v2+ — see [LICENSE](LICENSE).
