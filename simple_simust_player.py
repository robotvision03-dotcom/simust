"""
simple_simust_player.py - Video in top 512px only (new resolution: 3712x512)
Lower part shows desktop (transparent)
Video is full-width (3712px) and exactly 512px height at the very top.
Includes real-time speed control via GUI or file monitoring.
"""

import sys
import os
import signal
from PyQt5 import QtWidgets, QtCore, QtGui
import vlc
import time

# Hide console on Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


def kill_previous_simust_player_instances():
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid and 'simple_simust_player.py' in ' '.join(proc.info.get('cmdline', [])):
                    if sys.platform == "win32":
                        proc.terminate()
                    else:
                        os.kill(proc.info['pid'], signal.SIGTERM)
                    proc.wait(timeout=3)
            except:
                pass
    except:
        pass


class ScreenSelectionDialog(QtWidgets.QDialog):
    def __init__(self, screens, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Display for SIMUST PLAYER")
        self.setModal(True)
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Dialog)
        
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: white; min-width: 600px; }
            QLabel { color: white; font-size: 13px; padding: 5px; }
            QRadioButton { color: white; spacing: 8px; padding: 8px; font-size: 12px; }
            QRadioButton:hover { background-color: #3a3a3a; }
            QPushButton { background-color: #4caf50; color: white; border: none; padding: 10px 20px; border-radius: 5px; font-weight: bold; }
            QPushButton:hover { background-color: #45a049; }
            QPushButton#cancel { background-color: #f44336; }
            QPushButton#cancel:hover { background-color: #da190b; }
        """)
        
        layout = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("🎬 SIMUST PLAYER - Configuration")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)
        
        screen_group = QtWidgets.QGroupBox("Screen Selection")
        screen_layout = QtWidgets.QVBoxLayout()
        instruction = QtWidgets.QLabel("Select which screen to display the video on:")
        instruction.setAlignment(QtCore.Qt.AlignCenter)
        screen_layout.addWidget(instruction)
        screen_layout.addSpacing(10)
        
        self.button_group = QtWidgets.QButtonGroup(self)
        self.selected_index = 0
        
        for i, screen in enumerate(screens):
            size = screen.size()
            is_primary = " (Primary)" if i == 0 else ""
            text = f"Screen {i}: {screen.name()} - {size.width()}x{size.height()}{is_primary}"
            radio = QtWidgets.QRadioButton(text)
            if i == 0:
                radio.setChecked(True)
                self.selected_index = 0
            radio.toggled.connect(lambda checked, idx=i: self.set_selected(idx) if checked else None)
            self.button_group.addButton(radio, i)
            screen_layout.addWidget(radio)
        
        screen_group.setLayout(screen_layout)
        layout.addWidget(screen_group)
        
        loop_group = QtWidgets.QGroupBox("Playback Options")
        loop_layout = QtWidgets.QVBoxLayout()
        self.loop_checkbox = QtWidgets.QCheckBox("Loop video continuously")
        self.loop_checkbox.setChecked(True)
        loop_layout.addWidget(self.loop_checkbox)
        loop_group.setLayout(loop_layout)
        layout.addWidget(loop_group)
        
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QtWidgets.QPushButton("Launch Video")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        self.resize(600, 400)
    
    def set_selected(self, index):
        self.selected_index = index
    
    def get_selected_screen(self):
        return self.selected_index
    
    def get_loop_mode(self):
        return self.loop_checkbox.isChecked()


class PlayerWindow(QtWidgets.QMainWindow):
    def __init__(self, video_path, screen_index=0, loop=True, player_speed=1.0):
        super().__init__()
        self.video_path = video_path
        self.loop = loop
        self.player_speed = player_speed
        self.video_width = 3712
        self.video_height = 512
        
        # FIX: Use the same SIMUST_PLAYER_DIRECTORY as backend
        self.speed_file_path = "C:/Users/siama/Documents/simust_player/simust_speed.txt"
        
        # Initialize speed file with current speed
        try:
            os.makedirs(os.path.dirname(self.speed_file_path), exist_ok=True)
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
            print(f"Speed file created at: {self.speed_file_path}")
        except Exception as e:
            print(f"Error creating speed file: {e}")

        # VLC setup with more compatible arguments
        vlc_args = [
            '--quiet', 
            '--no-video-title-show', 
            '--intf', 'dummy',
            '--aspect-ratio', '3712:512',
            '--no-audio',  # Disable audio to improve performance
            '--network-caching=300',
            '--file-caching=300'
        ]
        self.instance = vlc.Instance(vlc_args)
        self.player = self.instance.media_player_new()

        # Main window setup - transparent below video
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")

        # Video frame - ONLY top 512px, full width 3712px
        self.videoframe = QtWidgets.QFrame(self)
        self.videoframe.setStyleSheet("background-color: black; border: none;")

        # Status overlay (on video area only)
        self.status = QtWidgets.QLabel("", self)
        self.status.setAlignment(QtCore.Qt.AlignCenter)
        self.status.setStyleSheet("background-color: rgba(0,0,0,180); color: white; font-size: 14px; padding: 8px; border-radius: 4px; font-weight: bold;")
        self.status.hide()

        self.status_timer = QtCore.QTimer(singleShot=True)
        self.status_timer.timeout.connect(self.status.hide)

        self.check_timer = QtCore.QTimer()
        self.check_timer.setInterval(500)
        self.check_timer.timeout.connect(self._check_video_position)

        # Speed monitoring timer
        self.speed_monitor_timer = QtCore.QTimer()
        self.speed_monitor_timer.setInterval(300)  # Check every 300ms for faster response
        self.speed_monitor_timer.timeout.connect(self._check_speed_changes)
        self.last_speed = player_speed
        self.last_check_time = time.time()

        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        # Position to selected screen
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        geo = screens[screen_index if 0 <= screen_index < len(screens) else 0].geometry()

        self.setGeometry(geo)
        self.move(geo.topLeft())
        self.showFullScreen()

        # Force video to top 512px
        for delay in [20, 60, 120, 250, 400, 600]:
            QtCore.QTimer.singleShot(delay, self._force_top_512)

        # Embed VLC
        if sys.platform.startswith('linux'):
            self.player.set_xwindow(self.videoframe.winId())
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self.videoframe.winId()))
        elif sys.platform == "darwin":
            self.player.set_nsobject(int(self.videoframe.winId()))

        self.media = self.instance.media_new(os.path.abspath(video_path))
        self.player.set_media(self.media)
        
        # Set playback speed with retry mechanism
        self._set_speed_with_retry(self.player_speed)
        
        self.player.play()

        self.check_timer.start()
        self.speed_monitor_timer.start()
        self.show_status(f"SIMUST PLAYER | Speed: {self.player_speed:.2f}x | ↑ ↓ arrows to adjust | R to reset", 4000)

    def _set_speed_with_retry(self, speed, retry_count=0):
        """Set VLC playback speed with retry mechanism"""
        try:
            # Clamp speed to VLC supported range (0.25 to 4.0)
            speed = max(0.25, min(4.0, speed))
            
            # Try to set rate
            self.player.set_rate(speed)
            
            # Give VLC a moment to apply the speed
            QtCore.QThread.msleep(50)
            
            # Verify the speed was set correctly
            actual_speed = self.player.get_rate()
            
            print(f"Speed request: {speed}x, Actual: {actual_speed:.2f}x")
            
            if abs(actual_speed - speed) > 0.05 and retry_count < 3:
                # If not set correctly, retry after a short delay
                QtCore.QTimer.singleShot(100, lambda: self._set_speed_with_retry(speed, retry_count + 1))
            else:
                self.player_speed = actual_speed
                print(f"✓ Speed set to: {actual_speed:.2f}x")
                
        except Exception as e:
            print(f"Error setting speed: {e}")
            if retry_count < 3:
                QtCore.QTimer.singleShot(100, lambda: self._set_speed_with_retry(speed, retry_count + 1))

    def _check_speed_changes(self):
        """Monitor the speed file for changes from GUI"""
        try:
            current_time = time.time()
            # Limit checking frequency to avoid excessive file I/O
            if current_time - self.last_check_time < 0.1:
                return
            
            if os.path.exists(self.speed_file_path):
                with open(self.speed_file_path, 'r') as f:
                    content = f.read().strip()
                    if content:
                        new_speed = float(content)
                        new_speed = max(0.25, min(4.0, new_speed))
                        
                        # Check if speed changed (with tolerance for floating point)
                        if abs(new_speed - self.last_speed) > 0.01:
                            print(f"⚡ Speed file changed: {self.last_speed:.2f} -> {new_speed:.2f}")
                            self.last_speed = new_speed
                            self.player_speed = new_speed
                            self._set_speed_with_retry(self.player_speed)
                            self.show_status(f"⚡ Speed changed to: {self.player_speed:.2f}x", 1500)
                self.last_check_time = current_time
        except Exception as e:
            print(f"Error checking speed file: {e}")

    def _force_top_512(self):
        """Force video strictly in top 512px only"""
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
        except:
            pass

    def show_status(self, message, timeout=2000):
        self.status.setText(message)
        self.status.adjustSize()
        self.status.move((self.video_width - self.status.width()) // 2, 20)
        self.status.show()
        self.status_timer.start(timeout)

    def _check_video_position(self):
        if not self.player or not self.loop:
            return
        try:
            state = self.player.get_state()
            if state == vlc.State.Ended:
                print("Video ended, restarting...")
                self._restart_video()
        except Exception as e:
            pass

    def _restart_video(self):
        try:
            self.player.stop()
            QtCore.QThread.msleep(100)
            self.media = self.instance.media_new(os.path.abspath(self.video_path))
            self.player.set_media(self.media)
            # Re-apply speed when restarting
            self._set_speed_with_retry(self.player_speed)
            self.player.play()
        except Exception as e:
            print(f"Error restarting video: {e}")

    def toggle_play(self):
        if self.player.is_playing():
            self.player.pause()
            self.show_status("⏸ Paused", 1000)
        else:
            self.player.play()
            self.show_status("▶ Playing", 1000)

    def stop(self):
        self.player.stop()
        self.show_status("⏹ Stopped", 1000)

    def toggle_loop(self):
        self.loop = not self.loop
        self.show_status(f"Loop: {'ON' if self.loop else 'OFF'}", 1500)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
            QtCore.QTimer.singleShot(100, self._force_top_512)
        self.show_status("Fullscreen toggled", 800)

    def increase_speed(self):
        """Increase playback speed by 0.25"""
        new_speed = min(4.0, self.player_speed + 0.25)
        self.player_speed = new_speed
        self.last_speed = new_speed
        self._set_speed_with_retry(self.player_speed)
        self.show_status(f"⚡ Speed: {self.player_speed:.2f}x", 1000)
        print(f"Speed increased to: {self.player_speed:.2f}x")
        
        # Save to speed file for GUI sync
        try:
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except Exception as e:
            print(f"Error saving speed: {e}")

    def decrease_speed(self):
        """Decrease playback speed by 0.25"""
        new_speed = max(0.25, self.player_speed - 0.25)
        self.player_speed = new_speed
        self.last_speed = new_speed
        self._set_speed_with_retry(self.player_speed)
        self.show_status(f"🐢 Speed: {self.player_speed:.2f}x", 1000)
        print(f"Speed decreased to: {self.player_speed:.2f}x")
        
        # Save to speed file for GUI sync
        try:
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except Exception as e:
            print(f"Error saving speed: {e}")

    def reset_speed(self):
        """Reset speed to 1.0x"""
        self.player_speed = 1.0
        self.last_speed = 1.0
        self._set_speed_with_retry(1.0)
        self.show_status(f"🔄 Speed reset to: 1.00x", 1000)
        print(f"Speed reset to: 1.00x")
        
        # Save to speed file for GUI sync
        try:
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except Exception as e:
            print(f"Error saving speed: {e}")

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Space:
            self.toggle_play()
        elif key == QtCore.Qt.Key_S:
            self.stop()
        elif key == QtCore.Qt.Key_L:
            self.toggle_loop()
        elif key == QtCore.Qt.Key_F:
            self.toggle_fullscreen()
        elif key == QtCore.Qt.Key_Up:
            self.increase_speed()
        elif key == QtCore.Qt.Key_Down:
            self.decrease_speed()
        elif key == QtCore.Qt.Key_R:
            self.reset_speed()
        elif key == QtCore.Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.check_timer.stop()
        self.speed_monitor_timer.stop()
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except:
            pass
        event.accept()


def main():
    if len(sys.argv) < 2:
        print("Usage: python simple_simust_player.py <video-file> [screen_index] [loop] [player_speed]")
        print("Example: python simple_simust_player.py video.mp4 0 true 1.2")
        print("         (1.2 = 1.2x speed, 2.0 = 2x speed, 0.5 = 0.5x speed)")
        print("\nKeyboard Controls:")
        print("  SPACE - Play/Pause")
        print("  S     - Stop")
        print("  L     - Toggle Loop")
        print("  F     - Toggle Fullscreen")
        print("  ↑     - Increase Speed (+0.25x)")
        print("  ↓     - Decrease Speed (-0.25x)")
        print("  R     - Reset Speed to 1.0x")
        print("  ESC   - Exit")
        print("\nSpeed range: 0.25x to 4.0x (supports decimals like 1.5, 2.3, etc.)")
        print("\nSpeed file location: C:/Users/siama/Documents/simust_player/simust_speed.txt")
        sys.exit(1)

    kill_previous_simust_player_instances()

    video = sys.argv[1]
    if not os.path.exists(video):
        print(f"Video not found: {video}")
        sys.exit(1)

    app = QtWidgets.QApplication(sys.argv)

    screen_index = None
    loop_mode = True
    player_speed = 1.0  # Default speed
    
    if len(sys.argv) >= 3:
        try:
            screen_index = int(sys.argv[2])
        except ValueError:
            loop_mode = sys.argv[2].lower() in ['true','1','yes','on']
    if len(sys.argv) >= 4:
        try:
            player_speed = float(sys.argv[3])
            # Clamp speed to valid range
            player_speed = max(0.25, min(4.0, player_speed))
        except ValueError:
            loop_mode = sys.argv[3].lower() in ['true','1','yes','on']
    if len(sys.argv) >= 5:
        try:
            player_speed = float(sys.argv[4])
            player_speed = max(0.25, min(4.0, player_speed))
        except ValueError:
            pass

    if screen_index is None:
        screens = app.screens()
        if len(screens) == 1:
            screen_index = 0
        else:
            dialog = ScreenSelectionDialog(screens)
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                screen_index = dialog.get_selected_screen()
                loop_mode = dialog.get_loop_mode()
            else:
                sys.exit(0)

    print(f"Starting SIMUST PLAYER with speed: {player_speed}x")
    print(f"Speed file will be monitored at: C:/Users/siama/Documents/simust_player/simust_speed.txt")
    player = PlayerWindow(video, screen_index=screen_index, loop=loop_mode, player_speed=player_speed)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()