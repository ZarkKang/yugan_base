#!/bin/bash -l
set -e

# �ͷ�����ͷ
pkill -9 ffplay 2>/dev/null || true
sudo fuser -k /dev/video0 2>/dev/null || true

# -----------------------------
# Step 0: Source all ROS workspaces
# -----------------------------
source /opt/ros/noetic/setup.bash
source /home/nvidia/livox_ws/devel/setup.bash
source /home/nvidia/Auto-planner/REAL_DRONE_400-main/devel/setup.bash
export ROS_PACKAGE_PATH="/home/nvidia/Auto-planner/REAL_DRONE_400-main/src:/home/nvidia/livox_ws/src:${ROS_PACKAGE_PATH}"
export CMAKE_PREFIX_PATH="/home/nvidia/Auto-planner/REAL_DRONE_400-main/devel:/home/nvidia/livox_ws/devel:${CMAKE_PREFIX_PATH}"
export PATH="/home/nvidia/Auto-planner/REAL_DRONE_400-main/devel/bin:/home/nvidia/livox_ws/devel/bin:${PATH}"
export LD_LIBRARY_PATH="/home/nvidia/Auto-planner/REAL_DRONE_400-main/devel/lib:/home/nvidia/livox_ws/devel/lib:${LD_LIBRARY_PATH}"

# -----------------------------
# Helper functions
# -----------------------------
wait_for_topic() {
    local topic_name=$1
    local timeout_sec=$2
    local start_time=$(date +%s)

    echo "Waiting for topic: $topic_name ..."
    while true; do
        if rostopic list 2>/dev/null | grep -q "^${topic_name}$"; then
            echo "Topic ready: $topic_name"
            return 0
        fi
        local now=$(date +%s)
        if [ $((now - start_time)) -ge "$timeout_sec" ]; then
            echo "Timeout waiting for topic: $topic_name"
            return 1
        fi
        sleep 0.2
    done
}

wait_for_rosservice() {
    local srv_name=$1
    local timeout_sec=$2
    local start_time=$(date +%s)

    echo "Waiting for service: $srv_name ..."
    while true; do
        if rosservice list 2>/dev/null | grep -q "^${srv_name}$"; then
            echo "Service ready: $srv_name"
            return 0
        fi
        local now=$(date +%s)
        if [ $((now - start_time)) -ge "$timeout_sec" ]; then
            echo "Timeout waiting for service: $srv_name"
            return 1
        fi
        sleep 0.2
    done
}

wait_for_roscore() {
    echo "Waiting for roscore ..."
    until rostopic list >/dev/null 2>&1; do
        sleep 0.2
    done
    echo "roscore is ready"
}

launch_bg() {
    echo "[START] $*"
    "$@" &
}

# -----------------------------
# Cleanup on exit
# -----------------------------
cleanup() {
    echo "Stopping all child processes..."
    pkill -P $$
}
trap cleanup EXIT

# -----------------------------
# Step 1: Start roscore if not running
# -----------------------------
if ! rostopic list >/dev/null 2>&1; then
    roscore &
    sleep 1
    wait_for_roscore
else
    echo "roscore already running"
fi

# -----------------------------
# Step 2: Set permission for /dev/ttyACM0
# -----------------------------
sudo chmod 777 /dev/ttyACM0

# Livox MID360 is configured to send data to 192.168.2.50 on the direct
# Ethernet interface. This address is stored in NetworkManager's eth0 profile.
if ! ip -4 addr show dev eth0 | grep -q '192.168.2.50/24'; then
    echo "Livox network address 192.168.2.50/24 is missing on eth0."
    exit 1
fi

# -----------------------------
# Step 3: Parallel start MAVROS + Livox + RViz
# -----------------------------
launch_bg roslaunch mavros px4.launch
launch_bg roslaunch livox_ros_driver2 msg_MID360.launch
launch_bg roslaunch ego_planner rviz.launch

# -----------------------------
# Step 4: Wait MAVROS ready, then send MAVLink commands
# -----------------------------
wait_for_topic "/mavros/state" 15
wait_for_rosservice "/mavros/cmd/command" 15
rosrun mavros mavcmd long 511 105 5000 0 0 0 0 0
sleep 0.3
rosrun mavros mavcmd long 511 31 5000 0 0 0 0 0
sleep 0.3

# -----------------------------
# Step 5: Wait Livox ready, then start Fast-LIO
# -----------------------------
wait_for_topic "/livox/lidar" 15
launch_bg roslaunch fast_lio mapping_mid360.launch rviz:=false
#launch_bg roslaunch faster_lio mapping_mid360.launch rviz:=false

#launch_bg roslaunch ~/Desktop/2REAL_DRONE_400/src/realflight_modules/ekf_pose/launch/ekf_lidar.launch

# -----------------------------
# Step 6: Wait odometry ready, then start Ego Planner
# -----------------------------
if ! wait_for_topic "/Odometry" 20; then
    wait_for_topic "/Odom_high_freq" 20
fi

launch_bg roslaunch ego_planner single_run_in_exp.launch
# -----------------------------
# Step 7: Start PX4 controller
# -----------------------------
launch_bg roslaunch px4ctrl run_ctrl.launch

echo "All processes started successfully!"

# Keep script alive so child processes stay attached
wait
