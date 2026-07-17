import os
import math

from .webview_compat import WEBVIEW_AVAILABLE, USING_WEBENGINE, WebView

# QAction moved from QtWidgets to QtGui in Qt6/PyQt6 -- try the new location first,
# fall back to the old one, so this plugin loads on both QGIS 3 (Qt5) and QGIS 4 (Qt6).
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from qgis.PyQt.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QToolButton, QRadioButton, QButtonGroup, QDockWidget, QFrame,
    QSizePolicy, QMessageBox, QSplitter,
)
from qgis.PyQt.QtCore import Qt, QUrl, QTimer, QSize, QPoint
from qgis.PyQt.QtGui import QIcon, QPainter, QColor, QPen
from qgis.gui import QgsMapCanvas, QgisInterface
from qgis.core import QgsProject

from .sources import (
    PROVIDERS, PROVIDER_BASEMAPS, PROVIDER_OVERLAYS, TILE_BASEMAPS,
    _make_xyz_raster_layer, _provider_has_style_options,
    _basemap_styles, _basemap_has_style_options,
    get_wgs84_point, get_canvas_center_wgs84, estimate_zoom_level, _mercator_pixel,
    build_provider_url,
)
from .swipe import SwipeCanvasController

PLUGIN_DIR = os.path.dirname(__file__)
ICON_DIR = os.path.join(PLUGIN_DIR, "icons")

# Provider tiles are debounced as a group after the main canvas view settles, since
# each update means reloading a web page -- same ~400ms interval QuickMapLink uses
# for its single embedded webview.
PROVIDER_SYNC_DEBOUNCE_MS = 400

# A tile that's just been resized (splitter drag) gets its provider URL refreshed
# after this short debounce too, so the zoom estimate catches up to its new pixel
# width without reloading on every intermediate frame of the drag.
PROVIDER_RESIZE_DEBOUNCE_MS = 300


# ----------------------------------------------------------------------------
# Mouse-cursor crosshair overlay -- same look as QuickMapLink's _CursorOverlay,
# one instance per tile, parented directly onto that tile's body widget (the
# QgsMapCanvas or WebView) so its move()/show()/hide() coordinates are already
# relative to that widget.
# ----------------------------------------------------------------------------

class _CursorOverlay(QWidget):
    _SIZE = 18

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # clicks pass through
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self._SIZE // 2
        radius = 5

        pen = QPen(QColor(255, 0, 0, 230))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 0, 0, 60))
        painter.drawEllipse(QPoint(center, center), radius, radius)
        painter.drawLine(center - 8, center, center - radius - 1, center)
        painter.drawLine(center + radius + 1, center, center + 8, center)
        painter.drawLine(center, center - 8, center, center - radius - 1)
        painter.drawLine(center, center + radius + 1, center, center + 8)


# ----------------------------------------------------------------------------
# Source picker dialog
# ----------------------------------------------------------------------------

