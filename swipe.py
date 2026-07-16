"""Swipe Compare: a press-and-hold-S gesture, directly on the main QGIS canvas, that
swipes between the live canvas and one chosen viewport -- no separate window.

Clicking a viewport's "Add to Swipe Compare" icon in its overlay bar (ViewportTileWidget)
cycles it through three states: off -> horizontal -> vertical -> off. Only offered for
QGIS layer and basemap-tile viewports. Web map provider viewports (embedded via a
webview) are deliberately excluded: there's no reliable way to composite an external web
page's rendering onto the live QGIS canvas at interactive, press-and-drag speed the way
a QgsMapCanvas-based viewport allows, so rather than offer something flaky, the icon
simply isn't shown for those.

With a viewport armed, click on the main canvas to give it focus, then press and hold S
and move the mouse: in horizontal mode everything left of the cursor is replaced by the
armed viewport's own content at the same extent (a vertical divider, dragged
left/right); in vertical mode it's everything above the cursor instead (a horizontal
divider, dragged up/down). Release S to return to the normal view.

Architecture: SwipeCanvasController is installed as an event filter directly on
iface.mapCanvas() (that's what "on the canvas itself" means here, as opposed to the
grab-a-snapshot-into-a-separate-dialog approach this used to take). SwipeCanvasOverlay
is a transparent child widget parented onto that same canvas, so it composites for
free -- it only paints the picked viewport's content over the portion left of the
divider; the untouched portion simply shows the real canvas beneath it.

Note the split between iface.mapCanvas() itself and iface.mapCanvas().viewport():
QgsMapCanvas is a QGraphicsView, and like any QAbstractScrollArea, the widget that
actually *receives mouse events* is its internal viewport() child, not the QGraphicsView
object itself -- only keyboard focus and resize land on the outer widget. The overlay is
therefore parented onto the viewport (so its coordinate system exactly matches the
rendered map pixels, with no frame-width offset to worry about), and mouse events are
filtered on the viewport while key events are filtered on the canvas itself.
"""

from qgis.PyQt.QtCore import QObject, Qt, QEvent, QRect
from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.QtGui import QPainter, QColor, QPen, QCursor, QFontMetrics
from qgis.gui import QgsMapCanvas
from qgis.core import QgsProject

from .sources import _make_xyz_raster_layer

SWIPE_KEY = Qt.Key.Key_S

# Kinds of viewport that can be used as a swipe-compare target -- both are rendered
# via QgsMapCanvas (same engine as the main canvas itself), which is what makes
# pixel-aligned, interactive-speed compositing onto the live canvas possible at all.
SWIPEABLE_SOURCE_KINDS = ("layer", "basemap")


def _event_pos(event):
    """QMouseEvent.pos() is deprecated in Qt6/PyQt6 in favor of position() (a
    QPointF) -- support both so this works on Qt5 (QGIS 3.x) and Qt6 (QGIS 4.x)."""
    point = event.position() if hasattr(event, "position") else event.pos()
    return point.x(), point.y()


