# models

Drop compiled `.hef` files here (e.g. `yolov8n.hef`).

This folder lives under `ros2_ws/`, which is the only thing bind-mounted
into the ROS2 container (see `../../docker/docker-compose.ros.yml`), so
files placed here are visible inside the container at
`/ros2_ws/models/<file>`.

Point the inference node at one with the **container-side** path:

```bash
export HEF_PATH=/ros2_ws/models/yolov8n.hef
docker compose -f docker/docker-compose.ros.yml up
```
