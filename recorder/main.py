# recorder/main.py (updated)
import os
import threading
from datetime import datetime
import logging
import multiprocessing
from . import settings
from .video_recorder import VideoRecorder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def prepare_video_recorders(selected_cameras):
    video_recorders = {}
    if not selected_cameras:
        logger.error("No cameras selected for recording")
        raise Exception("No cameras selected for recording")

    barrier = multiprocessing.Barrier(len(selected_cameras) + 1)
    stop_event = multiprocessing.Event()

    for cam_name in selected_cameras:
        if cam_name in settings.CAMERAS:
            config = settings.CAMERAS[cam_name]
            address = config["address"] if not config.get("screen_record", False) else None
            recorder = VideoRecorder(
                cam_name,
                address,
                config,  # Pass full config (incl. FPS)
                timeout=settings.TIMEOUT
            )
            try:
                if not config.get("screen_record", False):
                    video_capture = recorder._connect_camera(config["address"])
                    if not video_capture.isOpened():
                        raise Exception(f"Camera {cam_name} failed to open")
                    video_capture.release()
                    logger.info(f"Successfully pre-connected to {cam_name} with FPS {config.get('fps', 25.0)}")
                else:
                    logger.info(f"Prepared screen recorder for {cam_name} with framerate {config.get('framerate', 30.0)}")
                recorder.set_start_barrier(barrier)
                recorder.set_stop_event(stop_event)
                video_recorders[cam_name] = recorder
            except Exception as e:
                logger.error(f"Failed to connect to {cam_name}: {e}")
                raise Exception(f"Camera {cam_name} is not ready: {e}")
        else:
            logger.error(f"Camera {cam_name} not found in settings.CAMERAS")
            raise Exception(f"Camera {cam_name} not found in settings.CAMERAS")

    return video_recorders, barrier, stop_event

def capture_videos(video_recorders, barrier, stop_event, output_path):
    timestamp = datetime.now().strftime(settings.DIRECTORY_NAME_PATTERN)
    videos_path = os.path.join(output_path, timestamp)
    if not os.path.exists(videos_path):
        os.makedirs(videos_path)

    def start_recorder(camera_name, recorder, videos_path):
        video_file_name = f"{camera_name}{settings.VIDEOS_FILE_EXTENSION}"
        video_path = os.path.join(videos_path, video_file_name)
        logger.info(f"Preparing to start capturing video: {camera_name}...")
        try:
            recorder.start(video_path)
        except Exception as e:
            logger.error(f"Failed to start {camera_name}: {e}")
            raise

    threads = []
    for camera_name, recorder in video_recorders.items():
        thread = threading.Thread(
            target=start_recorder,
            args=(camera_name, recorder, videos_path),
            daemon=True
        )
        threads.append(thread)
        thread.start()

    # Wait for all startup threads to complete (ensures processes are launched)
    for thread in threads:
        thread.join()
    logger.info("All camera processes launched - now syncing via barrier")

    # Track processes now that they're started
    processes = [recorder._main_process for recorder in video_recorders.values() if recorder._main_process]

    # Sync point: Main process waits, releasing all cameras to start threads simultaneously
    logger.info(f"Main process waiting at barrier to sync {len(video_recorders)} cameras")
    try:
        barrier.wait(timeout=10)  # Main releases the barrier
        logger.info("Main process passed barrier - all cameras synced and recording")
    except multiprocessing.BrokenBarrierError:
        logger.error("Barrier broken - some cameras failed to sync; stopping all")
        stop_event.set()
        raise
    except Exception as e:
        logger.error(f"Barrier wait failed in main: {e}")
        stop_event.set()
        raise

    # Wait for stop signal
    stop_event.wait()
    logger.info("Stop event received - stopping all recorders")

    # Stop all recorders
    for camera_name, recorder in video_recorders.items():
        logger.info(f"Stopping video capture: {camera_name}...")
        recorder.stop()

    # Cleanup processes if needed
    for proc in processes:
        if proc and proc.is_alive():
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                logger.warning(f"Terminated lingering process {proc.pid}")