class SwipeCanvasOverlay(QWidget):
    """Transparent child of the main map canvas's viewport (see module docstring for
    why the viewport specifically). Paints only the picked viewport's content on one
    side of the current divider -- everywhere else is left untouched, so the real
    canvas underneath shows through with no special translucency handling needed
    (ordinary parent/child Qt widget compositing).

    Supports two orientations: "horizontal" (a vertical divider line, dragged
    left/right -- the picked viewport shows to the *left* of the cursor) and
    "vertical" (a horizontal divider line, dragged up/down -- the picked viewport
    shows *above* the cursor)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._pixmap = None
        self._orientation = "horizontal"
        self._divider_pos = 0
        self._label = ""
        self.hide()

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def set_orientation(self, orientation):
        self._orientation = orientation
        self.update()

    def set_divider_pos(self, pos):
        limit = self.width() if self._orientation == "horizontal" else self.height()
        self._divider_pos = max(0, min(limit, round(pos)))
        self.update()

    def set_label(self, label):
        self._label = label
        self.update()

    def paintEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull() or self._divider_pos <= 0:
            return
        painter = QPainter(self)
        horizontal = self._orientation == "horizontal"

        if horizontal:
            clip_rect = QRect(0, 0, self._divider_pos, self.height())
        else:
            clip_rect = QRect(0, 0, self.width(), self._divider_pos)

        # Draw the *whole* pixmap at its natural (0, 0) position rather than manually
        # slicing out a source rect -- self._pixmap came from QWidget.grab() on the
        # mirror canvas, which on a HiDPI/Retina screen returns a pixmap whose raw
        # pixel size is devicePixelRatio() times its logical size (e.g. 2x on a
        # standard Retina display). A source rect built from logical widths/heights
        # only samples a shrunk corner of that larger buffer -- showing up as a
        # zoomed-in crop of the real content. drawPixmap(point, pixmap) accounts for
        # devicePixelRatio() automatically, so this is the DPI-safe way to get an
        # undistorted 1:1 (logical-pixel) blit; clip to the divider instead of
        # cropping the source.
        painter.setClipRect(clip_rect)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.setClipping(False)

        pen = QPen(QColor(255, 255, 255, 235))
        pen.setWidth(2)
        painter.setPen(pen)
        if horizontal:
            painter.drawLine(self._divider_pos, 0, self._divider_pos, self.height())
        else:
            painter.drawLine(0, self._divider_pos, self.width(), self._divider_pos)

        if self._label:
            self._draw_label(painter, self._label)

    def _draw_label(self, painter, text):
        metrics = QFontMetrics(painter.font())
        pad_x, pad_y = 6, 4
        text_w = metrics.horizontalAdvance(text) if hasattr(metrics, "horizontalAdvance") else metrics.width(text)
        box_w, box_h = text_w + pad_x * 2, metrics.height() + pad_y * 2
        box = QRect(6, 6, box_w, box_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 175))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class SwipeCanvasController(QObject):
    """Installed as an event filter on the main map canvas for the plugin's whole
    lifetime (see QuickMapComparePlugin.initGui/unload). Tracks which viewport (if
    any) is picked for swipe comparison, and drives the press-S-and-drag gesture: key
    press renders a same-size/extent snapshot of the picked viewport once and shows
    the overlay; mouse move (while S is held) just moves the divider -- cheap, no
    re-render needed; key release hides the overlay again."""

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self._active_tile = None
        self._active_mode = None  # "horizontal" | "vertical", meaningful only alongside a tile
        self._overlay = None
        self._mirror_canvas = None
        self._swiping = False
        self._attached = False

    # -- setup / teardown -------------------------------------------------

    def attach(self):
        if self._attached:
            return
        canvas = self.iface.mapCanvas()
        viewport = canvas.viewport()
        canvas.installEventFilter(self)      # key events (focus lives on the canvas)
        viewport.installEventFilter(self)    # mouse events + resize (the actual rendered surface)

        self._overlay = SwipeCanvasOverlay(viewport)
        self._overlay.setGeometry(0, 0, viewport.width(), viewport.height())

        # Off-screen rendering surface used purely to produce matched-size/extent
        # snapshots of the picked viewport -- same "hidden mirror canvas" technique
        # used elsewhere in this plugin, kept well outside the visible canvas area so
        # it never receives real input (not that it would matter here, since only
        # grab() is ever called on it).
        self._mirror_canvas = QgsMapCanvas(canvas)
        self._mirror_canvas.setCanvasColor(canvas.canvasColor())
        self._mirror_canvas.setGeometry(-2000, -2000, 400, 300)
        self._mirror_canvas.show()

        self._attached = True

    def detach(self):
        if not self._attached:
            return
        canvas = self.iface.mapCanvas()
        viewport = canvas.viewport()
        try:
            canvas.removeEventFilter(self)
        except RuntimeError:
            pass
        try:
            viewport.removeEventFilter(self)
        except RuntimeError:
            pass
        if self._overlay is not None:
            self._overlay.setParent(None)
            self._overlay.deleteLater()
            self._overlay = None
        if self._mirror_canvas is not None:
            self._mirror_canvas.setParent(None)
            self._mirror_canvas.deleteLater()
            self._mirror_canvas = None
        self._active_tile = None
        self._active_mode = None
        self._swiping = False
        self._attached = False

    # -- active viewport ----------------------------------------------------

    def set_active(self, tile, mode):
        """mode is "horizontal", "vertical", or None (meaning no active target --
        tile should be None too in that case)."""
        if tile is self._active_tile and mode == self._active_mode:
            return
        if self._swiping:
            self._end_swipe()
        self._active_tile = tile
        self._active_mode = mode

    def active_tile(self):
        return self._active_tile

    def clear_if_active(self, tile):
        """Called when a tile is removed, or its source changes to something that
        can't be swiped (a web map provider) -- clears the active swipe target if it
        was this one, so nothing dangling is left picked."""
        if self._active_tile is tile:
            self.set_active(None, None)

    # -- event filter -----------------------------------------------------

    def eventFilter(self, watched, event):
        if self._overlay is None:
            return False
        canvas = self.iface.mapCanvas()
        viewport = canvas.viewport()
        event_type = event.type()

        if watched is viewport:
            if event_type == QEvent.Type.Resize:
                self._overlay.setGeometry(0, 0, viewport.width(), viewport.height())
                return False

            if self._swiping:
                # Fully own input for the duration of the gesture -- besides moving
                # the divider, this stops a stray click/scroll from panning or
                # zooming the main canvas out from under an active comparison.
                if event_type == QEvent.Type.MouseMove:
                    x, y = _event_pos(event)
                    self._overlay.set_divider_pos(x if self._active_mode == "horizontal" else y)
                    return True
                if event_type in (
                    QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                    QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel,
                ):
                    return True
            return False

        if watched is canvas:
            # Qt's QAbstractScrollArea machinery redirects the viewport's focus proxy
            # to the outer QGraphicsView, so clicking into the canvas gives *this*
            # object keyboard focus -- key events target it, not the viewport, unlike
            # mouse events (handled above).
            if event_type == QEvent.Type.KeyPress and not event.isAutoRepeat() and event.key() == SWIPE_KEY:
                if self._active_tile is None:
                    return False
                if not self._swiping:
                    self._start_swipe()
                return True

            if event_type == QEvent.Type.KeyRelease and not event.isAutoRepeat() and event.key() == SWIPE_KEY:
                if self._swiping:
                    self._end_swipe()
                    return True
                return False

        return False

    # -- swipe lifecycle -----------------------------------------------------

    def _start_swipe(self):
        tile = self._active_tile
        mode = self._active_mode
        if tile is None or mode is None:
            return
        canvas = self.iface.mapCanvas()
        viewport = canvas.viewport()
        pixmap = self._render_mirror(tile, canvas, viewport)
        if pixmap is None:
            return

        self._swiping = True
        self._overlay.setGeometry(0, 0, viewport.width(), viewport.height())
        self._overlay.set_orientation(mode)
        self._overlay.set_pixmap(pixmap)
        self._overlay.set_label(tile.display_name())
        cursor_pos = viewport.mapFromGlobal(QCursor.pos())
        self._overlay.set_divider_pos(cursor_pos.x() if mode == "horizontal" else cursor_pos.y())
        self._overlay.show()
        self._overlay.raise_()

    def _end_swipe(self):
        self._swiping = False
        if self._overlay is not None:
            self._overlay.hide()

    def _render_mirror(self, tile, main_canvas, viewport):
        kind, value = tile.source
        canvas = self._mirror_canvas
        if canvas is None or kind not in SWIPEABLE_SOURCE_KINDS:
            return None
        try:
            if kind == "layer":
                layer = QgsProject.instance().mapLayer(value)
                layers = [layer] if layer is not None else []
            else:  # "basemap"
                layer = _make_xyz_raster_layer(value)
                layers = [layer] if layer is not None and layer.isValid() else []

            # Sized to the *viewport*, not main_canvas itself -- see module docstring.
            # A widget-vs-viewport size mismatch (e.g. from a frame border) would
            # otherwise make setExtent() fit to a slightly different aspect ratio than
            # what's actually rendered on screen, throwing off pixel alignment.
            width, height = viewport.width(), viewport.height()
            canvas.resize(width, height)
            canvas.setDestinationCrs(main_canvas.mapSettings().destinationCrs())
            canvas.setLayers(layers)
            canvas.setExtent(main_canvas.extent())
            canvas.refresh()
            # QgsMapCanvas rendering happens in a background job kicked off by
            # refresh() -- grab()bing immediately after can catch it mid-render (or
            # not yet started at all), most noticeably right after switching which
            # tile is armed, where it shows whatever the *previous* render left behind
            # (a blank canvas the very first time, or a stale layer after that). This
            # blocks until that job actually finishes so grab() sees the real thing.
            canvas.waitWhileRendering()
            return canvas.grab()
        except RuntimeError:
            return None
