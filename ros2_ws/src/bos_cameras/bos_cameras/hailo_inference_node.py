#!/usr/bin/env python3
"""Run YOLOv8 (Hailo8) inference on an incoming image topic, log each
detection with a timestamp, and publish detections.

Parameters:
  input_topic (str): image topic to subscribe to.
  output_topic (str): std_msgs/String topic to publish detections to, as a
    JSON array of {class_id, class_name, score, cx, cy, w, h} (cx/cy/w/h in
    pixels).
  hef_path (str): path to the compiled .hef model (produced by the Hailo
    Dataflow Compiler from an exported ultralytics ONNX model — this file
    is hardware/model specific and is NOT included here).
  score_threshold (float): minimum confidence to keep a detection.
  class_names (list[str]): index -> label used for logging/output.
    Defaults to the 80 COCO classes (ultralytics' default YOLOv8 training set).
  log_file (str): path to a plain-text file that each detection is appended
    to as "<iso timestamp> class_id=.. class_name=.. score=.. cx=.. cy=.. w=.. h=..".
    Defaults under ros2_ws/, which is bind-mounted onto the host, so the
    file is readable from the host at the same relative path.
"""

import json
import os
from datetime import datetime, timezone

import rclpy # type: ignore
from rclpy.node import Node # type: ignore
from sensor_msgs.msg import Image # type: ignore 
from std_msgs.msg import String # type: ignore

from bos_cameras.hailo_accelerator import COCO_CLASSES, HailoYoloAccelerator
from bos_cameras.image_utils import image_msg_to_array


def stamp_to_iso(stamp) -> str:
    """Convert a ROS Time (header.stamp) to an ISO-8601 UTC string."""
    seconds = stamp.sec + stamp.nanosec * 1e-9
    if seconds <= 0:
        seconds = datetime.now(tz=timezone.utc).timestamp()
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


class HailoInferenceNode(Node):
    def __init__(self) -> None:
        super().__init__("hailo_inference")

        self.declare_parameter("input_topic", "camera0/image_raw")
        self.declare_parameter("output_topic", "camera0/detections")
        self.declare_parameter("hef_path", "/ros2_ws/models/yolov8m.hef")
        self.declare_parameter("score_threshold", 0.5)
        self.declare_parameter("class_names", COCO_CLASSES)
        self.declare_parameter("log_file", "/ros2_ws/logs/detections.log")

        hef_path = self.get_parameter("hef_path").value
        score_threshold = self.get_parameter("score_threshold").value
        class_names = self.get_parameter("class_names").value
        input_topic = self.get_parameter("input_topic").value
        output_topic = self.get_parameter("output_topic").value
        log_file = self.get_parameter("log_file").value

        if not hef_path:
            raise ValueError(
                "hef_path parameter is required — point it at a compiled "
                ".hef file for this model/Hailo8 target"
            )

        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        self._log_file = open(log_file, "a", buffering=1)

        self._accelerator = HailoYoloAccelerator(hef_path, score_threshold, class_names)

        self._sub = self.create_subscription(Image, input_topic, self._on_image, 10)
        self._pub = self.create_publisher(String, output_topic, 10)
        self.get_logger().info(
            f"hailo inference: {input_topic} -> {output_topic} using {hef_path}, "
            f"logging detections to {log_file}"
        )

    def _on_image(self, msg: Image) -> None:
        frame = image_msg_to_array(msg)
        detections = self._accelerator.process(frame)

        timestamp = stamp_to_iso(msg.header.stamp)
        for det in detections:
            self.get_logger().info(
                f"[{timestamp}] detected {det['class_name']} "
                f"(class {det['class_id']}) score={det['score']:.2f} "
                f"bbox=(cx={det['cx']:.1f}, cy={det['cy']:.1f}, "
                f"w={det['w']:.1f}, h={det['h']:.1f})"
            )
            self._log_file.write(
                f"{timestamp} class_id={det['class_id']} "
                f"class_name={det['class_name']} score={det['score']:.2f} "
                f"cx={det['cx']:.1f} cy={det['cy']:.1f} "
                f"w={det['w']:.1f} h={det['h']:.1f}\n"
            )

        out = String()
        out.data = json.dumps({"timestamp": timestamp, "detections": detections})
        self._pub.publish(out)

    def destroy_node(self) -> None:
        self._log_file.close()
        self._accelerator.close()
        super().destroy_node()


def main() -> None:
    rclpy.init()
    node = HailoInferenceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
