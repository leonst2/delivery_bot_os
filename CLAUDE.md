# delivery_bos_os

ROS2 (Jazzy) stack for a Raspberry Pi 5 with a Hailo8 AI accelerator and two
CSI OV9281 mono cameras. Full architecture/workflow docs live in
[README.md](README.md) — read that first for anything beyond quick
orientation. This file exists to save a fresh session from re-deriving the
non-obvious facts below by exploration.

## Layout

```
docker/               Dockerfile.ros + docker-compose.ros.yml — see README "How it works"
ros2_ws/src/bos_cameras/   the one ROS2 package (ament_python, pure Python, no C++)
  bos_cameras/
    camera_interface.py        CameraInterface (ABC): capture() -> (H,W) mono or (H,W,3) RGB, close()
    picamera2_camera.py        CameraInterface for the CSI OV9281s (mono)
    usb_camera.py              CameraInterface for a V4L2/UVC webcam via OpenCV (RGB)
    camera_publisher_node.py   ROS adapter: camera_type param picks the CameraInterface -> sensor_msgs/Image
    ai_accelerator_interface.py  AIAcceleratorInterface (ABC): __init__(model_path), process(image), close()
    hailo_accelerator.py       AIAcceleratorInterface for Hailo8 YOLOv8 (COCO_CLASSES lives here)
    hailo_inference_node.py    ROS adapter: image topic -> accelerator.process() -> detections + log file
    web_viewer_node.py         image topic -> MJPEG stream over Flask (LAN-reachable)
    image_utils.py             shared image_msg_to_array() helper
  config/cameras.yaml          per-node params: camera0/1 (picamera2) + camera2 (usb)
  config/hailo_accelerator.yaml  inference node params (hef_path etc.)
  launch/cameras.launch.py     loads the YAML configs and wires all of the above together
ros2_ws/models/       drop .hef files here (bind-mounted into the container as /ros2_ws/models/)
ros2_ws/logs/         detections.log lands here (root-owned, written from inside the container)
firmware/esp32_motor_controller/   PlatformIO project (Arduino framework, C++) for the ESP32 NodeMCU-32S
                       motor controller; talks to the Pi over the USB serial link.
                       Build/flash with the venv's pio: `.venv/bin/pio run [-t upload]`
                       (toolchains live in ~/.platformio, outside the repo)
scripts/               standalone host-side tools, NOT part of the ROS2 package
  record_dual_camera.py   dual-camera capture to .mp4 (no ROS2)
  gray_to_color.py        recorded video -> false-color colormap export(s)
```

## Environment split (important, easy to get backwards)

- **Host** (Raspberry Pi OS/Debian trixie, bare metal): owns `/dev/hailo0` and
  the camera/libcamera stack via apt (`hailo-all`, `python3-picamera2`). No
  ROS install here. `hailo_platform` and `picamera2` ARE importable directly
  on the host (useful for quick manual tests without Docker).
- **Container** (`docker/Dockerfile.ros`): ROS2 Jazzy, built from source
  (no Debian/arm64 binaries exist for it), on the *same* Debian trixie +
  Raspberry Pi apt base as the host so `hailort`/`picamera2` binary builds
  match the host's kernel driver exactly. `ros2_ws/` is bind-mounted in
  (`--symlink-install`, so host edits take effect on next `ros2 launch`/`run`
  with no rebuild — rebuild only needed for a new file, a new
  `console_scripts` entry, or a `package.xml` change).
- Only `/dev/hailo0` and the camera devices are physically shared —
  **only one process system-wide** (host or container) can hold a given
  camera or the Hailo device at a time. A host-side script and the
  container will fight over the same hardware.

## Running it

```bash
docker compose -f docker/docker-compose.ros.yml up -d      # day-to-day
docker compose -f docker/docker-compose.ros.yml stop        # clean shutdown, frees cameras+Hailo
docker compose -f docker/docker-compose.ros.yml build       # only after Dockerfile.ros changes (~1hr, ROS2 built from source)
```
Full command reference (build/iterate/inspect-graph variants) is in the
README's Workflow section — don't duplicate it here, it drifts.

## Non-obvious gotchas (all found by actually running this on the real hardware)

- **Docker shutdown must use SIGINT, not SIGTERM.** `ros2 launch`'s graceful
  shutdown path is built around SIGINT (same as a foreground Ctrl+C).
  `docker-compose.ros.yml` sets `stop_signal: SIGINT` and the container
  command ends in `exec ros2 launch ...` (not plain `ros2 launch`) so it
  becomes PID 1 and actually receives the signal. Without both of these,
  `docker stop`/`down` hard-kills everything after a 10s timeout with zero
  node cleanup (cameras/Hailo left locked).
