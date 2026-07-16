"""WebView setup shared by quick_map_compare.py (provider viewport tiles) and swipe.py
(the provider-viewport mirror used by Swipe Compare) -- kept in one place so both
import identical WEBVIEW_AVAILABLE/USING_WEBENGINE/WebView values rather than each
re-running the import probing independently (which also avoids a circular import
between quick_map_compare.py and swipe.py, since quick_map_compare.py imports
SwipeCompareDialog from swipe.py).
"""

import os

# Even with QWebEngineView (Chromium, out-of-process rendering), heavy WebGL/canvas
# sites can take the whole host app down if the bundled Chromium's GPU process hits a
# driver bug. Forcing software rendering trades a bit of smoothness for not crashing.
# These must be set before QtWebEngine spins up its first render process, so set them
# before importing it -- and QuickMapCompare can have several web views open at once
# (one per provider tile, plus the Swipe Compare mirror), which only raises the stakes
# relative to QuickMapLink's single embedded view.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                       "--disable-gpu --disable-gpu-compositing --disable-software-rasterizer")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

# Prefer QWebEngineView (Chromium, out-of-process renderer, what QGIS's own browser
# panel uses); fall back to the legacy QWebView (QtWebKit) on QGIS builds without
# QtWebEngine; and if neither is available at all (seen in practice on some QGIS 4
# builds missing PyQt6-WebEngine), degrade gracefully instead of crashing plugin load
# -- provider tiles (and the Swipe Compare provider mirror) just aren't offered.
WEBVIEW_AVAILABLE = True
USING_WEBENGINE = True
try:
    from qgis.PyQt.QtWebEngineWidgets import QWebEngineView as WebView
except ImportError:
    try:
        from qgis.PyQt.QtWebKitWidgets import QWebView as WebView
        USING_WEBENGINE = False
    except ImportError:
        WebView = None
        WEBVIEW_AVAILABLE = False
        USING_WEBENGINE = False
