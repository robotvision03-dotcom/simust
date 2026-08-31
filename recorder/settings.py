# recorder/settings.py

FRAMES_QUEUE_SIZE = 100
VIDEOS_FILE_EXTENSION = ".mp4"
VIDEOS_FOURCC = "mp4v"
DIRECTORY_NAME_PATTERN = "%Y-%m-%d_%H-%M-%S"
TIMEOUT = 5

CAMERAS = {
    "qr-camera": {
        "address": "rtsp://admin:admin@192.168.2.131:554/ch01",
        "screen_record": True,
        "offset_x": 1920,  # Start of second monitor
        "offset_y": 0,
        "width": 1920,     # Record only ONE monitor (1920), not both (3840)
        "height": 1080,
        "framerate": 30.0,
        "fps": 30.0,
        "enabled": False,
        # QR detection settings
        "qr_roi": {
            "x": 0,
            "y": 0,
            "width": 1920,  # Scan entire width
            "height": 540   # Top half of screen
        },
        "draw_roi": True,  # Enable for debugging
        "qr_cooldown": 0.5
    },
    "camera-1": {
        "address": "rtsp://admin:majidAram2@192.168.2.1:554/Streaming/Channels/101/",
        "fps": 25.0
    },
    "camera-8": {
        "address": "rtsp://admin:majidAram2@192.168.2.8:554/Streaming/Channels/101/",
        "fps": 25.0
    }
}