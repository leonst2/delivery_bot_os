import cv2
import numpy as np
from picamera2 import Picamera2

from bos_cameras.camera_interface import CameraInterface


class Picamera2Camera(CameraInterface):
    def __init__(self, camera_num: int, width: int, height: int) -> None:
        self._picam2 = Picamera2(camera_num=camera_num)
        config = self._picam2.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"}
        )
        self._picam2.configure(config)
        self._picam2.start()
        self._closed = False

    def capture(self) -> np.ndarray:
        frame = self._picam2.capture_array()
        # OV9281 is mono; picamera2 still delivers an RGB888-shaped buffer
        # with equal channels, so squeeze to a true single-channel image.
        if frame.ndim == 3 and frame.shape[2] >= 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return np.ascontiguousarray(frame)

    def close(self) -> None:
        if self._closed:
            return
        self._picam2.stop()
        self._picam2.close()
        self._closed = True
