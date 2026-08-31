#!/usr/bin/env python3
"""
RTSP Viewer with Capture
Displays a real‑time RTSP stream and allows you to save a high‑resolution frame.
Usage: python rtsp_viewer.py
Requirements: PyQt5, opencv-python, numpy
Install: pip install PyQt5 opencv-python numpy
"""

import sys
import os
import cv2
import numpy as np
from datetime import datetime
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap


# ================== RTSP URL ==================
RTSP_RIGHT = "rtsp://admin:majidAram2@192.168.2.12:554/Streaming/Channels/101/"


class RTSPViewer(QtWidgets.QWidget):
    def __init__(self, rtsp_url):
        super().__init__()
        self.rtsp_url = rtsp_url
        self.cap = None
        self.current_frame = None
        self.is_streaming = False

        # UI setup
        self.setWindowTitle("RTSP Viewer")
        self.setGeometry(100, 100, 800, 600)

        # Main layout
        layout = QtWidgets.QVBoxLayout()

        # Video display label
        self.video_label = QtWidgets.QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        self.video_label.setMinimumSize(640, 480)
        layout.addWidget(self.video_label)

        # Control buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.capture_btn = QtWidgets.QPushButton("Capture High‑Res Image")
        self.capture_btn.clicked.connect(self.capture_frame)
        self.capture_btn.setEnabled(False)
        btn_layout.addStretch()
        btn_layout.addWidget(self.capture_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

        # Timer to update the video feed (30 fps)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)  # ~30 Hz

        # Start the stream
        self.start_stream()

    def start_stream(self):
        """Open the RTSP stream."""
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            self.show_error("Failed to open RTSP stream.\nCheck the URL and network.")
            return
        self.is_streaming = True
        self.capture_btn.setEnabled(True)

    def update_frame(self):
        """Grab the latest frame from the stream and display it."""
        if not self.is_streaming or self.cap is None:
            return

        ret, frame = self.cap.read()
        if not ret:
            # If we lose connection, try to reconnect
            self.is_streaming = False
            self.capture_btn.setEnabled(False)
            self.show_error("Stream lost. Attempting to reconnect...")
            self.start_stream()
            return

        # Store the full‑resolution frame for capture
        self.current_frame = frame.copy()

        # Resize frame to fit the label while preserving aspect ratio
        label_width = self.video_label.width()
        label_height = self.video_label.height()
        if label_width > 0 and label_height > 0:
            h, w = frame.shape[:2]
            scale = min(label_width / w, label_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            display_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            display_frame = frame

        # Convert to QImage and display
        rgb_image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(qt_image))

    def capture_frame(self):
        """Save the current high‑resolution frame."""
        if self.current_frame is None:
            self.show_error("No frame available to capture.")
            return

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{timestamp}.jpg"

        # Save in the same directory as the script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(script_dir, filename)

        success = cv2.imwrite(filepath, self.current_frame)
        if success:
            self.show_info(f"Image saved:\n{filepath}")
        else:
            self.show_error("Failed to save image.")

    def show_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Error", message)

    def show_info(self, message):
        QtWidgets.QMessageBox.information(self, "Success", message)

    def closeEvent(self, event):
        """Release resources when closing."""
        if self.cap is not None:
            self.cap.release()
        self.timer.stop()
        event.accept()

    def resizeEvent(self, event):
        """Update frame when window is resized."""
        self.update_frame()
        super().resizeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    viewer = RTSPViewer(RTSP_RIGHT)
    viewer.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()