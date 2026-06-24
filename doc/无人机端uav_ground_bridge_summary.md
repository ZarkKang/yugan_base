# uav_ground_bridge 功能与使用说明

## 1. 包位置

`uav_ground_bridge` 是新增在无人机 NX 端的独立 ROS 包，路径为：

```bash
~/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge
```

该包只负责无人机数据桥接和可选视频推流，不控制飞行，不修改 PX4、MAVROS、EGO-Planner、FAST-LIO2、px4ctrl、traj_server 等原飞控逻辑。

## 2. 主要功能

### 2.1 心跳上传

节点会按固定周期向地面站发送无人机心跳。

默认周期：

```text
5 秒
```

接口：

```text
POST {ground_url}/api/v1/drones/{drone_code}/heartbeat
```

默认地面站地址：

```text
http://192.168.1.100:8001
```

心跳内容示例：

```json
{
  "drone_code": "DRONE001",
  "status": "idle",
  "battery": -1,
  "position": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "timestamp": 1781874689.7
}
```

如果地面站不可达，节点不会崩溃，只会输出 warning，并把失败请求写入本地日志。

### 2.2 RFID 数据接收

节点订阅 RFID 话题：

```text
/rfid/tags
```

消息类型：

```text
std_msgs/String
```

消息内容为 JSON，例如：

```json
{
  "epc": "E280F3372000F0001A72CDCE",
  "rssi_dbm": -62,
  "pc": "3400",
  "crc": "DEE0",
  "stamp": 1781874689.7
}
```

节点会解析并缓存最近一段时间读到的 RFID 标签。

默认缓存窗口：

```text
5 秒
```

### 2.3 航点到达监控

节点可读取固定航点文件：

```bash
src/payload/uav_ground_bridge/config/waypoints.yaml
```

示例：

```yaml
task_code: TASK001
waypoints:
  - id: 1
    x: 0.0
    y: 0.0
    z: 1.0
    dwell_time: 5.0
```

节点会根据当前位置判断是否到达当前航点。

默认到达条件：

```text
arrival_radius = 0.3 m
arrival_hold_time = 2.0 s
```

开启航点监控：

```bash
enable_waypoint_monitor:=true
```

关闭航点监控：

```bash
enable_waypoint_monitor:=false
```

### 2.4 位置信息读取

默认订阅：

```text
/Odometry
```

默认消息类型：

```text
nav_msgs/Odometry
```

如果没有 `/Odometry`，可以改用 MAVROS 位姿：

```bash
odom_topic:=/mavros/local_position/pose
odom_type:=geometry_msgs/PoseStamped
```

如果没有定位数据，默认位置为：

```json
{"x": 0.0, "y": 0.0, "z": 0.0}
```

### 2.5 电池信息读取

可选订阅：

```text
/mavros/battery
```

消息类型：

```text
sensor_msgs/BatteryState
```

如果没有电池话题，默认：

```text
battery = -1
```

### 2.6 航点 RFID 扫描与结果上传

当无人机到达航点后，节点会进入 RFID 扫描阶段。

扫描时长由航点文件中的 `dwell_time` 决定：

```yaml
dwell_time: 5.0
```

扫描结束后，节点会汇总这段时间内读到的 RFID 标签，并上传到地面站。

接口：

```text
POST {ground_url}/api/v1/gateway/receive
```

上传内容示例：

```json
{
  "drone_code": "DRONE001",
  "data_type": "rfid",
  "payload": "[{\"epc\":\"E280F3372000F0001A72CDCE\",\"rssi_dbm\":-62}]",
  "position_x": 0.0,
  "position_y": 0.0,
  "position_z": 0.0,
  "metadata": {
    "task_code": "TASK001",
    "waypoint_id": 1,
    "event": "waypoint_completed",
    "video_stream": "udp://@:5600",
    "battery": -1,
    "timestamp": 1781874689.7
  }
}
```

## 3. 网络失败日志

所有 HTTP 上传失败的数据都会写入本地 JSONL 日志，方便后续人工补传。

日志路径：

```bash
src/payload/uav_ground_bridge/logs/uav_ground_bridge_failed.jsonl
```

