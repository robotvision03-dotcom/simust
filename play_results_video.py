"""
play_results_video.py - Plays a results video fullscreen on Screen 2, identical to smart_simust_player.py
Usage:
  python play_results_video.py <video_path> [screen_index]
  python play_results_video.py --processing [screen_index]
"""

import sys
import os
from PyQt5 import QtWidgets, QtCore, QtGui

if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


class ProcessingCanvas(QtWidgets.QWidget):
    """Dark 3712x512 strip with rotating rings and 'Processing results'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.setFixedSize(3712, 512)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self):
        self.angle = (self.angle + 8) % 360
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(10, 12, 18))

        centers = [(620, 200), (1430, 200), (2280, 200), (3090, 200)]
        colors = [
            QtGui.QColor(255, 165, 0),
            QtGui.QColor(0, 215, 255),
            QtGui.QColor(255, 215, 0),
            QtGui.QColor(255, 165, 0),
        ]
        radius = 78
        thickness = 14
        span = 270 * 16
        for i, (cx, cy) in enumerate(centers):
            start = int(((-self.angle + i * 70) % 360) * 16)
            pen = QtGui.QPen(colors[i], thickness)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(cx - radius, cy - radius, radius * 2, radius * 2, start, span)
            inner = QtGui.QPen(QtGui.QColor(40, 48, 58), 3)
            painter.setPen(inner)
            painter.drawEllipse(QtCore.QPoint(cx, cy), radius - thickness, radius - thickness)

        painter.setPen(QtGui.QColor(255, 255, 255))
        font = QtGui.QFont("Segoe UI", 42, QtGui.QFont.Bold)
        painter.setFont(font)
        text = "Processing results"
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text)
        painter.drawText((self.width() - tw) // 2, 400, text)
        painter.end()


class ProcessingWaitWindow(QtWidgets.QMainWindow):
    def __init__(self, screen_index=1):
        super().__init__()
        self.screen_index = screen_index
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint
        )
        self.setStyleSheet("background-color: black;")
        self.canvas = ProcessingCanvas(self)
        self.setCentralWidget(self.canvas)
        self._position_on_screen()

    def _position_on_screen(self):
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        if screens and self.screen_index < len(screens):
            screen = screens[self.screen_index]
        else:
            screen = screens[0] if screens else None
        if screen:
            geometry = screen.geometry()
            self.setGeometry(geometry)
            self.move(geometry.topLeft())
        self.showFullScreen()
        self.canvas.move(0, 0)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class ResultsVideoWindow(QtWidgets.QMainWindow):
    def __init__(self, video_path, screen_index=1):
        super().__init__()
        import vlc
        self.video_path = video_path
        self.screen_index = screen_index
        self.video_width = 3712
        self.video_height = 512
        self.playlist_finished = False
        self._is_closing = False

        vlc_args = [
            '--quiet',
            '--no-video-title-show',
            '--intf', 'dummy',
            '--aspect-ratio', '3712:512',
            '--network-caching=300',
            '--file-caching=300',
            '--no-xlib'
        ]
        self.instance = vlc.Instance(vlc_args)
        self.player = self.instance.media_player_new()

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")

        self.videoframe = QtWidgets.QFrame(self)
        self.videoframe.setStyleSheet("background-color: black; border: none;")

        self._position_on_screen()

        if sys.platform.startswith('linux'):
            self.player.set_xwindow(self.videoframe.winId())
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self.videoframe.winId()))
        elif sys.platform == "darwin":
            self.player.set_nsobject(int(self.videoframe.winId()))

        self.media = self.instance.media_new(os.path.abspath(video_path))
        self.player.set_media(self.media)

        QtCore.QTimer.singleShot(20, self._force_top_512)
        self.player.play()

        self.check_timer = QtCore.QTimer()
        self.check_timer.setInterval(500)
        self.check_timer.timeout.connect(self._check_video_position)
        self.check_timer.start()

        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    def _position_on_screen(self):
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        if screens and self.screen_index < len(screens):
            screen = screens[self.screen_index]
            geometry = screen.geometry()
            self.setGeometry(geometry)
            self.move(geometry.topLeft())
            print(f"Positioned on Screen {self.screen_index}: {geometry.width()}x{geometry.height()}")
        else:
            screen = screens[0] if screens else None
            if screen:
                geometry = screen.geometry()
                self.setGeometry(geometry)
                self.move(geometry.topLeft())
        self.showFullScreen()

    def _force_top_512(self):
        if not self.videoframe:
            return
        self.videoframe.setGeometry(0, 0, self.video_width, self.video_height)
        self.videoframe.raise_()
        self.videoframe.repaint()
        self.repaint()
        try:
            self.player.video_set_aspect_ratio("3712:512")
            self.player.video_set_scale(1.0)
            self.player.video_set_crop_geometry("0:0:3712:512")
        except Exception as e:
            print(f"VLC settings error: {e}")

    def _check_video_position(self):
        import vlc
        if self._is_closing or self.playlist_finished:
            return
        try:
            state = self.player.get_state()
            if state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
                self.playlist_finished = True
                self.check_timer.stop()
                QtCore.QTimer.singleShot(2000, self.close)
        except Exception as e:
            print(f"Error checking video state: {e}")

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._is_closing:
            event.accept()
            return
        self._is_closing = True
        self.check_timer.stop()
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        event.accept()


def _configure_qt():
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, False)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, False)
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    args = [a for a in sys.argv[1:] if a]
    processing = False
    video_path = None
    screen_index = 1
    if args and args[0] in ("--processing", "--wait", "-p"):
        processing = True
        if len(args) >= 2:
            try:
                screen_index = int(args[1])
            except ValueError:
                pass
    else:
        if len(args) < 1:
            print("Usage: python play_results_video.py <video_path> [screen_index]")
            print("       python play_results_video.py --processing [screen_index]")
            sys.exit(1)
        video_path = args[0]
        if not os.path.exists(video_path):
            print(f"Video not found: {video_path}")
            sys.exit(1)
        if len(args) >= 2:
            try:
                screen_index = int(args[1])
            except ValueError:
                pass

    _configure_qt()
    app = QtWidgets.QApplication(sys.argv)
    if processing:
        window = ProcessingWaitWindow(screen_index)
        window.show()
    else:
        window = ResultsVideoWindow(video_path, screen_index)
        window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
