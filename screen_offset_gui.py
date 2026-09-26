#!/usr/bin/env python3
"""Calibrate one offset per installed screen.

Pick a screen, nudge it left, right, up, or down, then press Generate offsets.
A live RTSP camera sits in the control window: zoom and drag it to see that
cabinet. The wall window shows the same 14 frames the player uses on screen 2:
Field A on the left half, Field B on the right half, empty after 14 and after 7.

Run: python screen_offset_gui.py
Esc closes. Arrow keys nudge the selected screen. Mouse wheel zooms the camera.
"""

import os
import sys

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000",
)
import cv2
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen

from rtsp import RTSP_RIGHT

from simust_display_layout import (
    CHART_CENTER_Y,
    RING_RADIUS,
    COACH_BAND_WIDTH,
    COACH_BAND_HEIGHT,
    DISPLAY_SLICE_ORDER,
    EMPTY_DISPLAY_SLICES,
    CONTENT_WIDTH_RATIO,
    screen_content_offset,
    screen_content_offset_y,
)

SLICE_ORDER = list(DISPLAY_SLICE_ORDER)
# Same 14 frames as pass images and results. 1 and 8 are the empty places.
WALL_LAYOUT = list(DISPLAY_SLICE_ORDER)
EMPTY_FRAMES = set(EMPTY_DISPLAY_SLICES)
WALL_WIDTH = COACH_BAND_WIDTH
WALL_HEIGHT = COACH_BAND_HEIGHT
LAYOUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "simust_display_layout.py")
BEGIN = "# BEGIN GENERATED OFFSETS"
END = "# END GENERATED OFFSETS"
OFFSET_LIMIT = 200

# One camera is shown at a time. 192.168.2.13 is the last address (RTSP_RIGHT).
RTSP_LEFT = "rtsp://admin:majidAram2@192.168.2.1:554/Streaming/Channels/101/"
RTSP_CAMERA_8 = "rtsp://admin:majidAram2@192.168.2.8:554/Streaming/Channels/101/"
CAMERAS = [
    ("192.168.2.1", RTSP_LEFT),
    ("192.168.2.8", RTSP_CAMERA_8),
    ("192.168.2.13", RTSP_RIGHT),
]


def rtsp_url_for(text):
    """Accept a full rtsp:// URL or just an IP such as 192.168.2.13."""
    value = str(text or "").strip()
    if not value:
        return ""
    if "://" in value:
        return value
    if ":" in value:
        return f"rtsp://admin:majidAram2@{value}/Streaming/Channels/101/"
    return f"rtsp://admin:majidAram2@{value}:554/Streaming/Channels/101/"


class CameraReader(QtCore.QThread):
    """Reads one RTSP stream and keeps only the newest frame."""

    def __init__(self, url):
        super().__init__()
        self.url = url
        self._running = True
        self._lock = QtCore.QMutex()
        self.latest = None
        self.message = "Connecting..."

    def stop(self):
        self._running = False

    def take_frame(self):
        self._lock.lock()
        frame = self.latest
        self.latest = None
        message = self.message
        self._lock.unlock()
        return frame, message

    def _set_message(self, message):
        self._lock.lock()
        self.message = message
        self._lock.unlock()

    def _store(self, image):
        self._lock.lock()
        self.latest = image
        self.message = "Live"
        self._lock.unlock()

    def run(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            self._set_message("Cannot open camera")
            return
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        while self._running:
            ok, frame = cap.read()
            if not ok or frame is None:
                self._set_message("Reconnecting...")
                cap.release()
                if not self._running:
                    break
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb.shape
            image = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888).copy()
            self._store(image)
        cap.release()


class ViewState(QtCore.QObject):
    """Zoom and pan for the live camera only. Pan is in camera-view pixels."""

    changed = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.image = None
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.placeholder = "Connecting..."

    def set_image(self, image):
        self.image = image
        self.changed.emit()

    def set_placeholder(self, text):
        self.placeholder = text
        self.image = None
        self.changed.emit()

    def nudge(self, step_x, step_y):
        self.pan_x += float(step_x)
        self.pan_y += float(step_y)
        self.changed.emit()

    def set_zoom(self, zoom):
        self.zoom = max(0.2, min(8.0, float(zoom)))
        self.changed.emit()

    def zoom_by(self, factor):
        self.set_zoom(self.zoom * factor)


