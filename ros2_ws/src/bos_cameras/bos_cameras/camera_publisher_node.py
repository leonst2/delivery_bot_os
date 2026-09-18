#!/usr/bin/env python3
"""Publish frames from one camera as sensor_msgs/Image.

Parameters:
  camera_type (str): "picamera2" (CSI camera, published as mono8) or "usb"
    (V4L2/UVC webcam, published as rgb8).
  camera_num (int): picamera2 only — which camera index to open (0 or 1).
  device (str): usb only — V4L2 device path, ideally a stable
    /dev/v4l/by-id/... path rather than /dev/videoN.
  fourcc (str): usb only — pixel format to request, e.g. "MJPG" or "YUYV".
  topic (str): output image topic.
  width, height (int): capture resolution.
  frame_rate (float): publish rate in Hz.
"""

import rclpy # type: ignore
from rclpy.node import Node # type: ignore
from sensor_msgs.msg import Image # type: ignore

from bos_cameras.camera_interface import CameraInterface
from bos_cameras.picamera2_camera import Picamera2Camera
from bos_cameras.usb_camera import UsbCamera


class CameraPublisher(Node):
    def __init__(self) -> None:
        super().__init__("camera_publisher")

        self.declare_parameter("camera_type", "picamera2")
        self.declare_parameter("camera_num", 0)
        self.declare_parameter("device", "")
        self.declare_parameter("fourcc", "MJPG")
        self.declare_parameter("topic", "camera0/image_raw")
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 800)
        self.declare_parameter("frame_rate", 30.0)

        camera_type = self.get_parameter("camera_type").value
        camera_num = self.get_parameter("camera_num").value
        device = self.get_parameter("device").value
        fourcc = self.get_parameter("fourcc").value
        topic = self.get_parameter("topic").value
        width = self.get_parameter("width").value
        height = self.get_parameter("height").value
        frame_rate = self.get_parameter("frame_rate").value

        self._camera: CameraInterface
        if camera_type == "picamera2":
            self._camera = Picamera2Camera(camera_num, width, height)
            label = f"camera {camera_num}"
        elif camera_type == "usb":
            self._camera = UsbCamera(device, width, height, frame_rate, fourcc)
            label = f"usb camera {device}"
        else:
            raise ValueError(
                f"unknown camera_type {camera_type!r} — expected 'picamera2' or 'usb'"
            )

        self._pub = self.create_publisher(Image, topic, 10)
        self._timer = self.create_timer(1.0 / frame_rate, self._on_timer)
        self.get_logger().info(f"{label} publishing on {topic}")

    def _on_timer(self) -> None:
        frame = self._camera.capture()
        channels = 1 if frame.ndim == 2 else frame.shape[2]

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.height, msg.width = frame.shape[:2]
        msg.encoding = "mono8" if channels == 1 else "rgb8"
        msg.is_bigendian = 0
        msg.step = msg.width * channels
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
