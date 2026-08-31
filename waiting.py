#!/usr/bin/env python3
"""
standalone_waiting_animation.py – Professional Waiting Overlay with Bouncing Balls
Displays an animated waiting screen on the second monitor (top‑left, 3712x512).
Features:
- 14 slices (matching the final video layout)
- Spinning gold rings with "Processing" / "Results" text on dark semi‑transparent backgrounds
- Slice numbers clearly shown above each ring
- 2–3 colorful bouncing balls per slice for a lively, busy look
- All elements perfectly centered using floating‑point arithmetic
Press Esc to close.
"""

import sys
import random
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont


class Ball:
    """A bouncing ball with position, velocity, radius, and color."""
    def __init__(self, x, y, vx, vy, radius, color):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.radius = radius
        self.color = color

    def update(self, bounds_x, bounds_y, width, height):
        """Move ball and bounce off walls."""
        self.x += self.vx
        self.y += self.vy

        # Bounce off left/right walls
        if self.x - self.radius < bounds_x:
            self.x = bounds_x + self.radius
            self.vx = -self.vx
        elif self.x + self.radius > bounds_x + width:
            self.x = bounds_x + width - self.radius
            self.vx = -self.vx

        # Bounce off top/bottom walls
        if self.y - self.radius < bounds_y:
            self.y = bounds_y + self.radius
            self.vy = -self.vy
        elif self.y + self.radius > bounds_y + height:
            self.y = bounds_y + height - self.radius
            self.vy = -self.vy


