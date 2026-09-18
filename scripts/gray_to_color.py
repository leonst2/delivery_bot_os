#!/usr/bin/env python3
"""Re-encode a recorded video, remapping every frame's brightness through a
false-color colormap (default) or replicating it into plain 3-channel gray.

Note: since the OV9281 cameras have no color filter array, there is no real
color information in the source to recover — a colormap just remaps
brightness to a color gradient for visual inspection (e.g. to make detail
pop), it does not represent actual captured color. Pass --flat for the
old behavior (cv2.cvtColor GRAY2BGR: equal B=G=R, still visually gray).

Usage:
    python3 scripts/gray_to_color.py camera0.mp4                  # one export per colormap
    python3 scripts/gray_to_color.py camera0.mp4 --colormap jet   # just one
    python3 scripts/gray_to_color.py camera0.mp4 --flat           # also export plain gray
    python3 scripts/gray_to_color.py camera0.mp4 --rotation 0     # default is 180
"""

import argparse
import os
import sys

import cv2

COLORMAPS = {
    "autumn": cv2.COLORMAP_AUTUMN,
    "bone": cv2.COLORMAP_BONE,
    "hot": cv2.COLORMAP_HOT,
    "inferno": cv2.COLORMAP_INFERNO,
    "jet": cv2.COLORMAP_JET,
    "magma": cv2.COLORMAP_MAGMA,
    "ocean": cv2.COLORMAP_OCEAN,
    "plasma": cv2.COLORMAP_PLASMA,
    "rainbow": cv2.COLORMAP_RAINBOW,
    "turbo": cv2.COLORMAP_TURBO,
    "viridis": cv2.COLORMAP_VIRIDIS,
}

ROTATIONS = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def convert(in_path: str, out_path: str, colormap: str | None, rotation: int) -> None:
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        sys.exit(f"Could not open {in_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if rotation in (90, 270):
        width, height = height, width

    rotate_code = ROTATIONS[rotation]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        sys.exit(f"Could not open {out_path} for writing")

    frame_count = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if rotate_code is not None:
                frame = cv2.rotate(frame, rotate_code)

            # cv2.VideoCapture decodes to BGR by default even for a
            # grayscale-sourced stream, so collapse back to a single
            # channel first — otherwise GRAY2BGR would reject a 3-channel
            # input.
            if frame.ndim == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if colormap is None:
                color_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            else:
                color_frame = cv2.applyColorMap(frame, COLORMAPS[colormap])
            writer.write(color_frame)
            frame_count += 1
    finally:
        cap.release()
        writer.release()

    print(f"Wrote {frame_count} frames -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="path to the recorded video")
    parser.add_argument(
        "--out", default=None,
        help="output path — only valid together with a single --colormap "
        "(default: <input>_<colormap>.mp4 next to the input)",
    )
    parser.add_argument(
        "--colormap", default="all", choices=[*sorted(COLORMAPS), "all"],
        help="false-color colormap to apply; 'all' (default) exports one "
        "video per available colormap",
    )
    parser.add_argument(
        "--flat", action="store_true",
        help="additionally export a plain 3-channel gray version (B=G=R, "
        "still renders as plain gray — useful only if a downstream tool "
        "needs 3-channel input)",
    )
    parser.add_argument(
        "--rotation", type=int, default=180, choices=sorted(ROTATIONS),
        help="degrees to rotate each frame clockwise before conversion "
        "(default: 180)",
    )
    args = parser.parse_args()

    if args.out is not None and args.colormap == "all":
        sys.exit("--out can only be used together with a single --colormap, not 'all'")

    root, _ext = os.path.splitext(args.input)

    colormaps = sorted(COLORMAPS) if args.colormap == "all" else [args.colormap]
    for name in colormaps:
        out_path = args.out or f"{root}_{name}.mp4"
        convert(args.input, out_path, name, args.rotation)

    if args.flat:
        convert(args.input, f"{root}_flat.mp4", None, args.rotation)


if __name__ == "__main__":
    main()
