# delivery_bos_os

ROS2 setup for a Raspberry Pi 5 (8GB) with a Hailo8 AI accelerator and two
CSI-connected OV9281 (mono, global-shutter) cameras.

## Hardware

- Raspberry Pi 5, 8GB
- Hailo8 accelerator (PCIe/M.2 HAT), exposed at `/dev/hailo0`
- 2x OV9281 mono CSI cameras

## How it works

The host runs Raspberry Pi OS (a Debian trixie–based release). Two things
only make sense installed directly on the host, since they talk to kernel
drivers:

- **Hailo runtime** — `hailo-all` (apt), which owns the PCIe kernel driver
  and firmware. This is what makes `/dev/hailo0` exist.
- **Camera stack** — `python3-picamera2` / `python3-libcamera` (apt), tied to
  the host's specific libcamera build and kernel camera ISP driver.

ROS2 Jazzy has no apt binaries for Raspberry Pi OS/Debian (only Ubuntu), so
rather than build it from source on the host, it's built **once, inside a
Docker image** (`docker/Dockerfile.ros`):

- **Builder stage**: `debian:trixie-slim` + build tools. Checks out the
  official `ros2.repos` (Jazzy), strips packages not needed for a headless
  backend (rviz and the rest of the Qt/GUI stack, Gazebo vendor packages,
  Rust codegen support, demos/examples/tutorials — dropping these also
  sidesteps several packaging gaps between Ubuntu and Debian trixie),
  resolves remaining dependencies via `rosdep`, and `colcon build`s
  everything into `/opt/ros/jazzy`.
- **Final stage**: the *same* `debian:trixie-slim` base plus Raspberry Pi's
  own apt repo — deliberately not Ubuntu — so `hailort`/`python3-hailort`/
  `python3-picamera2`/`python3-libcamera` install as the exact same build
  the host's kernel driver and libcamera stack expect. Versions are pinned
  to whatever's on the host (see the comments in the Dockerfile) so the
  container and host are guaranteed protocol-compatible. The compiled ROS2
  install is copied in from the builder stage; `colcon` and a handful of
  runtime-only shared libraries are added since the final stage doesn't
  inherit anything from the builder's apt install.

At runtime, the container gets `--privileged` + `network_mode: host` (see
`docker/docker-compose.ros.yml`): `--privileged` because libcamera/picamera2
enumerate a shifting set of ~36 `/dev/video*`/`/dev/media*` nodes rather than
a fixed pair, and host networking because ROS2's DDS discovery (UDP
multicast) needs to reach nodes anywhere on the same `ROS_DOMAIN_ID` —
whether they're in this container, another container, or bare-metal on the
host — with no manual endpoint wiring.

`ros2_ws/` is bind-mounted into the container, so source edits made on the
host are immediately visible inside it — there's no "deploy" step for node
code; only `docker/Dockerfile.ros` changes require rebuilding the image.

## Components

```
docker/
  docker-compose.ros.yml   # container run config: devices, network, volumes
  Dockerfile.ros          # builds the ROS2 Jazzy image (see "How it works")
  ros_entrypoint.sh        # sources ROS2 + the workspace overlay, then execs
ros2_ws/
  src/bos_cameras/         # the one ROS2 package
    bos_cameras/
      camera_interface.py        # CameraInterface: capture()/close()
      picamera2_camera.py        # CSI camera implementation
      usb_camera.py              # USB (V4L2/UVC) webcam implementation
      camera_publisher_node.py   # camera -> sensor_msgs/Image (type chosen in cameras.yaml)
      ai_accelerator_interface.py  # AIAcceleratorInterface: process(image)/close()
      hailo_accelerator.py       # Hailo8 YOLOv8 implementation
      hailo_inference_node.py    # Hailo8 inference -> JSON detections (std_msgs/String)
      web_viewer_node.py         # image topic -> MJPEG stream over Flask
      image_utils.py             # shared sensor_msgs/Image <-> numpy helper
    config/
      cameras.yaml               # camera0/1 (CSI) + camera2 (USB webcam) params
      hailo_accelerator.yaml     # inference node params
    launch/
      cameras.launch.py    # camera publishers + Hailo inference + web viewer
requirements.txt            # pip deps for scripts/ only — see note below
scripts/
  record_dual_camera.py     # standalone dual-camera capture (no ROS2)
  gray_to_color.py          # re-encode a recording through false-color colormaps
```

**Note on `requirements.txt`**: `picamera2`, `rclpy`, and `hailo_platform`
are deliberately *not* listed there — they come from apt / the ROS2 image,
not pip, and installing them from PyPI would shadow versions built
specifically for this host/image.

**Note on `hailo_platform`**: the apt package is `python3-hailort`, but the
importable Python module is `hailo_platform`, not `hailort` — there is no
`import hailort`.

## Workflow

### Build the image

Only needed the first time, or after changing `docker/Dockerfile.ros`
(new apt package, base image bump, etc.) — not for ROS2 node code changes.
This compiles ROS2 Jazzy from source and takes roughly an hour:

```bash
docker compose -f docker/docker-compose.ros.yml build
```

### Iterate on a node

```bash
docker compose -f docker/docker-compose.ros.yml run --rm ros bash
# inside the container:
colcon build --symlink-install && source install/setup.sh
ros2 run bos_cameras camera_publisher   # or hailo_inference, web_viewer
```

`--symlink-install` means colcon links to the source files instead of
copying them, so editing a `.py` file on the host takes effect on the next
`ros2 run`/`ros2 launch` — no rebuild needed. Rebuild (`colcon build`) is
only required after adding a new file, a new `console_scripts` entry in
`setup.py`, or changing `package.xml`.

### Start the full stack

This is the one you want day-to-day — it runs `colcon build && ros2 launch
bos_cameras cameras.launch.py`: both CSI camera publishers, the USB webcam
publisher (`camera2`), the Hailo inference node, and the `web_viewer` MJPEG
stream. The webcam is optional — plug it in before `up`, or add
`usb_camera:=false` to the `ros2 launch` line in `docker-compose.ros.yml` to
start without it.

```bash
docker compose -f docker/docker-compose.ros.yml up -d
docker compose -f docker/docker-compose.ros.yml logs -f   # watch output live, Ctrl+C to detach
```

`-d` runs it detached (survives your shell disconnecting); drop it to run in
the foreground instead (Ctrl+C then stops it). To stop it cleanly (frees the
cameras and the Hailo device):

```bash
docker compose -f docker/docker-compose.ros.yml stop
```

The Hailo model defaults to `ros2_ws/models/yolov8m.hef` — drop a `.hef`
file there (see `ros2_ws/models/README.md`), or override with
`export HEF_PATH=/ros2_ws/models/<other>.hef` before `up`. Once running:

- Detections are logged to `ros2_ws/logs/detections.log`.
- The camera0 feed is viewable from any device on the network at
  `http://<this-pi's-lan-ip>:8080/`.

The compose file has no `restart:` policy yet, so it won't come back on its
own after a reboot or crash — add `restart: unless-stopped` when you want
that.

### Inspect a running graph

```bash
docker exec -it ros bash
source /opt/ros/jazzy/setup.sh && source /ros2_ws/install/setup.sh
ros2 topic list
ros2 topic echo /camera0/image_raw
ros2 node list
```
