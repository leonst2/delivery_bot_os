from glob import glob

from setuptools import find_packages, setup

package_name = "bos_cameras"

setup(
    name=package_name,
    version="0.0.1",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Leon Stiffel",
    maintainer_email="leonstiffel@gmail.com",
    description="Dual OV9281 CSI camera publishers and Hailo8 inference node",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "camera_publisher = bos_cameras.camera_publisher_node:main",
            "hailo_inference = bos_cameras.hailo_inference_node:main",
            "web_viewer = bos_cameras.web_viewer_node:main",
        ],
    },
)
