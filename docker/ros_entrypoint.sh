#!/bin/bash
set -e
# Debian's colcon doesn't ship the bash-specific shell-hook extension, so
# only setup.sh (POSIX) gets generated, not setup.bash — sourcing it from
# bash works fine (env vars only, no completion hooks needed here).
source "/opt/ros/${ROS_DISTRO}/setup.sh"
if [ -f /ros2_ws/install/setup.sh ]; then
    source /ros2_ws/install/setup.sh
fi
exec "$@"
