import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    config_dir = os.path.join(get_package_share_directory("bos_cameras"), "config")
    cameras_yaml = os.path.join(config_dir, "cameras.yaml")
    hailo_yaml = os.path.join(config_dir, "hailo_accelerator.yaml")

    # Read the configured default straight from hailo_accelerator.yaml so
    # there's one source of truth for it, while `hef_path:=` (used by
    # docker-compose.ros.yml's HEF_PATH env var) can still override it at
    # launch time without editing the file.
    with open(hailo_yaml) as f:
        hailo_defaults = yaml.safe_load(f)["camera0_inference"]["ros__parameters"]

    hef_path_arg = DeclareLaunchArgument(
        "hef_path",
        default_value=hailo_defaults["hef_path"],
        description="Path to the compiled .hef model for the Hailo8 inference node "
        "(overrides the value in config/hailo_accelerator.yaml)",
    )
    web_viewer_port_arg = DeclareLaunchArgument(
        "web_viewer_port",
        default_value="8080",
        description="HTTP port for the web_viewer MJPEG stream",
    )

    camera0 = Node(
        package="bos_cameras",
        executable="camera_publisher",
        name="camera0_publisher",
        parameters=[cameras_yaml],
        output="screen",
        emulate_tty=True,
    )
    camera1 = Node(
        package="bos_cameras",
        executable="camera_publisher",
        name="camera1_publisher",
        parameters=[cameras_yaml],
        output="screen",
        emulate_tty=True,
    )
    inference0 = Node(
        package="bos_cameras",
        executable="hailo_inference",
        name="camera0_inference",
        # hef_path is layered on top of the YAML file so the launch
        # argument (and docker-compose's HEF_PATH env var) can still
        # override it.
        parameters=[hailo_yaml, {"hef_path": LaunchConfiguration("hef_path")}],
        output="screen",
        emulate_tty=True,
    )
    web_viewer = Node(
        package="bos_cameras",
        executable="web_viewer",
        name="camera0_web_viewer",
        parameters=[
            {
                "input_topic": "camera0/image_raw",
                "port": LaunchConfiguration("web_viewer_port"),
            }
        ],
        output="screen",
        emulate_tty=True,
    )

    return LaunchDescription([
        hef_path_arg, web_viewer_port_arg, camera0, camera1, inference0, web_viewer,
    ])
