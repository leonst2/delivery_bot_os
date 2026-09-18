#!/usr/bin/env python3
"""Serve the latest frame from an image topic as an MJPEG stream over HTTP,
viewable from any device on the network at http://<this-host's-ip>:<port>/.

Parameters:
  input_topic (str): image topic to subscribe to.
  port (int): HTTP port to serve on.
  jpeg_quality (int): JPEG encode quality, 0-100.
"""

import threading

import cv2
import rclpy # type: ignore
from flask import Flask, Response
from rclpy.node import Node # type: ignore
from sensor_msgs.msg import Image # type: ignore

from bos_cameras.image_utils import image_msg_to_array

INDEX_HTML = """<!doctype html>
<title>{topic}</title>
<body style="margin:0;background:#000">
<img src="/stream" style="width:100%;height:auto;display:block">
</body>
"""


class WebViewerNode(Node):
    def __init__(self) -> None:
        super().__init__("web_viewer")

        self.declare_parameter("input_topic", "camera0/image_raw")
        self.declare_parameter("port", 8080)
        self.declare_parameter("jpeg_quality", 80)

        input_topic = self.get_parameter("input_topic").value
        self._port = self.get_parameter("port").value
        self._jpeg_quality = self.get_parameter("jpeg_quality").value

        self._lock = threading.Lock()
        self._new_frame = threading.Condition(self._lock)
        self._latest_jpeg = None

        self._sub = self.create_subscription(Image, input_topic, self._on_image, 10)

        app = Flask(__name__)
        app.add_url_rule("/", "index", self._index)
        app.add_url_rule("/stream", "stream", self._stream)
        self._server_thread = threading.Thread(
            target=app.run,
            kwargs={"host": "0.0.0.0", "port": self._port, "threaded": True, "use_reloader": False},
            daemon=True,
        )
        self._server_thread.start()

        self._input_topic = input_topic
        self.get_logger().info(
            f"web_viewer: {input_topic} -> http://0.0.0.0:{self._port}/ "
            "(reachable from any device on the network)"
        )

    def _on_image(self, msg: Image) -> None:
        frame = image_msg_to_array(msg)
        ok, encoded = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        )
        if not ok:
            return
        with self._new_frame:
            self._latest_jpeg = encoded.tobytes()
            self._new_frame.notify_all()

    def _index(self):
        return INDEX_HTML.format(topic=self._input_topic)

    def _stream(self):
        def generate():
            last_sent = None
            while rclpy.ok():
                with self._new_frame:
                    # Wake on every new frame, but re-check rclpy.ok()
                    # periodically too so shutdown doesn't hang this thread
                    # waiting on a camera that has stopped publishing.
                    self._new_frame.wait_for(
                        lambda: self._latest_jpeg is not last_sent, timeout=1.0
                    )
                    frame = self._latest_jpeg
                if frame is None or frame is last_sent:
                    continue
                last_sent = frame
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


def main() -> None:
    rclpy.init()
    node = WebViewerNode()
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