class SourcePickerDialog(QDialog):
    """Radio choice: QGIS Layer vs WMS/XYZ tiles vs Web Map Providers, with the
    relevant combo box below each. Used both for adding a new tile and for
    "Change source" on an existing one (pass current_source to preselect)."""

    def __init__(self, parent=None, current_source=None):
        super().__init__(parent)
        self.setWindowTitle("Choose Viewport Source")
        layout = QVBoxLayout(self)

        self.layer_radio = QRadioButton("QGIS layer")
        self.basemap_radio = QRadioButton("WMS/XYZ tiles")
        self.provider_radio = QRadioButton("Web Map Providers")
        button_group = QButtonGroup(self)
        button_group.addButton(self.layer_radio)
        button_group.addButton(self.basemap_radio)
        button_group.addButton(self.provider_radio)
        layout.addWidget(self.layer_radio)

        self.layer_combo = QComboBox()
        self._layer_ids = []
        for layer in QgsProject.instance().mapLayers().values():
            self._layer_ids.append(layer.id())
            self.layer_combo.addItem(layer.name())
        layout.addWidget(self.layer_combo)

        layout.addWidget(self.basemap_radio)
        self.basemap_combo = QComboBox()
        self.basemap_combo.addItems(list(TILE_BASEMAPS.keys()))
        layout.addWidget(self.basemap_combo)

        layout.addWidget(self.provider_radio)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(PROVIDERS)
        layout.addWidget(self.provider_combo)

        if not WEBVIEW_AVAILABLE:
            note = QLabel(
                "Web map providers aren't available in this QGIS build (no "
                "QtWebEngine/QtWebKit found) -- only QGIS layers and WMS/XYZ "
                "tiles can be used.")
            note.setWordWrap(True)
            layout.addWidget(note)
            self.provider_radio.setEnabled(False)
            self.provider_combo.setEnabled(False)

        if not self._layer_ids:
            self.layer_radio.setEnabled(False)
            self.layer_combo.setEnabled(False)

        # Preselect based on current_source (Change source), or a sensible default.
        if current_source and current_source[0] == "layer" and current_source[1] in self._layer_ids:
            self.layer_radio.setChecked(True)
            self.layer_combo.setCurrentIndex(self._layer_ids.index(current_source[1]))
        elif current_source and current_source[0] == "basemap" and current_source[1] in TILE_BASEMAPS:
            self.basemap_radio.setChecked(True)
            self.basemap_combo.setCurrentText(current_source[1])
        elif current_source and current_source[0] == "provider" and current_source[1] in PROVIDERS:
            self.provider_radio.setChecked(True)
            self.provider_combo.setCurrentText(current_source[1])
        elif self._layer_ids:
            self.layer_radio.setChecked(True)
        elif WEBVIEW_AVAILABLE:
            self.provider_radio.setChecked(True)
        else:
            self.basemap_radio.setChecked(True)

        button_row = QHBoxLayout()
        ok_button = QPushButton("OK")
        cancel_button = QPushButton("Cancel")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def result_source(self):
        """Returns ("layer", layer_id), ("basemap", name), or ("provider", provider_name); or None."""
        if self.layer_radio.isChecked():
            index = self.layer_combo.currentIndex()
            if index < 0 or index >= len(self._layer_ids):
                return None
            return ("layer", self._layer_ids[index])
        elif self.basemap_radio.isChecked():
            return ("basemap", self.basemap_combo.currentText())
        elif self.provider_radio.isChecked():
            return ("provider", self.provider_combo.currentText())
        return None


class ProviderStyleDialog(QDialog):
    """Opened from a provider tile's settings icon: basemap + overlay pickers,
    filtered to what that provider actually supports."""

    def __init__(self, parent, provider, current_basemap, current_overlay):
        super().__init__(parent)
        self.setWindowTitle(f"{provider} Style")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Base map style:"))
        self.basemap_combo = QComboBox()
        basemaps = PROVIDER_BASEMAPS.get(provider, ["Roadmap"])
        self.basemap_combo.addItems(basemaps)
        self.basemap_combo.setCurrentText(current_basemap if current_basemap in basemaps else basemaps[0])
        layout.addWidget(self.basemap_combo)

        layout.addWidget(QLabel("Overlay layer:"))
        self.overlay_combo = QComboBox()
        overlays = PROVIDER_OVERLAYS.get(provider, ["None"])
        self.overlay_combo.addItems(overlays)
        self.overlay_combo.setCurrentText(current_overlay if current_overlay in overlays else overlays[0])
        layout.addWidget(self.overlay_combo)

        button_row = QHBoxLayout()
        ok_button = QPushButton("OK")
        cancel_button = QPushButton("Cancel")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def result_style(self):
        return self.basemap_combo.currentText(), self.overlay_combo.currentText()


class BasemapStyleDialog(QDialog):
    """Opened from a WMS/XYZ tile's settings icon when it has more than one style
    (currently "Google Maps" and "CartoDB") -- a single style picker, simpler than
    ProviderStyleDialog since basemap tiles have no separate overlay concept."""

    def __init__(self, parent, basemap_name, current_style, styles):
        super().__init__(parent)
        self.setWindowTitle(f"{basemap_name} Style")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(styles)
        self.style_combo.setCurrentText(current_style if current_style in styles else styles[0])
        layout.addWidget(self.style_combo)

        button_row = QHBoxLayout()
        ok_button = QPushButton("OK")
        cancel_button = QPushButton("Cancel")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def result_style(self):
        return self.style_combo.currentText()