class WaitingOverlay(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMouseTracking(False)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

        # Animation timers
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_animation)
        self.timer.start(30)  # ~33 FPS

        # Slice layout
        self.slice_order = [12, 13, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        self.num_slices = len(self.slice_order)
        self.radius = 60  # ring radius

        # Offsets per tile index (for slice numbers 2 and 3)
        # index 4 -> slice number 2, offset +25px
        # index 5 -> slice number 3, offset +20px
        self.content_offset = {
            0: -5,   # tile 0 (slice 12) – shift left 10px
            1: -15,   # tile 1 (slice 13) – shift left 20px
            2: -20,   # tile 2 (slice 14) – shift left 25px
            4: 20,    # tile 4 (slice 2)  – shift right 25px
            5: 15,    # tile 5 (slice 3)  – shift right 20px
            6: 5,    # tile 6 (slice 4)  – shift right 10px
            7: -5,   # tile 7 (slice 5)  – shift left 10px
            8: -15,   # tile 8 (slice 6)  – shift left 20px
            9: -20,   # tile 9 (slice 7)  – shift left 25px
            11: 20,   # tile 11 (slice 9) – shift right 25px
            12: 15,   # tile 12 (slice 10) – shift right 20px
            13: 5    # tile 13 (slice 11) – shift right 10px
        }

        # Balls per slice – will be created on first paint
        self.balls_by_slice = None

    def _update_animation(self):
        """Update ring rotation and ball positions."""
        self.angle = (self.angle + 5) % 360

        # Update ball positions if balls exist
        if self.balls_by_slice is not None:
            w = self.width()
            h = self.height()
            if w <= 0 or h <= 0:
                return
            tile_width = w / self.num_slices
            padding = 12
            for i in range(self.num_slices):
                offset_x = self.content_offset.get(i, 0)
                x0 = int(i * tile_width) + padding + offset_x
                y0 = padding
                width = int(tile_width) - 2 * padding
                height = h - 2 * padding
                for ball in self.balls_by_slice[i]:
                    ball.update(x0, y0, width, height)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(10, 12, 18))

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        # Floating-point tile width for perfect centering
        tile_width = w / self.num_slices

        # Draw tile boundaries (semi-transparent grid)
        painter.setPen(QPen(QColor(80, 80, 100, 80), 1))
        for i in range(1, self.num_slices):
            x_line = int(i * tile_width)
            painter.drawLine(x_line, 0, x_line, h)

        # Initialize balls on first paint
        if self.balls_by_slice is None:
            self.balls_by_slice = []
            colors = [
                QColor(255, 50, 50), QColor(50, 255, 50), QColor(50, 150, 255),
                QColor(255, 200, 50), QColor(255, 50, 200), QColor(50, 255, 200),
                QColor(255, 150, 50), QColor(200, 50, 255), QColor(100, 255, 100),
                QColor(255, 100, 100)
            ]
            for i in range(self.num_slices):
                num_balls = random.randint(2, 3)
                slice_balls = []
                padding = 12
                offset_x = self.content_offset.get(i, 0)
                x0 = int(i * tile_width) + padding + offset_x
                y0 = padding
                width = int(tile_width) - 2 * padding
                height = h - 2 * padding
                for _ in range(num_balls):
                    radius_ball = random.randint(6, 14)
                    vx = random.uniform(1.0, 3.0) * random.choice([-1, 1])
                    vy = random.uniform(1.0, 3.0) * random.choice([-1, 1])
                    color = random.choice(colors)
                    x = random.randint(x0 + radius_ball, x0 + width - radius_ball)
                    y = random.randint(y0 + radius_ball, y0 + height - radius_ball)
                    ball = Ball(x, y, vx, vy, radius_ball, color)
                    slice_balls.append(ball)
                self.balls_by_slice.append(slice_balls)

        for i, slice_num in enumerate(self.slice_order):
            offset_x = self.content_offset.get(i, 0)

            # Exact center of this tile (shifted for tiles with offset)
            cx = int((i + 0.5) * tile_width) + offset_x
            cy = h // 2

            # ---- Slice number (centered above the ring) ----
            painter.setPen(QColor(0, 255, 255))
            font = QFont("Segoe UI", 18, QFont.Bold)
            painter.setFont(font)
            num_text = str(slice_num)
            metrics = painter.fontMetrics()
            tw = metrics.width(num_text)
            th = metrics.height()
            text_y = cy - self.radius - 25
            painter.drawText(cx - tw//2, text_y + th//2, num_text)

            # ---- Ring and arc ----
            radius = min(self.radius, int(tile_width // 2))
            if radius < 5:
                radius = 5

            # Background ring (dark)
            painter.setPen(QPen(QColor(60, 60, 80), int(radius * 0.25)))
            painter.drawEllipse(cx - radius, cy - radius, 2*radius, 2*radius)

            # Spinning arc (gold)
            painter.setPen(QPen(QColor(255, 193, 7), int(radius * 0.3)))
            painter.drawArc(
                cx - radius, cy - radius,
                2*radius, 2*radius,
                self.angle * 16, 270 * 16
            )

            # ---- "Processing" and "Results" text with background ----
            painter.setPen(QColor(255, 255, 255))
            font = QFont("Segoe UI", 12, QFont.Bold)  # slightly larger
            painter.setFont(font)

            text1 = "Processing"
            text2 = "Results"
            metrics = painter.fontMetrics()
            tw1 = metrics.width(text1)
            th1 = metrics.height()
            tw2 = metrics.width(text2)
            th2 = metrics.height()
            total_text_width = max(tw1, tw2) + 20  # padding
            total_text_height = th1 + th2 + 12     # spacing + padding
            x_text = cx - total_text_width // 2
            y_text = cy - total_text_height // 2

            # Draw rounded rectangle background (dark semi-transparent)
            painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x_text, y_text, total_text_width, total_text_height, 8, 8)

            # Draw text on top
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(cx - tw1//2, y_text + th1 + 4, text1)
            painter.drawText(cx - tw2//2, y_text + th1 + 8 + th2, text2)

            # ---- Bouncing balls inside this tile ----
            padding = 12
            # Balls are already updated with offset via _update_animation; just draw at current positions
            for ball in self.balls_by_slice[i]:
                # Draw ball
                painter.setBrush(QBrush(ball.color))
                painter.setPen(QPen(ball.color.darker(150), 1))
                painter.drawEllipse(int(ball.x - ball.radius),
                                    int(ball.y - ball.radius),
                                    int(2 * ball.radius),
                                    int(2 * ball.radius))

                # Highlight (3D effect)
                highlight_radius = int(ball.radius * 0.3)
                if highlight_radius > 1:
                    painter.setBrush(QBrush(QColor(255, 255, 255, 180)))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(int(ball.x - highlight_radius * 0.5),
                                        int(ball.y - highlight_radius * 0.5),
                                        int(highlight_radius),
                                        int(highlight_radius))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, screen_index=1):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        self.video_width = 3712
        self.video_height = 512
        self.setFixedSize(self.video_width, self.video_height)

        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        if screen_index < len(screens):
            screen = screens[screen_index]
            self.move(screen.geometry().topLeft())
        else:
            self.move(screens[0].geometry().topLeft())

        self.overlay = WaitingOverlay(self)
        self.setCentralWidget(self.overlay)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(screen_index=1)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()