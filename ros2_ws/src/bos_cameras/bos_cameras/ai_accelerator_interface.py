"""Generic interface for an AI accelerator that runs a model against an
image (Hailo8, or any future replacement), so callers don't depend on a
specific accelerator SDK directly.
"""

from abc import ABC, abstractmethod

import numpy as np


class AIAcceleratorInterface(ABC):
    def __init__(self, model_path: str) -> None:
        """Subclasses call super().__init__(model_path) and then load/
        configure that model onto their specific hardware."""
        self.model_path = model_path

    @abstractmethod
    def process(self, image: np.ndarray) -> list[dict]:
        """Run inference on `image` and return a list of result dicts
        (e.g. detections)."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying accelerator hardware. Implementations
        must be idempotent (safe to call more than once)."""

    def __enter__(self) -> "AIAcceleratorInterface":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def __del__(self) -> None:
        # Safety net only — see CameraInterface.__del__ for why callers
        # must still call close() explicitly and deterministically.
        try:
            self.close()
        except Exception:
            pass
