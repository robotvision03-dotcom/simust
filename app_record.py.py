import cv2
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import threading
import time
import os
from datetime import datetime
import numpy as np

# ----------------------------------------------------------------------
# RTSP streams – same as in app.py
# ----------------------------------------------------------------------
RTSP_LEFT = "rtsp://admin:majidAram2@192.168.2.1:554/Streaming/Channels/101/"
RTSP_RIGHT = "rtsp://admin:majidAram2@192.168.2.8:554/Streaming/Channels/101/"

# Directory where recordings will be saved
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------
# GUI Application
# ----------------------------------------------------------------------
class StitchedVideoRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Stitched Video Recorder (HR)")
        self.root.geometry("1200x800")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # State variables
        self.cap_left = None
        self.cap_right = None
        self.recording = False
        self.video_writer = None
        self.recording_path = None
        self.running = True
        self.frame = None  # latest stitched frame

        # Video dimensions (will be set after first read)
        self.width = 1920
        self.height = 1080
        self.stitched_width = 3840
        self.stitched_height = 1080

        # UI layout
        self.create_widgets()

        # Start the video capture thread
        self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.capture_thread.start()

        # Start the GUI update loop
        self.update_video()

    def create_widgets(self):
        # Top control frame
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill=tk.X)

        self.status_label = ttk.Label(control_frame, text="Status: Stopped", font=("Arial", 12))
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.record_btn = ttk.Button(control_frame, text="Start Recording", command=self.toggle_recording)
        self.record_btn.pack(side=tk.LEFT, padx=10)

        self.time_label = ttk.Label(control_frame, text="Recording: 00:00", font=("Arial", 12))
        self.time_label.pack(side=tk.LEFT, padx=10)

        self.path_label = ttk.Label(control_frame, text="", font=("Arial", 9), foreground="gray")
        self.path_label.pack(side=tk.LEFT, padx=10)

        # Video display canvas (will be resized to fit window)
        self.video_frame = ttk.Frame(self.root)
        self.video_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.canvas = tk.Canvas(self.video_frame, bg='black')
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Bind resize event to adjust image
        self.root.bind('<Configure>', self.on_resize)

        # Recording timer variables
        self.recording_start_time = None
        self.timer_running = False
        self.timer_thread = None
        self.timer_stop = threading.Event()

    def on_resize(self, event):
        # Redraw the current frame when window resizes
        if self.frame is not None:
            self.display_frame(self.frame)

    def display_frame(self, frame):
        """Display a frame on the canvas, scaling to fit."""
        if frame is None:
            return
        # Get canvas size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width < 10 or canvas_height < 10:
            canvas_width = 1000
            canvas_height = 600

        # Calculate scaling to fit while preserving aspect ratio
        h, w = frame.shape[:2]
        scale = min(canvas_width / w, canvas_height / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        if new_w < 1 or new_h < 1:
            return

        # Resize the frame
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        # Convert to RGB and then to ImageTk
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(image=img)

        # Update canvas
        self.canvas.delete("all")
        self.canvas.create_image(canvas_width//2, canvas_height//2, anchor=tk.CENTER, image=imgtk)
        self.canvas.image = imgtk  # keep a reference

    def update_video(self):
        """Called periodically to update the display with the latest frame."""
        if self.running and self.frame is not None:
            self.display_frame(self.frame)
        if self.running:
            self.root.after(30, self.update_video)  # ~33 fps

    def capture_loop(self):
        """Main loop: capture from both RTSP streams, stitch, and optionally record."""
        # Open streams
        self.cap_left = cv2.VideoCapture(RTSP_LEFT)
        self.cap_right = cv2.VideoCapture(RTSP_RIGHT)

        if not self.cap_left.isOpened() or not self.cap_right.isOpened():
            self.root.after(0, lambda: messagebox.showerror("Error", "Could not open one or both RTSP streams"))
            self.running = False
            return

        # Read first frames to get dimensions
        ret_left, frame_left = self.cap_left.read()
        ret_right, frame_right = self.cap_right.read()
        if not ret_left or not ret_right:
            self.root.after(0, lambda: messagebox.showerror("Error", "Failed to read initial frames from streams"))
            self.running = False
            return

        h, w_left, _ = frame_left.shape
        _, w_right, _ = frame_right.shape
        self.height = h
        self.width = w_left + w_right
        self.stitched_height = h
        self.stitched_width = w_left + w_right
        print(f"Stitched dimensions: {self.stitched_width}x{self.stitched_height}")

        while self.running:
            ret_left, frame_left = self.cap_left.read()
            ret_right, frame_right = self.cap_right.read()
            if not ret_left or not ret_right:
                # If one stream fails, wait a bit
                time.sleep(0.05)
                continue

            # Stitch horizontally
            stitched = cv2.hconcat([frame_left, frame_right])
            self.frame = stitched

            # If recording, write frame
            if self.recording and self.video_writer is not None:
                self.video_writer.write(stitched)

        # Cleanup
        if self.cap_left:
            self.cap_left.release()
        if self.cap_right:
            self.cap_right.release()
        if self.video_writer:
            self.video_writer.release()
        print("Capture loop terminated.")

    def toggle_recording(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if self.recording:
            return
        if self.frame is None:
            messagebox.showwarning("Warning", "No video frames available to record.")
            return

        # Create video writer
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"stitched_{timestamp}.mp4"
        self.recording_path = os.path.join(BASE_DIR, filename)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        # Use the actual stitched dimensions
        self.video_writer = cv2.VideoWriter(
            self.recording_path, fourcc, 25.0,
            (self.stitched_width, self.stitched_height)
        )
        if not self.video_writer.isOpened():
            messagebox.showerror("Error", "Could not open video writer. Check file permissions.")
            self.video_writer = None
            return

        self.recording = True
        self.record_btn.config(text="Stop Recording")
        self.status_label.config(text="Status: Recording...", foreground="red")
        self.path_label.config(text=f"Saving to: {self.recording_path}")

        # Start timer
        self.recording_start_time = time.time()
        self.timer_running = True
        self.timer_stop.clear()
        self.timer_thread = threading.Thread(target=self.update_timer, daemon=True)
        self.timer_thread.start()

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.timer_running = False
        self.timer_stop.set()
        if self.timer_thread and self.timer_thread.is_alive():
            self.timer_thread.join(timeout=1.0)

        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None

        self.record_btn.config(text="Start Recording")
        self.status_label.config(text="Status: Stopped", foreground="black")
        self.time_label.config(text="Recording: 00:00")
        if self.recording_path:
            self.path_label.config(text=f"Saved: {self.recording_path}")
            print(f"Recording saved: {self.recording_path}")

    def update_timer(self):
        """Update the timer label every second."""
        while self.timer_running and not self.timer_stop.is_set():
            if self.recording_start_time:
                elapsed = int(time.time() - self.recording_start_time)
                mins = elapsed // 60
                secs = elapsed % 60
                self.root.after(0, lambda m=mins, s=secs: self.time_label.config(text=f"Recording: {m:02d}:{s:02d}"))
            time.sleep(1)

    def on_close(self):
        """Clean up on window close."""
        self.running = False
        if self.recording:
            self.stop_recording()
        self.root.destroy()

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = StitchedVideoRecorder(root)
    root.mainloop()