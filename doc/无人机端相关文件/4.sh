#!/bin/bash
# ============================================================
# 域感智能 - 无人机端启动脚本
# 运行位置: 无人机 NX 板 (192.168.1.201)
# 连接目标: 地面基站 (192.168.1.100)
# ============================================================

# ══════════ 配置区 (根据实际情况修改) ══════════
# 基站IP地址 (地面站)
BASE_STATION_IP="192.168.1.100"
# 无人机编号 (必须与基站前端注册的编号一致)
DRONE_CODE="DRONE001"
# 基站端口 (直连后端=8001, 走API网关=8080)
BASE_PORT="8001"
# 视频推流端口
VIDEO_PORT="5600"
# ══════════ 配置区结束 ══════════

cd ~/Auto-planner/REAL_DRONE_400-main
source /opt/ros/noetic/setup.bash
source devel/setup.bash

roslaunch uav_ground_bridge bridge.launch \
  ground_url:=http://${BASE_STATION_IP}:${BASE_PORT} \
  drone_code:=${DRONE_CODE} \
  rfid_topic:=/rfid/tags \
  odom_topic:=/Odom_high_freq \
  odom_type:=nav_msgs/Odometry \
  enable_waypoint_monitor:=true \
  enable_video_stream:=true \
  video_device:=/dev/video0 \
  video_target_host:=${BASE_STATION_IP} \
  video_target_port:=${VIDEO_PORT}

# ============================================================
# 接口说明:
#   心跳上报: POST {ground_url}/api/v1/drones/{DRONE_CODE}/heartbeat  (每5秒)
#   RFID上传: POST {ground_url}/api/v1/gateway/receive                 (航点到达时)
#   设备上报: POST {ground_url}/api/v1/drone-integration/device/report  (启动1次)
#   视频推流: UDP  {BASE_STATION_IP}:{VIDEO_PORT}                       (持续)
#
# 使用前检查:
#   1. 无人机IP设置为 192.168.1.201/24 (与基站同一网段)
#   2. ping通基站: ping -c 3 ${BASE_STATION_IP}
#   3. 基站已启动且已注册编号为 ${DRONE_CODE} 的无人机
#   4. 如走API网关, 将 BASE_PORT 改为 8080
# ============================================================