查看日志：

```bash
tail -20 src/payload/uav_ground_bridge/logs/uav_ground_bridge_failed.jsonl
```

## 4. 可选视频推流

该包支持可选视频推流。默认不启动视频流：

```xml
<arg name="enable_video_stream" default="false"/>
```

启动时加：

```bash
enable_video_stream:=true
```

即可启动 `uav_video_stream` 节点，并调用 NX 上的：

```bash
/usr/bin/ffmpeg
```

默认摄像头：

```text
/dev/video0
```

默认推送目标：

```text
192.168.1.100:5600
```

实际推流形式：

```text
H.264 -> MPEG-TS -> UDP
```

地面电脑 VLC 打开：

```text
udp://@:5600
```

## 5. 视频推流参数

可在启动时修改：

```bash
video_device:=/dev/video0
video_target_host:=192.168.1.100
video_target_port:=5600
video_width:=640
video_height:=480
video_fps:=30
video_bitrate:=1500k
```

例如推到另一台地面电脑：

```bash
video_target_host:=192.168.1.50
video_target_port:=5600
```

地面电脑对应打开：

```text
udp://@:5600
```

## 6. 完整启动命令

正式启动桥接、航点监控、RFID、心跳和视频推流：

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
source /opt/ros/noetic/setup.bash
source devel/setup.bash

roslaunch uav_ground_bridge bridge.launch \
ground_url:=http://192.168.1.100:8001 \
drone_code:=DRONE001 \
rfid_topic:=/rfid/tags \
odom_topic:=/Odometry \
enable_waypoint_monitor:=true \
enable_video_stream:=true \
video_device:=/dev/video0 \
video_target_host:=192.168.1.100 \
video_target_port:=5600
```

## 7. 无 `/Odometry` 时的测试启动命令

如果当前没有 `/Odometry`，可以先关闭航点监控，只测试心跳、RFID 和视频：

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
source /opt/ros/noetic/setup.bash
source devel/setup.bash

roslaunch uav_ground_bridge bridge.launch \
ground_url:=http://192.168.1.100:8001 \
drone_code:=DRONE001 \
enable_waypoint_monitor:=false \
enable_video_stream:=true \
video_device:=/dev/video0 \
video_target_host:=192.168.1.100 \
video_target_port:=5600
```

## 8. 常用验证命令

确认 ROS 包存在：

```bash
rospack find uav_ground_bridge
```

确认 RFID：

```bash
rostopic echo -n 5 /rfid/tags
```

确认视频设备：

```bash
ls -l /dev/video*
```

确认 ffmpeg：

```bash
which ffmpeg
```

确认推流进程：

```bash
pgrep -a ffmpeg
```

确认到地面电脑的路由：

```bash
ip route get 192.168.1.100
```

期望类似：

```text
192.168.1.100 dev eth1 src 192.168.1.201
```

确认失败日志：

```bash
tail -20 src/payload/uav_ground_bridge/logs/uav_ground_bridge_failed.jsonl
```

## 9. 当前已验证状态

当前已经验证：

```text
1. uav_ground_bridge 能被 rospack 找到
2. catkin_make --pkg uav_ground_bridge 构建通过
3. python3 requests/yaml 依赖正常
4. /usr/bin/ffmpeg 存在
5. /dev/video0 和 /dev/video1 存在
6. enable_video_stream:=true 时会启动 uav_video_stream
7. ffmpeg 会向 udp://192.168.1.100:5600 推流
8. 地面站 8001 不在线时，心跳失败只 warning，不崩溃
9. HTTP 失败会写入本地 JSONL 日志
10. 路由走 eth1，源地址为 192.168.1.201
```

## 10. 注意事项

`uav_ground_bridge` 不控制飞行，只做数据桥接。

它不会修改：

```text
PX4
MAVROS
EGO-Planner
FAST-LIO2
px4ctrl
traj_server
```

视频流和心跳是两条不同链路：

```text
视频流: UDP 5600
心跳/RFID 上传: HTTP 8001
```

所以即使地面站 `8001` 没开，视频流仍然可以通过 VLC 在 `udp://@:5600` 查看。
