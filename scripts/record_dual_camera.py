#!/usr/bin/env python3
"""Record a short video from each attached CSI camera at the same time.

Usage:
    python3 scripts/record_dual_camera.py --duration 10 --out-dir ./captures
"""

import argparse
import os
import sys
import time

from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput


def record(duration: float, out_dir: str, width: int, height: int, convert_to_rgb: bool) -> None:
    cameras = Picamera2.global_camera_info()
    if len(cameras) < 2:
        sys.exit(f"Expected 2 cameras, found {len(cameras)}: {cameras}")

    os.makedirs(out_dir, exist_ok=True)

    main_stream = {"size": (width, height)}
    if convert_to_rgb:
        # OV9281 is mono (no color filter array), so this just replicates the
        # single channel into equal R=G=B values at the ISP level — it does
        # not add real color information, only changes the pixel format from
        # the sensor's native single-channel data to a 3-channel layout.
        main_stream["format"] = "RGB888"

    picams = []
    try:
        for cam_num in range(2):
            picam2 = Picamera2(camera_num=cam_num)
            # Append immediately so a failure below (e.g. the other camera
            # being busy) still lets the `finally` block close this one.
            picams.append(picam2)
            config = picam2.create_video_configuration(main=main_stream)
            picam2.configure(config)

            out_path = os.path.join(out_dir, f"camera{cam_num}.mp4")
            picam2.start_recording(H264Encoder(), FfmpegOutput(out_path))
            print(f"Recording camera {cam_num} -> {out_path}")

        try:
            time.sleep(duration)
        except KeyboardInterrupt:
            print("Interrupted, stopping...")
    finally:
        # Each camera is closed independently so a second Ctrl+C (or any
        # error) while closing one camera can't skip closing the others.
        for cam_num, picam2 in enumerate(picams):
            try:
                picam2.stop_recording()
            except Exception:
                pass  # never started recording, or already stopped
            try:
                picam2.close()
            except BaseException as exc:
                print(f"Warning: error closing camera {cam_num}: {exc}")
            else:
                print(f"Stopped camera {cam_num}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=5.0, help="seconds to record")
    parser.add_argument("--out-dir", default=".", help="output directory")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument(
        "--convert-to-rgb",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Record as 3-channel RGB instead of the sensor's native mono "
        "format (OV9281 has no color filter array, so this only changes "
        "pixel format/channel count, not actual color content). "
        "Default: on — pass --no-convert-to-rgb for native mono.",
    )
    args = parser.parse_args()
    record(args.duration, args.out_dir, args.width, args.height, args.convert_to_rgb)


if __name__ == "__main__":
    main()
