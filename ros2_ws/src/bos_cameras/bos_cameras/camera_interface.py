"""Generic interface for a physical camera, so callers (ROS nodes or
otherwise) don't depend on a specific camera SDK (picamera2, a USB webcam
driver, etc.) directly.

The constructor is deliberately NOT part of this interface: different
camera hardware needs different setup arguments (camera index + resolution
for a Picamera2 camera, a device path for a USB camera, ...). The shared
contract is only capture()/close().
"""

from abc import ABC, abstractmethod

import numpy as np


class CameraInterface(ABC):
    @abstractmethod
    def capture(self) -> np.ndarray:
        """Capture and return the current frame."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying camera hardware. Implementations must be
        idempotent (safe to call more than once)."""

    def __enter__(self) -> "CameraInterface":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def __del__(self) -> None:
        # Safety net only. Callers (e.g. a ROS node's destroy_node()) must
        # still call close() explicitly and deterministically — some
        # hardware (see HailoAccelerator) segfaults if release order is
        # left to unpredictable garbage-collection timing instead.
        try:
            self.close()
        except Exception:
            pass