class CameraView(QtWidgets.QWidget):
    """Live RTSP picture. Drag to look around, wheel to zoom in on one cabinet."""

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self._drag = None
        self.view.changed.connect(self.update)
        self.setMinimumHeight(320)
        self.setFocusPolicy(Qt.WheelFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        image = self.view.image
        if image is None or image.isNull():
            painter.setPen(QColor(220, 220, 220))
            painter.setFont(QFont("Segoe UI", 14))
            painter.drawText(self.rect(), Qt.AlignCenter, self.view.placeholder)
            return
        fit = min(self.width() / float(image.width()), self.height() / float(image.height()))
        scale = fit * self.view.zoom
        draw_w = image.width() * scale
        draw_h = image.height() * scale
        draw_x = (self.width() - draw_w) / 2.0 + self.view.pan_x
        draw_y = (self.height() - draw_h) / 2.0 + self.view.pan_y
        painter.drawImage(QtCore.QRectF(draw_x, draw_y, draw_w, draw_h), image)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.view.zoom_by(1.15 ** steps)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.pos()

    def mouseMoveEvent(self, event):
        if self._drag is None or not (event.buttons() & Qt.LeftButton):
            return
        delta = event.pos() - self._drag
        self._drag = event.pos()
        self.view.nudge(delta.x(), delta.y())

    def mouseReleaseEvent(self, event):
        self._drag = None


# One color per screen so a rectangle that slides into the next frame is obvious.
FRAME_COLORS = {
    12: QColor(0, 188, 212),
    13: QColor(255, 152, 0),
    14: QColor(129, 199, 132),
    2: QColor(186, 104, 200),
    3: QColor(255, 112, 67),
    4: QColor(121, 134, 203),
    5: QColor(255, 214, 0),
    6: QColor(77, 182, 172),
    7: QColor(240, 98, 146),
    9: QColor(149, 117, 205),
    10: QColor(255, 167, 38),
    11: QColor(66, 165, 245),
}


class WallStrip(QtWidgets.QWidget):
    """Cabinets in wall order, with an empty block after 14 and after 7.

    Each real screen is a colored rectangle on one line. All rectangles stay off
    until that frame's number is clicked.
    """

    def __init__(self, model, slots=None, parent=None):
        super().__init__(parent)
        self.model = model
        self.slots = list(slots or WALL_LAYOUT)
        self.model.changed.connect(self.update)
        self.setMinimumHeight(140)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.width() <= 0 or self.height() <= 0:
            return
        for index in range(len(self.slots) - 1, -1, -1):
            sid = self.slots[index]
            if sid is None or sid in EMPTY_FRAMES:
                continue
            if self._frame_rect(index, sid).contains(event.pos()):
                self.model.select(sid)
                return
        index = self._slot_index(event.x())
        if index is None:
            return
        sid = self.slots[index]
        if sid is None or sid in EMPTY_FRAMES:
            return
        self.model.select(sid)

    def _slot_span(self, index):
        count = max(1, len(self.slots))
        x0 = (index * self.width()) // count
        x1 = ((index + 1) * self.width()) // count
        return x0, max(x0 + 1, x1)

    def _slot_index(self, x):
        count = len(self.slots)
        if count <= 0 or self.width() <= 0:
            return None
        index = min(count - 1, max(0, (int(x) * count) // self.width()))
        return index

    def _scale(self):
        if self.height() <= 0:
            return 1.0
        return min(1.0, self.height() / float(WALL_HEIGHT))

    def _frame_rect(self, index, sid):
        """Rectangle for one screen, centered on the same line as the others."""
        x0, x1 = self._slot_span(index)
        tile_w = x1 - x0
        scale = self._scale()
        dx = int(self.model.dx.get(sid, 0) * scale)
        dy = int(self.model.dy.get(sid, 0) * scale)
        rect_w = max(8, int(tile_w * CONTENT_WIDTH_RATIO))
        rect_h = max(18, int(self.height() * 0.72))
        cx = (x0 + x1) // 2 + dx
        cy = self.height() // 2 + dy
        return QtCore.QRect(cx - rect_w // 2, cy - rect_h // 2, rect_w, rect_h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(10, 12, 18))
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return
        scale = self._scale()
        for index, sid in enumerate(self.slots):
            if sid is None or sid in EMPTY_FRAMES or sid != self.model.selected:
                continue
            frame = self._frame_rect(index, sid)
            color = FRAME_COLORS.get(sid, QColor(0, 200, 255))
            fill = QColor(color)
            fill.setAlpha(180)
            painter.setPen(QPen(color, 4))
            painter.setBrush(fill)
            painter.drawRect(frame)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI", max(10, int(18 * scale)), QFont.Bold))
            painter.drawText(frame.adjusted(0, 0, 0, -frame.height() // 5), Qt.AlignCenter, str(sid))
            painter.setFont(QFont("Segoe UI", max(8, int(11 * scale))))
            offset_label = f"{self.model.dx.get(sid, 0):+d}, {self.model.dy.get(sid, 0):+d}"
            painter.drawText(
                frame.adjusted(2, 0, -2, -4),
                Qt.AlignHCenter | Qt.AlignBottom,
                offset_label,
            )


class OffsetModel(QtCore.QObject):
    changed = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.dx = {sid: screen_content_offset(sid) for sid in SLICE_ORDER if sid not in EMPTY_FRAMES}
        self.dy = {sid: screen_content_offset_y(sid) for sid in SLICE_ORDER if sid not in EMPTY_FRAMES}
        self.selected = None

    def select(self, screen_id):
        screen_id = int(screen_id)
        if screen_id in EMPTY_FRAMES:
            return
        self.selected = None if self.selected == screen_id else screen_id
        self.changed.emit()

    def nudge(self, step_x, step_y):
        sid = self.selected
        if sid is None:
            return
        self.dx[sid] = _clamp(self.dx[sid] + int(step_x))
        self.dy[sid] = _clamp(self.dy[sid] + int(step_y))
        self.changed.emit()


def _clamp(value):
    return max(-OFFSET_LIMIT, min(OFFSET_LIMIT, int(value)))


def format_offset_block(dx, dy):
    def body(values):
        lines = []
        for sid in SLICE_ORDER:
            if sid in EMPTY_FRAMES:
                continue
            value = int(values.get(sid, 0))
            if value:
                lines.append(f"    {sid}: {value},")
        inner = "\n".join(lines)
        if inner:
            return "{\n" + inner + "\n}"
        return "{\n}"

    return (
        f"{BEGIN}\n"
        f"SCREEN_CONTENT_OFFSET = {body(dx)}\n"
        f"SCREEN_CONTENT_OFFSET_Y = {body(dy)}\n"
        f"{END}"
    )


def format_readable(dx, dy):
    lines = ["screen   x     y"]
    for sid in SLICE_ORDER:
        if sid in EMPTY_FRAMES:
            continue
        lines.append(f"{sid:>6}  {int(dx.get(sid, 0)):+4d}  {int(dy.get(sid, 0)):+4d}")
    return "\n".join(lines)


def write_offsets(dx, dy):
    block = format_offset_block(dx, dy)
    with open(LAYOUT_PATH, "r", encoding="utf-8") as handle:
        text = handle.read()
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise RuntimeError("Offset markers are missing from simust_display_layout.py")
    end_line = text.find("\n", end)
    if end_line < 0:
        end_line = len(text)
    else:
        end_line += 1
    updated = text[:start] + block + "\n" + text[end_line:]
    with open(LAYOUT_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(updated)
    return block


class ControlWindow(QtWidgets.QWidget):
    def __init__(self, model, view):
        super().__init__()
        self.model = model
        self.view = view
        self.reader = None
        self._zoom_lock = False
        self.setWindowTitle("SIMUST screen offset calibrator")
        self.setMinimumWidth(720)

        self.camera_view = CameraView(view, parent=self)
        self.camera_picker = QtWidgets.QComboBox()
        for label, _url in CAMERAS:
            self.camera_picker.addItem(label)
        self.camera_picker.currentIndexChanged.connect(self._switch_camera)
        self.ip_edit = QtWidgets.QLineEdit()
        self.ip_edit.setPlaceholderText("Type any IP, for example 192.168.2.13")
        self.ip_edit.returnPressed.connect(self._connect_typed_camera)
        open_camera = QtWidgets.QPushButton("Open")
        open_camera.clicked.connect(self._connect_typed_camera)
        self.camera_status = QtWidgets.QLabel("Connecting...")
        camera_row = QtWidgets.QHBoxLayout()
        camera_row.addWidget(QtWidgets.QLabel("Camera"))
        camera_row.addWidget(self.camera_picker)
        camera_row.addWidget(QtWidgets.QLabel("IP"))
        camera_row.addWidget(self.ip_edit, 1)
        camera_row.addWidget(open_camera)
        camera_row.addWidget(self.camera_status)

        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self._pull_camera)
        self.camera_timer.start(40)
        self._switch_camera(0)

        self.screen_buttons = {}
        button_row = QtWidgets.QHBoxLayout()
        for sid in WALL_LAYOUT:
            if sid in EMPTY_FRAMES:
                empty = QtWidgets.QLabel("empty")
                empty.setAlignment(Qt.AlignCenter)
                empty.setStyleSheet("color: #888; background: #222; padding: 6px;")
                button_row.addWidget(empty)
                continue
            button = QtWidgets.QPushButton(str(sid))
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, screen_id=sid: self.model.select(screen_id))
            self.screen_buttons[sid] = button
            button_row.addWidget(button)

        self.status = QtWidgets.QLabel()
        self.status.setFont(QFont("Segoe UI", 14, QFont.Bold))

        self.step = QtWidgets.QSpinBox()
        self.step.setRange(1, 80)
        self.step.setValue(2)
        self.step.setSuffix(" px")

        left = QtWidgets.QPushButton("Left")
        right = QtWidgets.QPushButton("Right")
        up = QtWidgets.QPushButton("Up")
        down = QtWidgets.QPushButton("Down")
        left.clicked.connect(lambda: self._nudge_screen(-self.step.value(), 0))
        right.clicked.connect(lambda: self._nudge_screen(self.step.value(), 0))
        up.clicked.connect(lambda: self._nudge_screen(0, -self.step.value()))
        down.clicked.connect(lambda: self._nudge_screen(0, self.step.value()))
        for button in (left, right, up, down):
            button.setMinimumHeight(44)
            button.setMinimumWidth(90)

        self.zoom_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(20, 800)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self._zoom_from_slider)
        zoom_out = QtWidgets.QPushButton("Zoom −")
        zoom_in = QtWidgets.QPushButton("Zoom +")
        zoom_out.clicked.connect(lambda: self.view.zoom_by(1 / 1.25))
        zoom_in.clicked.connect(lambda: self.view.zoom_by(1.25))
        self.zoom_label = QtWidgets.QLabel("100%")

        moves = QtWidgets.QHBoxLayout()
        moves.addWidget(left)
        moves.addWidget(right)
        moves.addWidget(up)
        moves.addWidget(down)
        moves.addSpacing(16)
        moves.addWidget(QtWidgets.QLabel("Step"))
        moves.addWidget(self.step)
        moves.addStretch(1)

        zoom_row = QtWidgets.QHBoxLayout()
        zoom_row.addWidget(zoom_out)
        zoom_row.addWidget(self.zoom_slider, 1)
        zoom_row.addWidget(zoom_in)
        zoom_row.addWidget(self.zoom_label)

        generate = QtWidgets.QPushButton("Generate offsets")
        generate.setMinimumHeight(48)
        generate.setStyleSheet("font-weight: bold; font-size: 16px;")
        generate.clicked.connect(self._generate)

        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Consolas", 11))
        self.output.setPlainText(
            "Click a frame number to turn that rectangle on. Click it again to turn it off.\n"
            "Only that color is shown. If it enters the next frame, nudge it back.\n"
            "The camera is live RTSP. Drag it and use Zoom to look at one cabinet.\n"
            "Generate offsets writes every screen into simust_display_layout.py."
        )

        self.preview = WallStrip(model, parent=self)
        self.preview.setMinimumHeight(160)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.camera_view, 1)
        layout.addLayout(camera_row)
        layout.addWidget(QtWidgets.QLabel("Camera — drag to pan, wheel or slider to zoom"))
        layout.addLayout(moves)
        layout.addLayout(zoom_row)
        layout.addWidget(QtWidgets.QLabel("14 frames on screen 2, same 3840×512 as pass images and results. Empty after 14 and after 7."))
        layout.addWidget(self.preview)
        layout.addLayout(button_row)
        layout.addWidget(self.status)
        layout.addWidget(generate)
        layout.addWidget(self.output, 1)

        self.model.changed.connect(self._refresh)
        self.view.changed.connect(self._refresh)
        self.installEventFilter(self)
        for child in self.findChildren(QtWidgets.QWidget):
            child.installEventFilter(self)
        self._refresh()

    def _nudge_screen(self, step_x, step_y):
        self.model.nudge(step_x, step_y)

    def _zoom_from_slider(self, value):
        if self._zoom_lock:
            return
        self.view.set_zoom(value / 100.0)

    def _refresh(self):
        sid = self.model.selected
        if sid is None:
            self.status.setText(f"All rectangles off. Click a frame number.      camera zoom {self.view.zoom * 100:.0f}%")
        else:
            self.status.setText(
                f"Screen {sid}    x = {self.model.dx[sid]:+d}    y = {self.model.dy[sid]:+d}"
                f"      camera zoom {self.view.zoom * 100:.0f}%"
            )
        self._zoom_lock = True
        self.zoom_slider.setValue(int(round(self.view.zoom * 100)))
        self._zoom_lock = False
        self.zoom_label.setText(f"{self.view.zoom * 100:.0f}%")
        for screen_id, button in self.screen_buttons.items():
            button.setChecked(screen_id == sid)

    def _generate(self):
        try:
            block = write_offsets(self.model.dx, self.model.dy)
        except Exception as exc:
            self.output.setPlainText(f"Could not write offsets:\n{exc}")
            return
        text = (
            "Wrote simust_display_layout.py\n"
            "Restart the player (Stop, then Play) and app.py before the next results video.\n\n"
            + format_readable(self.model.dx, self.model.dy)
            + "\n\n"
            + block
        )
        self.output.setPlainText(text)
        QtWidgets.QApplication.clipboard().setText(text)

    def keyPressEvent(self, event):
        self._nudge_from_key(event)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress and self._nudge_from_key(event):
            return True
        return super().eventFilter(obj, event)

    def _nudge_from_key(self, event):
        step = self.step.value()
        key = event.key()
        if key == Qt.Key_Left:
            self._nudge_screen(-step, 0)
        elif key == Qt.Key_Right:
            self._nudge_screen(step, 0)
        elif key == Qt.Key_Up:
            self._nudge_screen(0, -step)
        elif key == Qt.Key_Down:
            self._nudge_screen(0, step)
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.view.zoom_by(1.25)
        elif key == Qt.Key_Minus:
            self.view.zoom_by(1 / 1.25)
        elif key == Qt.Key_Escape:
            QtWidgets.QApplication.instance().quit()
        else:
            return False
        return True

    def _open_url(self, url):
        self.stop_camera()
        self.camera_status.setText("Connecting...")
        self.view.set_placeholder("Connecting...")
        self.reader = CameraReader(url)
        self.reader.start()

    def _switch_camera(self, index):
        if index < 0 or index >= len(CAMERAS):
            return
        label, url = CAMERAS[index]
        self.ip_edit.setText(label)
        self._open_url(url)

    def _connect_typed_camera(self):
        url = rtsp_url_for(self.ip_edit.text())
        if not url:
            self.camera_status.setText("Enter an IP")
            return
        self._open_url(url)

    def _pull_camera(self):
        if self.reader is None:
            return
        frame, message = self.reader.take_frame()
        self.camera_status.setText(message)
        if frame is None:
            return
        self.view.set_image(frame)

    def stop_camera(self, wait=False):
        reader = self.reader
        self.reader = None
        if reader is None:
            return
        reader.stop()
        if wait:
            reader.wait(1500)

    def closeEvent(self, event):
        self.camera_timer.stop()
        self.stop_camera(wait=True)
        super().closeEvent(event)


class WallWindow(QtWidgets.QMainWindow):
    def __init__(self, model, view, screen_index=1):
        super().__init__()
        self.model = model
        self.view = view
        self.setWindowTitle("SIMUST offset wall")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(WALL_WIDTH, WALL_HEIGHT)
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        target = screens[screen_index] if screen_index < len(screens) else screens[0]
        self.move(target.geometry().topLeft())
        self.strip = WallStrip(model, slots=WALL_LAYOUT, parent=self)
        self.setCentralWidget(self.strip)

    def keyPressEvent(self, event):
        step = 20
        key = event.key()
        if key == Qt.Key_Left:
            self.model.nudge(-step, 0)
        elif key == Qt.Key_Right:
            self.model.nudge(step, 0)
        elif key == Qt.Key_Up:
            self.model.nudge(0, -step)
        elif key == Qt.Key_Down:
            self.model.nudge(0, step)
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.view.zoom_by(1.15)
        elif key == Qt.Key_Minus:
            self.view.zoom_by(1 / 1.15)
        elif key == Qt.Key_Escape:
            QtWidgets.QApplication.instance().quit()


def main():
    app = QtWidgets.QApplication(sys.argv)
    model = OffsetModel()
    view = ViewState()
    wall = WallWindow(model, view, screen_index=1)
    controls = ControlWindow(model, view)
    screens = app.screens()
    if screens:
        controls.move(screens[0].geometry().topLeft() + QtCore.QPoint(40, 40))
    app.aboutToQuit.connect(lambda: controls.stop_camera(wait=True))
    wall.show()
    controls.show()
    controls.raise_()
    controls.activateWindow()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
