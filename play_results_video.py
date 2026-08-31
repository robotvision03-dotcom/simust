"""
play_results_video.py - Plays a results video fullscreen on Screen 2, identical to smart_simust_player.py
Usage: python play_results_video.py <video_path> [screen_index]
Example: python play_results_video.py C:/path/to/results_video.mp4 1
"""

import sys
import os
import time
import vlc
from PyQt5 import QtWidgets, QtCore, QtGui

# Hide console on Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

        
class ResultsVideoWindow(QtWidgets.QMainWindow):
    def __init__(self, video_path, screen_index=1):
        super().__init__()
        self.video_path = video_path
        self.screen_index = screen_index
        self.video_width = 3712
        self.video_height = 512
        self.playlist_finished = False
        self._is_closing = False

        # VLC setup – WITHOUT --no-audio to allow sound
        vlc_args = [
            '--quiet',
            '--no-video-title-show',
            '--intf', 'dummy',
            '--aspect-ratio', '3712:512',
            # '--no-audio',   # <-- REMOVED to allow audio
            '--network-caching=300',
            '--file-caching=300',
            '--no-xlib'
        ]
        self.instance = vlc.Instance(vlc_args)
        self.player = self.instance.media_player_new()

        # Window setup – frameless, stays on top, transparent background
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")

        # Video frame – exactly at the top of the screen
        self.videoframe = QtWidgets.QFrame(self)
        self.videoframe.setStyleSheet("background-color: black; border: none;")

        # Position to the correct screen and go fullscreen
        self._position_on_screen()

        # Embed VLC
        if sys.platform.startswith('linux'):
            self.player.set_xwindow(self.videoframe.winId())
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self.videoframe.winId()))
        elif sys.platform == "darwin":
            self.player.set_nsobject(int(self.videoframe.winId()))

        # Load and play the video
        self.media = self.instance.media_new(os.path.abspath(video_path))
        self.player.set_media(self.media)

        # Force video to top 512px and full width
        QtCore.QTimer.singleShot(20, self._force_top_512)

        # Start playback
        self.player.play()

        # Timer to check for video end
        self.check_timer = QtCore.QTimer()
        self.check_timer.setInterval(500)
        self.check_timer.timeout.connect(self._check_video_position)
        self.check_timer.start()

        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    def _position_on_screen(self):
        """Position the window fullscreen on the specified screen"""
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        if screens and self.screen_index < len(screens):
            screen = screens[self.screen_index]
            geometry = screen.geometry()
            self.setGeometry(geometry)
            self.move(geometry.topLeft())
            print(f"📺 Positioned on Screen {self.screen_index}: {geometry.width()}x{geometry.height()}")
        else:
            # fallback to primary
            screen = screens[0] if screens else None
            if screen:
                geometry = screen.geometry()
                self.setGeometry(geometry)
                self.move(geometry.topLeft())
        self.showFullScreen()

    def _force_top_512(self):
        """Force the video frame to exactly 3712x512 at the top-left"""
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
        """Check if the video ended and close the window"""
        if self._is_closing or self.playlist_finished:
            return
        try:
            state = self.player.get_state()
            if state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
                self.playlist_finished = True
                self.check_timer.stop()
                # Auto-close after a short delay
                QtCore.QTimer.singleShot(2000, self.close)
        except Exception as e:
            print(f"Error checking video state: {e}")

    def keyPressEvent(self, event):
        """Allow ESC to close"""
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Clean up resources"""
        if self._is_closing:
            event.accept()
            return
        self._is_closing = True
        self.check_timer.stop()
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except:
            pass
        event.accept()


def main():
    if len(sys.argv) < 2:
        print("Usage: python play_results_video.py <video_path> [screen_index]")
        print("Example: python play_results_video.py C:/path/to/results_video.mp4 1")
        sys.exit(1)

    video_path = sys.argv[1]
    if not os.path.exists(video_path):
        print(f"Video not found: {video_path}")
        sys.exit(1)

    screen_index = 1  # default to Screen 2
    if len(sys.argv) >= 3:
        try:
            screen_index = int(sys.argv[2])
        except:
            pass

    # Disable DPI scaling to ensure pixel-perfect sizing
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass

    app = QtWidgets.QApplication(sys.argv)
    app.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, False)
    app.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, False)

    window = ResultsVideoWindow(video_path, screen_index)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()