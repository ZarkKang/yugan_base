# uav_ground_bridge

ROS Noetic bridge for sending UAV heartbeat, RFID tags, and waypoint completion results to a ground station.

## Build

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
source /opt/ros/noetic/setup.bash
sudo apt install -y python3-requests python3-yaml
catkin_make --pkg uav_ground_bridge -DCMAKE_BUILD_TYPE=Release
source devel/setup.bash
```

## Run

```bash
roslaunch uav_ground_bridge bridge.launch ground_url:=http://192.168.1.100:8001 drone_code:=DRONE001
```

If `/Odometry` is not available and MAVROS local pose is available instead:

```bash
roslaunch uav_ground_bridge bridge.launch odom_topic:=/mavros/local_position/pose odom_type:=geometry_msgs/PoseStamped
```

For heartbeat-only testing without waypoint arrival monitoring:

```bash
roslaunch uav_ground_bridge bridge.launch ground_url:=http://192.168.1.100:8001 drone_code:=DRONE001 enable_waypoint_monitor:=false
```

To start the bridge and push the camera stream from NX to the ground computer:

```bash
roslaunch uav_ground_bridge bridge.launch \
  ground_url:=http://192.168.1.100:8001 \
  drone_code:=DRONE001 \
  enable_video_stream:=true \
  video_device:=/dev/video0 \
  video_target_host:=192.168.1.100 \
  video_target_port:=5600
```

On the ground computer, open VLC with:

```text
udp://@:5600
```

## Test requirements

* `/rfid/tags` from `rfid_reader`, message type `std_msgs/String`, JSON payload.
* `/Odometry` by default, or set `odom_topic:=/mavros/local_position/pose odom_type:=geometry_msgs/PoseStamped`.
* Optional `/mavros/battery`; if unavailable, heartbeat uses `battery=-1`.
* Optional `/dev/video0` and `ffmpeg` when `enable_video_stream:=true`.
* Ground station reachable from NX via LQ3:
  `curl http://192.168.1.100:8001/health`

## Ground station interfaces

Heartbeat:

```text
POST {ground_url}/api/v1/drones/{drone_code}/heartbeat
```

Waypoint RFID result:

```text
POST {ground_url}/api/v1/gateway/receive
```

If the ground station returns 404 or a format error, keep this bridge package unchanged and adapt the ground station to the payload documented in the task. Failed HTTP posts are logged locally for manual replay.

## Notes

This package does not control PX4, MAVROS, EGO-Planner, px4ctrl, or traj_server. Video streaming is optional and only starts when `enable_video_stream:=true`.

Failed HTTP posts are logged to:

```text
src/payload/uav_ground_bridge/logs/uav_ground_bridge_failed.jsonl
```