- **Every node's `main()` must guard `rclpy.shutdown()` with
  `if rclpy.ok():`.** rclpy's own SIGINT handler already shuts the context
  down; calling `rclpy.shutdown()` unconditionally afterward raises
  `RCLError: rcl_shutdown already called`, which crashes the node instead of
  exiting cleanly (and for `hailo_inference`, cascades into a HailoRT
  segfault during uncontrolled interpreter-exit teardown — see next point).
- **`hailo_platform`'s `VDevice` must be explicitly `.release()`d** in
  `destroy_node()` (after dropping `configured_model`/`infer_model`
  references), not left to the garbage collector — GC teardown order at
  interpreter exit can segfault HailoRT. Picamera2's own bundled Hailo
  helper (`picamera2/devices/hailo/hailo.py`) does the same thing; that file
  is the closest thing to official reference usage for this API and is
  worth checking before changing inference code.
- **`hailo_platform`'s newer `InferModel`/`Bindings` API has sharp edges**:
  `Bindings` is not a context manager (no `with ... as`), `run()` takes
  `timeout` not `timeout_ms`, and an NMS-postprocess output needs an
  explicit `bindings.output().set_buffer(np.empty(shape, dtype))` call
  *before* `run()` — the shape/dtype come from `infer_model.output().shape`
  / `.format.type`, not guessed. Omitting the output buffer raises
  `HAILO_INVALID_OPERATION`.
- **A HEF's actual output layout is a hardware fact, not an assumption** —
  check it with `hailortcli parse-hef <file>` before writing/trusting
  postprocessing code. The current model was compiled with on-chip NMS
  (`HAILO NMS BY CLASS`), so `_postprocess()` in `hailo_inference_node.py`
  decodes a list of 80 per-class arrays of `[ymin, xmin, ymax, xmax, score]`
  (normalized 0-1) — a HEF without on-chip NMS needs different decoding.
- **The CMA/DMA-buffer pool is only 64MB total** (`grep -i cma
  /proc/meminfo`). Two 1280x800 cameras + Hailo + the web stream running
  together leaves only a few MB free — `OSError: Cannot allocate memory` /
  `DMA_HEAP_IOCTL_ALLOC` failures on a camera are this, not a code bug. Fix:
  stop everything and restart cleanly (releases fragmented allocations); if
  it recurs, the real fix is raising `cma=` in `/boot/firmware/config.txt`.
- **`ros2 topic echo`/`hz` are broken in this image** (`No module named
  'psutil'` — `python3-psutil` isn't apt-installed in `Dockerfile.ros`). Use
  a throwaway rclpy subscriber script instead, or fix by adding the package.
- **The USB webcam (Logitech BRIO) is `camera2`, addressed by its
  `/dev/v4l/by-id/...-video-index0` path.** The BRIO exposes four V4L2
  nodes: index0 = colour, index2 = IR camera (GREY 340x340), index1/3 =
  metadata — only index0 is the picture you want, and `/dev/videoN` numbers
  can change between boots. The by-id symlinks only exist inside the
  container because `docker-compose.ros.yml` bind-mounts `/dev/v4l`, and a
  device plugged in *after* the container starts is invisible to it — plug
  the webcam in first, then `up`. `usb_camera:=false` on the launch line
  skips it. In low light the BRIO's auto-exposure drops its frame rate to
  ~7.5Hz on its own (`exposure_dynamic_framerate`); that's the camera, not
  the pipeline. It's currently on a USB 2.0 port (480M); a USB 3.0 port
  allows the higher modes.
- **Both CSI cameras are physically mounted upside down.** `record_dual_camera.py`
  output needs a 180° rotation to read right-side up — `gray_to_color.py`
  defaults `--rotation` to 180 for this reason.
- **The OV9281 sensors have no color filter array** — there is no real color
  data anywhere in this pipeline, ever. `cv2.cvtColor(..., GRAY2BGR)` only
  replicates luma into equal B=G=R (still renders as gray); `gray_to_color.py`'s
  colormap output is a cosmetic false-color remap for visual inspection, not
  recovered color.
- **`.hef` files must live under `ros2_ws/`** (the only bind-mounted path)
  and be referenced by their *container-side* path (`/ros2_ws/models/...`),
  not the host path — `docker-compose.ros.yml`'s `HEF_PATH` env var and the
  `hef_path` launch arg both default to
  `/ros2_ws/models/yolov8m.hef`.
- Detection log lines land in `ros2_ws/logs/detections.log`, written as
  root from inside the container — readable from the host, but `sudo` is
  needed to delete/move it.
