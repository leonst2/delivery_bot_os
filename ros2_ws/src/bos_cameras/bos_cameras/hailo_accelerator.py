"""AIAcceleratorInterface implementation for Hailo8, running a YOLOv8
model compiled with Hailo's on-chip NMS postprocess (the standard path for
YOLOv8 via the Hailo Model Zoo / Dataflow Compiler): the model's output is
one array per class, each row [ymin, xmin, ymax, xmax, score] normalized
to [0, 1]. A HEF compiled without on-chip NMS would need different
decoding in process().
"""

import cv2
import numpy as np
from hailo_platform import FormatType, HailoSchedulingAlgorithm, VDevice

from bos_cameras.ai_accelerator_interface import AIAcceleratorInterface

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]


class HailoYoloAccelerator(AIAcceleratorInterface):
    def __init__(
        self,
        model_path: str,
        score_threshold: float = 0.5,
        class_names: list[str] = COCO_CLASSES,
    ) -> None:
        super().__init__(model_path)
        self._score_threshold = score_threshold
        self._class_names = class_names
        self._closed = False

        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        self._vdevice = VDevice(params)
        self._infer_model = self._vdevice.create_infer_model(model_path)
        self._infer_model.input().set_format_type(FormatType.UINT8)
        self._configured_model = self._infer_model.configure()

        output_stream = self._infer_model.output()
        self._output_shape = output_stream.shape
        self._output_dtype = {
            FormatType.FLOAT32: np.float32,
            FormatType.UINT8: np.uint8,
            FormatType.UINT16: np.uint16,
        }[output_stream.format.type]

    def process(self, image: np.ndarray) -> list[dict]:
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

        input_h, input_w, _ = self._infer_model.input().shape
        resized = cv2.resize(image, (input_w, input_h))

        bindings = self._configured_model.create_bindings()
        bindings.input().set_buffer(np.ascontiguousarray(resized))
        bindings.output().set_buffer(np.empty(self._output_shape, dtype=self._output_dtype))
        self._configured_model.run([bindings], timeout=1000)
        raw_detections = bindings.output().get_buffer()

        return self._postprocess(raw_detections, image.shape[1], image.shape[0])

    def _postprocess(self, raw_detections, frame_w: int, frame_h: int) -> list[dict]:
        """Decode Hailo's on-chip NMS output into a list of detection dicts.

        `raw_detections` is one array per class, each row
        [ymin, xmin, ymax, xmax, score] normalized to [0, 1].
        """
        detections = []
        for class_id, class_boxes in enumerate(raw_detections):
            for row in class_boxes:
                score = float(row[4])
                if score < self._score_threshold:
                    continue

                ymin, xmin, ymax, xmax = (float(v) for v in row[0:4])
                x1, y1, x2, y2 = xmin * frame_w, ymin * frame_h, xmax * frame_w, ymax * frame_h
                class_name = (
                    self._class_names[class_id]
                    if 0 <= class_id < len(self._class_names)
                    else str(class_id)
                )
                detections.append({
                    "class_id": class_id,
                    "class_name": class_name,
                    "score": score,
                    "cx": (x1 + x2) / 2.0,
                    "cy": (y1 + y2) / 2.0,
                    "w": x2 - x1,
                    "h": y2 - y1,
                })
        return detections

    def close(self) -> None:
        if self._closed:
            return
        # Explicitly release in this order (rather than letting the
        # garbage collector do it in whatever order it likes at
        # interpreter exit) — releasing the VDevice while bindings/
        # configured-model objects are still alive segfaults HailoRT.
        del self._configured_model
        del self._infer_model
        self._vdevice.release()
        self._closed = True
