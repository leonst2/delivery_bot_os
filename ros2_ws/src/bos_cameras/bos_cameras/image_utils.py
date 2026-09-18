import numpy as np
from sensor_msgs.msg import Image # type: ignore


def image_msg_to_array(msg: Image) -> np.ndarray:
    frame = np.frombuffer(msg.data, dtype=np.uint8)
    channels = {"mono8": 1, "rgb8": 3, "bgr8": 3}.get(msg.encoding, 1)
    frame = frame.reshape((msg.height, msg.width, channels)) if channels > 1 else \
        frame.reshape((msg.height, msg.width))
    return frame