# ----------------------------------------------------------------------------
# Individual viewport tile
# ----------------------------------------------------------------------------

_OVERLAY_BAR_STYLE = """
    QWidget#overlayBar { background-color: rgba(20, 20, 20, 145); }
    QToolButton { background: transparent; border: none; padding: 3px; }
    QToolButton:hover { background-color: rgba(255, 255, 255, 60); border-radius: 4px; }
    QToolButton:checked { background-color: rgba(255, 176, 59, 190); border-radius: 4px; }
"""


class ViewportTileWidget(QFrame):
    """One tile in the comparison grid: a semi-transparent overlay bar floating
    over the top of the viewport content (Sync / Change source / Settings at the
    top-left, Close at the top-right), with the QgsMapCanvas or WebView filling
    the entire tile beneath it."""

    OVERLAY_HEIGHT = 30

    def __init__(self, iface, source, on_remove, on_changed, on_swipe_selected):
        super().__init__()
        self.iface = iface
        self.source = source  # ("layer", layer_id) or ("provider", provider_name)
        self._on_remove = on_remove
        self._on_changed = on_changed
        self._on_swipe_selected = on_swipe_selected
        self.sync_enabled = True
        self.basemap_style = None
        self.overlay_style = None
        self._swipe_mode = None  # None | "horizontal" | "vertical"

        self.setFrameShape(QFrame.Shape.Box)
        self.setMinimumSize(QSize(220, 180))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Body fills the entire tile; the overlay bar floats on top of it (not part
        # of this layout) and is repositioned manually in resizeEvent.
        self.body_container = QVBoxLayout(self)
        self.body_container.setContentsMargins(0, 0, 0, 0)
        self.body_container.setSpacing(0)

        self._build_overlay_bar()

        self.canvas = None
        self.webview = None
        self._body_widget = None
        self._cursor_overlay = None
        self._map_center = None  # (lat, lon) last used to build a provider tile's URL
        self._map_zoom = None    # zoom last used for that URL
        self._basemap_layer = None  # keeps the XYZ QgsRasterLayer alive for "basemap" tiles

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(PROVIDER_RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self.refresh_provider_url)

        self._build_body()

    # -- overlay bar -----------------------------------------------------

    def _icon_button(self, icon_name, tooltip, checkable=False):
        button = QToolButton(self.overlay_bar)
        icon_path = os.path.join(ICON_DIR, icon_name)
        if os.path.exists(icon_path):
            button.setIcon(QIcon(icon_path))
        else:
            button.setText(tooltip[:1])  # last-resort fallback if icons/ is missing
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(24, 24)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_overlay_bar(self):
        self.overlay_bar = QWidget(self)
        self.overlay_bar.setObjectName("overlayBar")
        self.overlay_bar.setStyleSheet(_OVERLAY_BAR_STYLE)

        bar_layout = QHBoxLayout(self.overlay_bar)
        bar_layout.setContentsMargins(4, 3, 4, 3)
        bar_layout.setSpacing(3)

        self.sync_button = self._icon_button("sync.png", "Sync with main canvas", checkable=True)
        self.sync_button.setChecked(True)
        self.sync_button.toggled.connect(self._on_sync_toggled)

        self.change_source_button = self._icon_button("change_source.png", "Change source")
        self.change_source_button.clicked.connect(self._change_source)

        self.settings_button = self._icon_button("settings.png", "Style settings")
        self.settings_button.clicked.connect(self._open_style_settings)
        self.settings_button.setVisible(False)

        self.swipe_button = self._icon_button("swipe.png", "Add to Swipe Compare", checkable=True)
        self.swipe_button.clicked.connect(self._on_swipe_clicked)
        self.swipe_button.setVisible(False)

        self.close_button = self._icon_button("close.png", "Remove viewport")
        self.close_button.clicked.connect(lambda: self._on_remove(self))

        bar_layout.addWidget(self.sync_button)
        bar_layout.addWidget(self.change_source_button)
        bar_layout.addWidget(self.settings_button)
        bar_layout.addWidget(self.swipe_button)
        bar_layout.addStretch()
        bar_layout.addWidget(self.close_button)

        self.overlay_bar.setGeometry(0, 0, self.width(), self.OVERLAY_HEIGHT)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay_bar.setGeometry(0, 0, self.width(), self.OVERLAY_HEIGHT)
        if self.source[0] == "provider" and self.webview is not None:
            # Debounced: a splitter drag fires many resize events in a row, and each
            # provider update reloads a web page, so only refresh once it settles.
            self._resize_timer.start()

    # -- body construction -------------------------------------------------

    def _clear_body(self):
        if self._body_widget is not None:
            self.body_container.removeWidget(self._body_widget)
            self._body_widget.setParent(None)
            self._body_widget.deleteLater()
            self._body_widget = None
        self.canvas = None
        self.webview = None
        self._cursor_overlay = None
        self._map_center = None
        self._map_zoom = None
        self._basemap_layer = None

    def _build_body(self):
        self._clear_body()
        kind, value = self.source
        if kind == "layer":
            self._build_layer_body(value)
        elif kind == "basemap":
            self._build_basemap_body(value)
        else:
            self._build_provider_body(value)
        self.overlay_bar.raise_()

    def _build_layer_body(self, layer_id):
        self.settings_button.setVisible(False)
        self.swipe_button.setVisible(True)

        layer = QgsProject.instance().mapLayer(layer_id)
        self.overlay_bar.setToolTip(layer.name() if layer else "(layer removed)")

        main_canvas = self.iface.mapCanvas()
        canvas = QgsMapCanvas()
        canvas.setCanvasColor(main_canvas.canvasColor())
        # Same rendering engine as the main canvas, so mirroring its extent/CRS
        # directly via setExtent() is instant/pixel-perfect -- no lat/lon/zoom
        # conversion needed, unlike the web-provider case.
        canvas.setDestinationCrs(main_canvas.mapSettings().destinationCrs())
        if layer is not None:
            canvas.setLayers([layer])
        canvas.setExtent(main_canvas.extent())
        canvas.refresh()

        self.canvas = canvas
        self._body_widget = canvas
        self.body_container.addWidget(canvas)
        self._cursor_overlay = _CursorOverlay(canvas)

    def _build_basemap_body(self, basemap_name):
        # Built-in XYZ tile basemap -- technically identical to a layer tile (same
        # QgsMapCanvas, same setExtent() sync), just backed by a raster layer we
        # construct on the fly instead of an existing project layer. A basemap with
        # more than one style (e.g. "Google Maps", "CartoDB") gets the settings-gear
        # icon too, same as a provider tile with style choices.
        self.settings_button.setVisible(_basemap_has_style_options(basemap_name))
        self.swipe_button.setVisible(True)
        self.overlay_bar.setToolTip(basemap_name)

        styles = _basemap_styles(basemap_name)
        self.basemap_style = styles[0] if styles else None

        main_canvas = self.iface.mapCanvas()
        canvas = QgsMapCanvas()
        canvas.setCanvasColor(main_canvas.canvasColor())
        canvas.setDestinationCrs(main_canvas.mapSettings().destinationCrs())

        layer = _make_xyz_raster_layer(basemap_name, self.basemap_style)
        self._basemap_layer = layer  # keep a live Python reference alongside the canvas
        if layer is not None and layer.isValid():
            canvas.setLayers([layer])
        canvas.setExtent(main_canvas.extent())
        canvas.refresh()

        self.canvas = canvas
        self._body_widget = canvas
        self.body_container.addWidget(canvas)
        self._cursor_overlay = _CursorOverlay(canvas)

    def _rebuild_basemap_layer(self):
        """Rebuild the XYZ raster layer in place with the currently-selected style --
        used when the user picks a different style (e.g. Google Maps Roadmap ->
        Satellite) from the settings dialog, without needing to remove and
        re-add the tile."""
        kind, name = self.source
        if kind != "basemap" or self.canvas is None:
            return
        try:
            layer = _make_xyz_raster_layer(name, self.basemap_style)
            self._basemap_layer = layer
            if layer is not None and layer.isValid():
                self.canvas.setLayers([layer])
                self.canvas.refresh()
        except RuntimeError:
            pass

    def _build_provider_body(self, provider):
        self.settings_button.setVisible(_provider_has_style_options(provider))
        self.swipe_button.setVisible(False)
        if self._swipe_mode is not None:
            # Web map providers can't be used as a swipe-compare target (see swipe.py)
            # -- un-arm it if it was armed before switching to this source, and notify
            # the dock/controller so nothing dangling is left picked.
            self._swipe_mode = None
            self._update_swipe_button_visual()
            self._on_swipe_selected(self, None)
        self.overlay_bar.setToolTip(provider)

        self.basemap_style = PROVIDER_BASEMAPS.get(provider, ["Roadmap"])[0]
        self.overlay_style = PROVIDER_OVERLAYS.get(provider, ["None"])[0]

        if not WEBVIEW_AVAILABLE:
            message = QLabel(
                "Web map providers aren't available in this QGIS build\n"
                "(no QtWebEngine/QtWebKit found).")
            message.setWordWrap(True)
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._body_widget = message
            self.body_container.addWidget(message)
            return

        webview = WebView()
        try:
            webview.loadFinished.connect(self._on_webview_load_finished)
        except AttributeError:
            pass
        self.webview = webview
        self._body_widget = webview
        self.body_container.addWidget(webview)
        self._cursor_overlay = _CursorOverlay(webview)
        self.refresh_provider_url()

    def _on_webview_load_finished(self, ok):
        # Leaflet-based providers (e.g. Wikimedia Maps) can mis-measure their
        # container on first paint even when the tile is already visible; nudging
        # a resize event after load makes them recompute and fill in tiles.
        if not ok or self.webview is None:
            return
        js = "window.dispatchEvent(new Event('resize'));"
        try:
            if USING_WEBENGINE:
                self.webview.page().runJavaScript(js)
            else:  # QWebView (QtWebKit) fallback
                self.webview.page().mainFrame().evaluateJavaScript(js)
        except RuntimeError:
            pass

    # -- sync ----------------------------------------------------------------

    def _on_sync_toggled(self, checked):
        self.sync_enabled = checked
        if checked:
            # Bring the tile in line with the main canvas immediately rather than
            # waiting for the next pan/zoom.
            self.sync_now()

    _SWIPE_MODE_CYCLE = (None, "horizontal", "vertical")

    def _on_swipe_clicked(self):
        # Cycles off -> horizontal -> vertical -> off on each click, rather than a
        # plain on/off toggle -- Qt still flips the button's own checked state
        # automatically on click since it's checkable (for the highlighted-when-armed
        # look), but _update_swipe_button_visual() overwrites that right after with
        # whatever our own three-state cycle actually landed on.
        index = self._SWIPE_MODE_CYCLE.index(self._swipe_mode)
        self._swipe_mode = self._SWIPE_MODE_CYCLE[(index + 1) % len(self._SWIPE_MODE_CYCLE)]
        self._update_swipe_button_visual()
        self._on_swipe_selected(self, self._swipe_mode)

    def _update_swipe_button_visual(self):
        self.swipe_button.setChecked(self._swipe_mode is not None)
        icon_name = "swipe_vertical.png" if self._swipe_mode == "vertical" else "swipe.png"
        icon_path = os.path.join(ICON_DIR, icon_name)
        if os.path.exists(icon_path):
            self.swipe_button.setIcon(QIcon(icon_path))
        suffix = {
            None: "",
            "horizontal": " (horizontal -- hold S and move the mouse over the main canvas)",
            "vertical": " (vertical -- hold S and move the mouse over the main canvas)",
        }[self._swipe_mode]
        self.swipe_button.setToolTip("Add to Swipe Compare" + suffix)

    def reset_swipe_mode(self):
        """Called by the dock to un-arm this tile when another one is armed instead --
        unlike _on_swipe_clicked, doesn't notify the dock back (it's already the one
        driving this), avoiding pointless re-entrant bookkeeping."""
        if self._swipe_mode is not None:
            self._swipe_mode = None
            self._update_swipe_button_visual()

    def sync_now(self):
        kind, _ = self.source
        if kind in ("layer", "basemap"):
            self.sync_layer_extent()
        else:
            self.refresh_provider_url()

    def sync_layer_extent(self):
        if self.canvas is None:
            return
        try:
            main_canvas = self.iface.mapCanvas()
            self.canvas.setDestinationCrs(main_canvas.mapSettings().destinationCrs())
            self.canvas.setExtent(main_canvas.extent())
            self.canvas.refresh()
        except RuntimeError:
            # Underlying C++ object already deleted (e.g. tile torn down mid-signal).
            pass

    def refresh_provider_url(self):
        if self.webview is None:
            return
        kind, provider = self.source
        if kind != "provider":
            return
        try:
            main_canvas = self.iface.mapCanvas()
            latitude, longitude = get_canvas_center_wgs84(main_canvas)
            tile_width = self.webview.width() or 400
            zoom = estimate_zoom_level(main_canvas, tile_width)

            url = build_provider_url(
                provider, self.basemap_style, self.overlay_style, latitude, longitude, zoom)
            self.webview.setUrl(QUrl(url))

            self._map_center = (latitude, longitude)
            self._map_zoom = round(max(0, min(21, zoom)))
        except RuntimeError:
            pass

    # -- settings / change source / removal -----------------------------------

    def _open_style_settings(self):
        kind, value = self.source
        if kind == "provider":
            dialog = ProviderStyleDialog(self, value, self.basemap_style, self.overlay_style)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.basemap_style, self.overlay_style = dialog.result_style()
                self.refresh_provider_url()
        elif kind == "basemap":
            styles = _basemap_styles(value)
            if len(styles) <= 1:
                return
            dialog = BasemapStyleDialog(self, value, self.basemap_style, styles)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.basemap_style = dialog.result_style()
                self._rebuild_basemap_layer()

    def _change_source(self):
        dialog = SourcePickerDialog(self, current_source=self.source)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result_source()
            if result is not None:
                self.source = result
                self._build_body()
                self.sync_now()
                self._on_changed()

    def handle_layer_removed(self, layer_id):
        """Called by the dock when a layer is removed from the project. If this
        tile was showing that layer, clear it rather than leaving a dangling
        reference (or crashing next time we touch it)."""
        if self.source == ("layer", layer_id):
            self.overlay_bar.setToolTip("(layer removed)")
            if self.canvas is not None:
                try:
                    self.canvas.setLayers([])
                    self.canvas.refresh()
                except RuntimeError:
                    pass

    # -- swipe compare -----------------------------------------------------

    def display_name(self):
        """Human-readable label for this tile -- used by the Swipe Compare viewport
        picker. Reuses the overlay bar's tooltip text, which is already kept in sync
        with the current source (layer name, basemap name, provider name, or
        "(layer removed)")."""
        return self.overlay_bar.toolTip() or "Viewport"

    # -- mouse-cursor overlay --------------------------------------------------

    def update_cursor_overlay(self, map_point):
        if self._cursor_overlay is None:
            return
        kind, _ = self.source
        if kind in ("layer", "basemap"):
            self._update_cursor_overlay_layer(map_point)
        else:
            self._update_cursor_overlay_provider(map_point)

    def _update_cursor_overlay_layer(self, map_point):
        if self.canvas is None:
            self._cursor_overlay.hide()
            return
        try:
            pixel_point = self.canvas.getCoordinateTransform().transform(map_point)
        except RuntimeError:
            self._cursor_overlay.hide()
            return
        self._position_cursor_overlay(pixel_point.x(), pixel_point.y(), self.canvas.width(), self.canvas.height())

    def _update_cursor_overlay_provider(self, map_point):
        if self.webview is None or self._map_center is None or self._map_zoom is None:
            self._cursor_overlay.hide()
            return
        project_crs = QgsProject.instance().crs()
        latitude, longitude = get_wgs84_point(map_point, project_crs)
        center_lat, center_lon = self._map_center
        zoom = self._map_zoom

        cx, cy = _mercator_pixel(center_lat, center_lon, zoom)
        px, py = _mercator_pixel(latitude, longitude, zoom)
        dx, dy = px - cx, py - cy
        half_w = self.webview.width() / 2
        half_h = self.webview.height() / 2
        self._position_cursor_overlay(half_w + dx, half_h + dy, self.webview.width(), self.webview.height())

    def _position_cursor_overlay(self, x, y, widget_w, widget_h):
        if x < 0 or y < 0 or x > widget_w or y > widget_h:
            # Cursor currently maps to a point off the visible tile area (or the
            # two views have drifted out of sync) -- hide rather than draw outside
            # the widget's own bounds.
            self._cursor_overlay.hide()
            return
        size = self._cursor_overlay.width()
        self._cursor_overlay.move(round(x - size / 2), round(y - size / 2))
        self._cursor_overlay.show()
        self._cursor_overlay.raise_()


# ----------------------------------------------------------------------------
# Dockable comparison panel
# ----------------------------------------------------------------------------

class CompareDockWidget(QDockWidget):
    def __init__(self, iface, swipe_controller, parent=None):
        super().__init__("QuickMapCompare", parent)
        self.setObjectName("QuickMapCompareDock")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        self.iface = iface
        self.swipe_controller = swipe_controller
        self.tiles = []
        self._root_splitter = None

        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self.setWidget(self._host)

        # Shared debounce for provider tiles: batches every sync-enabled provider
        # tile's reload into one pass, ~400ms after the main canvas view settles.
        self._provider_sync_timer = QTimer(self)
        self._provider_sync_timer.setSingleShot(True)
        self._provider_sync_timer.setInterval(PROVIDER_SYNC_DEBOUNCE_MS)
        self._provider_sync_timer.timeout.connect(self._sync_provider_tiles)

    # -- tile management -------------------------------------------------

    def add_tile(self, source):
        tile = ViewportTileWidget(
            self.iface, source, self.remove_tile, self._on_tile_changed, self._on_swipe_toggle)
        self.tiles.append(tile)
        self._rebuild_layout()
        return tile

    def remove_tile(self, tile):
        if tile in self.tiles:
            self.tiles.remove(tile)
        self.swipe_controller.clear_if_active(tile)
        tile.setParent(None)
        tile.deleteLater()
        self._rebuild_layout()

    def _on_tile_changed(self):
        pass  # placeholder hook for future bookkeeping (e.g. persisting layout)

    def _on_swipe_toggle(self, tile, mode):
        """Swipe compare has a single active target (and orientation) at a time --
        arming one tile's swipe icon un-arms whichever other tile had it armed."""
        if mode is not None:
            for other in self.tiles:
                if other is not tile:
                    other.reset_swipe_mode()
            self.swipe_controller.set_active(tile, mode)
        elif self.swipe_controller.active_tile() is tile:
            self.swipe_controller.set_active(None, None)

    def _rebuild_layout(self):
        # Tiles live inside a QSplitter(Vertical) of QSplitter(Horizontal) rows
        # rather than a plain QGridLayout, so the user can drag dividers to resize
        # individual viewports. Roughly-square arrangement: columns = ceil(sqrt(n))
        # -- 1->1x1, 2->1x2, 4->2x2, 5->2x3, etc. Rebuilding the splitter tree from
        # scratch on every add/remove is simplest; the tradeoff is that any custom
        # sizes the user dragged reset when the tile count changes.
        if self._root_splitter is not None:
            self._host_layout.removeWidget(self._root_splitter)
            self._root_splitter.setParent(None)
            self._root_splitter.deleteLater()
            self._root_splitter = None

        count = len(self.tiles)
        if count == 0:
            return

        columns = max(1, math.ceil(math.sqrt(count)))
        root = QSplitter(Qt.Orientation.Vertical)
        for row_start in range(0, count, columns):
            row_tiles = self.tiles[row_start:row_start + columns]
            row_splitter = QSplitter(Qt.Orientation.Horizontal)
            for tile in row_tiles:
                row_splitter.addWidget(tile)
            root.addWidget(row_splitter)

        self._root_splitter = root
        self._host_layout.addWidget(root)

    # -- sync dispatch -----------------------------------------------------

    def on_main_canvas_extents_changed(self):
        needs_provider_sync = False
        for tile in self.tiles:
            if not tile.sync_enabled:
                continue
            if tile.source[0] in ("layer", "basemap"):
                tile.sync_layer_extent()  # cheap local render, no debounce
            else:
                needs_provider_sync = True
        if needs_provider_sync:
            self._provider_sync_timer.start()  # (re)start the debounce window

    def _sync_provider_tiles(self):
        for tile in self.tiles:
            if tile.sync_enabled and tile.source[0] == "provider":
                tile.refresh_provider_url()

    def on_main_canvas_mouse_moved(self, map_point):
        for tile in self.tiles:
            tile.update_cursor_overlay(map_point)

    def on_layers_removed(self, layer_ids):
        for tile in self.tiles:
            for layer_id in layer_ids:
                tile.handle_layer_removed(layer_id)


# ----------------------------------------------------------------------------
# Plugin entry point
# ----------------------------------------------------------------------------

class QuickMapComparePlugin:
    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.dock = None
        self.toolbar = None
        self.swipe_controller = SwipeCanvasController(self.iface)

        icon_path = os.path.join(PLUGIN_DIR, "icon.png")
        self.add_viewport_action = QAction(QIcon(icon_path), "Add Viewport", self.iface.mainWindow())
        self.add_viewport_action.setToolTip("Add a viewport to the QuickMapCompare panel")
        self.add_viewport_action.triggered.connect(self.add_viewport)

    def initGui(self):
        # Directly into the Plugins menu (one clickable item), same pattern as
        # QuickMapLink, rather than wrapping it in its own submenu.
        self.iface.pluginMenu().addAction(self.add_viewport_action)

        self.toolbar = self.iface.addToolBar("QuickMapCompare")
        self.toolbar.setObjectName("QuickMapCompareToolbar")
        self.toolbar.addAction(self.add_viewport_action)

        self.iface.mapCanvas().extentsChanged.connect(self._on_canvas_extents_changed)
        self.iface.mapCanvas().xyCoordinates.connect(self._on_canvas_mouse_moved)
        QgsProject.instance().layersRemoved.connect(self._on_layers_removed)

        self.swipe_controller.attach()

    def unload(self):
        self.iface.pluginMenu().removeAction(self.add_viewport_action)

        self.swipe_controller.detach()

        try:
            self.iface.mapCanvas().extentsChanged.disconnect(self._on_canvas_extents_changed)
        except (TypeError, RuntimeError):
            pass
        try:
            self.iface.mapCanvas().xyCoordinates.disconnect(self._on_canvas_mouse_moved)
        except (TypeError, RuntimeError):
            pass
        try:
            QgsProject.instance().layersRemoved.disconnect(self._on_layers_removed)
        except (TypeError, RuntimeError):
            pass

        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock = None

        self.iface.removeToolBarIcon(self.add_viewport_action)
        if self.toolbar is not None:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None

    # -- actions -------------------------------------------------------------

    def add_viewport(self):
        dialog = SourcePickerDialog(self.iface.mainWindow())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        source = dialog.result_source()
        if source is None:
            QMessageBox.information(
                self.iface.mainWindow(), "QuickMapCompare",
                "No layer or provider available to add as a viewport.")
            return

        if self.dock is None:
            self.dock = CompareDockWidget(self.iface, self.swipe_controller, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)

        # Show the dock BEFORE building/loading the new tile's webview: Leaflet-based
        # providers (e.g. Wikimedia Maps, OpenSnowMap) measure their container size
        # at init, so a tile built while still hidden/zero-sized can load blank
        # until the next resize nudge. Showing first avoids relying on that fallback.
        self.dock.show()
        self.dock.raise_()
        self.dock.add_tile(source)

    def _on_canvas_extents_changed(self):
        if self.dock is not None:
            self.dock.on_main_canvas_extents_changed()

    def _on_canvas_mouse_moved(self, map_point):
        if self.dock is not None:
            self.dock.on_main_canvas_mouse_moved(map_point)

    def _on_layers_removed(self, layer_ids):
        if self.dock is not None:
            self.dock.on_layers_removed(layer_ids)


def classFactory(iface):
    return QuickMapComparePlugin(iface)
