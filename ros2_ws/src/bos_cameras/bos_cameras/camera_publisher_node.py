#!/usr/bin/env python3
"""Publish frames from one CSI camera as sensor_msgs/Image.

Parameters:
  camera_num (int): which picamera2 camera index to open (0 or 1).
  topic (str): output image topic.
  width, height (int): capture resolution.
  frame_rate (float): publish rate in Hz.
"""

import rclpy # type: ignore
from rclpy.node import Node # type: ignore
from sensor_msgs.msg import Image # type: ignore

from bos_cameras.picamera2_camera import Picamera2Camera


class CameraPublisher(Node):
    def __init__(self) -> None:
        super().__init__("camera_publisher")

        self.declare_parameter("camera_num", 0)
        self.declare_parameter("topic", "camera0/image_raw")
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 800)
        self.declare_parameter("frame_rate", 30.0)

        camera_num = self.get_parameter("camera_num").value
        topic = self.get_parameter("topic").value
        width = self.get_parameter("width").value
        height = self.get_parameter("height").value
        frame_rate = self.get_parameter("frame_rate").value

        self._camera = Picamera2Camera(camera_num, width, height)

        self._pub = self.create_publisher(Image, topic, 10)
        self._timer = self.create_timer(1.0 / frame_rate, self._on_timer)
        self.get_logger().info(f"camera {camera_num} publishing on {topic}")

    def _on_timer(self) -> None:
        frame = self._camera.capture()

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.height, msg.width = frame.shape
        msg.encoding = "mono8"
        msg.is_bigendian = 0
        msg.step = frame.shape[1]
        msg.data = frame.tobytes()
        self._pub.publish(msg)

    def destroy_node(self) -> None:
        self._camera.close()
        super().destroy_node()


def main() -> None:
    rclpy.init()
    node = CameraPublisher()
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
