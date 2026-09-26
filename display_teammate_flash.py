"""Flash teammate.png on arena Screen 2 slices.

Sequence (x5):
  screens 4 + 11  → 1.2s on
  black           → 0.5s off
  screens 3 + 10  → 1.2s on
  black           → 0.5s off

Placement matches coach / integrated video: fixed 3840×512 band at the
top-left of Screen 2 (same as smart_simust_player / waiting.py).
Escape closes early.
"""

from __future__ import annotations

import os
import sys

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from simust_display_layout import (
        screen_content_offset,
        screen_content_offset_y,
        COACH_BAND_WIDTH,
        COACH_BAND_HEIGHT,
        DISPLAY_SLICE_ORDER,
        slice_x_span,
        content_x_box,
    )
except ImportError:
    def screen_content_offset(screen_id):
        return {12: -6, 13: -17, 3: 8, 4: 6, 5: -6, 6: -17, 10: 19, 11: 7}.get(
            int(screen_id), 0
        )

    def screen_content_offset_y(screen_id):
        return 0

    COACH_BAND_WIDTH = 3840
    COACH_BAND_HEIGHT = 512
    DISPLAY_SLICE_ORDER = [12, 13, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    def slice_x_span(index, width=None, count=None):
        width = COACH_BAND_WIDTH if width is None else int(width)
        count = len(DISPLAY_SLICE_ORDER) if count is None else max(1, int(count))
        x0 = (int(index) * width) // count
        x1 = ((int(index) + 1) * width) // count
        return x0, max(x0 + 1, x1)

    def content_x_box(index, screen_id, width=None, count=None):
        width = COACH_BAND_WIDTH if width is None else int(width)
        count = len(DISPLAY_SLICE_ORDER) if count is None else max(1, int(count))
        x0, x1 = slice_x_span(index, width, count)
        rect_w = max(8, int((x1 - x0) * 0.92))
        center = (x0 + x1) // 2
        return center - rect_w // 2, center + rect_w // 2, rect_w

ROOT = os.path.dirname(os.path.abspath(__file__))
IMAGE_PATH = os.path.join(ROOT, "teamate.png")

# Same order as waiting / results strip
SLICE_ORDER = list(DISPLAY_SLICE_ORDER)

# Coach band on screen 2: 14 frames, 3840×512. Screens 1 and 8 are empty.
VIDEO_WIDTH = COACH_BAND_WIDTH
VIDEO_HEIGHT = COACH_BAND_HEIGHT

ON_MS = 1200
OFF_MS = 500
REPEAT = 5
DEFAULT_SCREEN_INDEX = 1  # lab arena wall (DISPLAY2)


def tile_index(screen_id: int) -> int:
    return SLICE_ORDER.index(int(screen_id))


class TeammateFlashWindow(QtWidgets.QWidget):
    def __init__(self, image_path: str, screen_index: int = DEFAULT_SCREEN_INDEX):
        super().__init__()
        self.screen_index = int(screen_index)
        self.active_screens = set()  # screen ids currently lit
        self.cycle = 0
        self.phase = 0  # 0=4+11, 1=off, 2=3+10, 3=off

        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")
        self.pixmap = QtGui.QPixmap(image_path)
        if self.pixmap.isNull():
            raise RuntimeError(f"Could not load image: {image_path}")

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Window
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("background-color: black;")
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setFixedSize(VIDEO_WIDTH, VIDEO_HEIGHT)

        self._position_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()

        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._advance)
        QtCore.QTimer.singleShot(100, self._start)

    def _position_on_screen(self):
        """Top-left of Screen 2 at 3840×512 — same as coach animation video."""
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        if not screens:
            return
        idx = self.screen_index if self.screen_index < len(screens) else 0
        geo = screens[idx].geometry()
        self.move(geo.topLeft())
        print(
            f"Screen {idx} origin ({geo.x()},{geo.y()}) — "
            f"canvas {VIDEO_WIDTH}x{VIDEO_HEIGHT} (coach video band) — "
            f"image {os.path.basename(IMAGE_PATH)}"
        )

    def _start(self):
        self.cycle = 0
        self.phase = 0
        self._apply_phase()

    def _apply_phase(self):
        if self.cycle >= REPEAT and self.phase == 0:
            print("Done — 5 cycles complete.")
            self.close()
            return

        if self.phase == 0:
            self.active_screens = {4, 11}
            delay = ON_MS
            print(f"Cycle {self.cycle + 1}/{REPEAT}: ON screens 4 & 11 ({ON_MS} ms)")
        elif self.phase == 1:
            self.active_screens = set()
            delay = OFF_MS
            print(f"Cycle {self.cycle + 1}/{REPEAT}: OFF ({OFF_MS} ms)")
        elif self.phase == 2:
            self.active_screens = {3, 10}
            delay = ON_MS
            print(f"Cycle {self.cycle + 1}/{REPEAT}: ON screens 3 & 10 ({ON_MS} ms)")
        else:
            self.active_screens = set()
            delay = OFF_MS
            print(f"Cycle {self.cycle + 1}/{REPEAT}: OFF ({OFF_MS} ms)")

        self.update()
        self.timer.start(delay)

    def _advance(self):
        self.phase += 1
        if self.phase > 3:
            self.phase = 0
            self.cycle += 1
        self._apply_phase()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))
        if not self.active_screens:
            painter.end()
            return

        n = len(SLICE_ORDER)
        for sid in self.active_screens:
            i = tile_index(sid)
            left, _right, rect_w = content_x_box(i, sid, VIDEO_WIDTH, n)
            dy = screen_content_offset_y(sid)
            placed = QtCore.QRect(left, 0, rect_w, VIDEO_HEIGHT)
            scaled = self.pixmap.scaled(
                rect_w,
                VIDEO_HEIGHT,
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation,
            )
            px = left + (rect_w - scaled.width()) // 2
            py = (VIDEO_HEIGHT - scaled.height()) // 2 + dy
            painter.setClipRect(placed)
            painter.drawPixmap(px, py, scaled)
            painter.setClipping(False)
        painter.end()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        event.accept()
        QtWidgets.QApplication.instance().quit()


def main():
    screen_index = DEFAULT_SCREEN_INDEX
    image_path = IMAGE_PATH
    args = sys.argv[1:]
    if args and args[0].lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
        image_path = args[0]
        args = args[1:]
    if args:
        screen_index = int(args[0])

    app = QtWidgets.QApplication(sys.argv)
    win = TeammateFlashWindow(image_path, screen_index=screen_index)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
