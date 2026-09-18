import cv2
import numpy as np

from bos_cameras.camera_interface import CameraInterface


class UsbCamera(CameraInterface):
    def __init__(
        self,
        device: str,
        width: int,
        height: int,
        frame_rate: float,
        fourcc: str = "MJPG",
    ) -> None:
        self._closed = True  # until the device is actually open
        self._device = device
        self._cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            self._cap.release()
            raise RuntimeError(
                f"could not open USB camera at {device!r} — is it plugged in "
                "(before the container started) and is the path visible in "
                "the container?"
            )
        self._closed = False

        # FOURCC must be set before the size/fps: UVC cameras only offer
        # their high resolutions in a compressed format like MJPG.
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, frame_rate)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # always the newest frame

    def capture(self) -> np.ndarray:
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError(f"failed to read a frame from USB camera {self._device!r}")
        # OpenCV delivers BGR; the interface contract is RGB.
        return np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def close(self) -> None:
        if self._closed:
            return
        self._cap.release()
        self._closed = True
