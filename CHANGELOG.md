# Changelog

All notable changes to QuickMapCompare, from v0.7.0 through the first stable release, v1.0.0.

## 1.0.0

First stable release — no functional changes since 0.8.2.

*   Shortened the plugin description shown in the QGIS Plugin Manager.

## 0.8.2

*   **"Add Viewport" no longer forces the source picker when reopening an already-populated panel.** Closing the QuickMapCompare dock via its own titlebar close button just hides it — the panel and its viewports live on unchanged. Clicking "Add Viewport" now simply reopens the panel as it was in that case, instead of also prompting for (and adding) a new viewport. The source picker still opens as before the first time (no panel/viewports yet) or whenever the panel is already open.

## 0.8.1

*   **Fixed the native "Google Maps" WMS/XYZ tile not rendering.** Its tile URL contains literal `&` characters, which were corrupting the outer XYZ connection string QGIS builds internally — truncating the URL and losing the `{x}`/`{y}`/`{z}` tokens. The `&` is now percent-encoded before use.
*   **Fixed Swipe Compare getting stuck "on" indefinitely.** If S was pressed and released again quickly while the armed layer/basemap was still loading, the wait for that render to finish could outlast the key press — the release was processed (and silently dropped) before swipe had actually started, leaving it armed with no way to turn off except pressing S again. The physical key state is now tracked independently and checked before arming.
*   **Added a small "Loading…" indicator** over a tile while its content is being fetched — driven by QGIS's own render signals for layer/WMS-XYZ tiles, and by the page-load signals for Web Map Provider tiles.

## 0.8.0

*   **Removed** the Windy, RainViewer, Waymarked Trails (Hiking), OpenSeaMap, and OpenTopoMap web map providers — none could be verified working reliably.
*   **Renamed** the "Map provider" source kind to "Web Map Providers" and "Basemap tile layer" to "WMS/XYZ tiles" throughout the UI.
*   **Added a native "Google Maps" WMS/XYZ tile** (Roadmap/Satellite/Terrain/Hybrid, switchable via the settings-gear icon) — no API key, no webview chrome, independent of the existing webview "Google Maps" provider.
*   **Added** "CartoDB" (Light/Dark/Voyager), "Esri Ocean", "Esri NatGeo", "Esri Light Gray", and "Bing Maps (Aerial)" as new WMS/XYZ tile basemaps.
*   WMS/XYZ tiles with more than one style (Google Maps, CartoDB) now show a settings-gear icon to switch between them, same as multi-style web map providers already did.

## 0.7.1

*   **Removed** the "Google Maps (JS)" provider and the "Stamen Terrain" basemap tile layer (and their associated API key settings/menu actions), since neither could be tested locally. Plain "Google Maps" (no API key needed) and the other basemap/provider options are unaffected.

## 0.7.0

*   **Added a vertical Swipe Compare mode.** Clicking a viewport's "Add to Swipe Compare" icon now cycles off → horizontal (left/right, the original behavior) → vertical (top/bottom, a new draggable horizontal divider) → off, instead of a plain on/off toggle.
*   **Fixed Swipe Compare showing the previously-armed viewport** the first time S is pressed after switching to a different one — `QgsMapCanvas` renders asynchronously, so grabbing a snapshot immediately after `refresh()` could catch it before the new layer had finished rendering. Now waits for rendering to complete before grabbing.
