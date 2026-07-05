# 2026-07-06 REAL_DRONE_400 修改总结

## 本次修改目标

将无人机端与地面站端的数据传输逻辑整理为 5 条独立链路，避免旧版本中航点事件、心跳、RFID、货架信息混合处理，便于地面站分别接收、解析和调试。

本次修改已上传到无人机 NX：

- SSH 地址：`192.168.31.178`
- 用户：`nvidia`
- 工程目录：`/home/nvidia/Auto-planner/REAL_DRONE_400-main`

## 修改文件

### 1. 桥接主节点

路径：

```bash
/home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/scripts/uav_ground_bridge_node.py
```

主要修改：

- 重构地面站通讯逻辑。
- 新增货架坐标同步。
- 新增任务获取逻辑。
- 新增 `task_code` 保存逻辑。
- 新增任务航点文件生成逻辑。
- 新增航点到达独立上报逻辑。
- 新增最后航点完成后 RFID 统一上传逻辑。
- 移除旧的 `waypoint_event` 混合事件上报逻辑。

### 2. ROS 启动文件

路径：

```bash
/home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/launch/bridge.launch
```

主要修改：

- 新增 5 条通讯链路对应的参数。
- 新增任务文件路径参数。
- 移除旧的 `enable_waypoint_event`、`waypoint_event_url`、`waypoint_event_path` 参数。
- 保留 RFID、里程计、电池、视频推流等原有功能参数。

### 3. 无人机端启动脚本

路径：

```bash
/home/nvidia/4.sh
```

主要修改：

- 将默认通讯参数切换到新的 5 条接口。
- 保持里程计话题为：

```bash
/Odom_high_freq
```

- 保持里程计类型为：

```bash
nav_msgs/Odometry
```

- 保持视频推流参数不变。

## 备份文件

上传前已在无人机 NX 上创建备份：

```bash
/home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/scripts/uav_ground_bridge_node.py.bak.20260705_five_channel_transport
/home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/launch/bridge.launch.bak.20260705_five_channel_transport
/home/nvidia/4.sh.bak.20260705_five_channel_transport
```

## 当前 5 条传输链路

### 1. 货架坐标同步

用途：

将 `record_shelves.sh` 标定保存的货架编号和位置信息同步到地面站。

接口：

```http
POST /api/drones/{drone_id}/shelves/sync
```

发送内容：

```json
{
  "drone_code": "DRONE001",
  "coordinate_frame": "map",
  "shelves": [],
  "timestamp": 1783260000.0
}
```

说明：

- `shelves` 来自无人机端 `shelves.yaml`。
- `shelves.yaml` 由 `record_shelves.sh` 标定生成或更新。

### 2. 获取任务顺序和 task_code

用途：

无人机从地面站获取本次任务的货柜执行顺序，并保存 `task_code`。

接口：

```http
GET /api/drones/{drone_id}/tasks/available
```

无人机端处理结果：

- 读取地面站返回的货柜顺序。
- 根据本地 `shelves.yaml` 查找每个货柜坐标。
- 生成本次任务文件：

```bash
/home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/config/active_mission.yaml
/home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/config/generated/active_planner_waypoints.yaml
```

说明：

- `active_mission.yaml` 保存任务信息、`task_code` 和货柜顺序。
- `active_planner_waypoints.yaml` 保存 EGO-Planner 可读取的航点坐标。

### 3. 心跳信息上报

用途：

向地面站周期性发送无人机状态。

当前接口：

```http
POST /api/drones/{drone_id}/shelves/sync
```

发送内容只包含：

```json
{
  "drone_code": "DRONE001",
  "position": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "status": "running",
  "battery": 86.0,
  "timestamp": 1783260000.0
}
```

状态规则：

- 运行中：`running`
- 到达最后一个航点并完成任务：`completed`

注意：

当前心跳接口路径按本次需求配置为 `/api/drones/{drone_id}/shelves/sync`。如果地面站后端实际有单独的心跳接口，只需要修改 `/home/nvidia/4.sh` 中的 `heartbeat_path:=...`。

### 4. 航点到达指令上报

用途：

无人机每到达一个航点后，向地面站单独发送一条到达指令。

接口：

```http
POST /api/drones/{drone_id}/waypoints/{waypoint_id}/commands/arrive
```

发送内容只包含：

```json
{
  "drone_code": "DRONE001",
  "task_code": "TASK001",
  "command": "WAYPOINT_ARRIVED",
  "waypoint_id": "01-01",
  "waypoint_index": 1,
  "timestamp": 1783260000.0
}
```

说明：

- `waypoint_index` 从 `1` 开始计数。
- `waypoint_id` 对应货柜编号。
- `task_code` 来自地面站任务接口。

### 5. RFID 扫描结果上传

用途：

任务执行过程中累计 RFID 扫描结果，到最后一个航点完成时统一上传。

接口：

```http
POST /api/drones/{drone_id}/rfid/upload
```

发送内容只包含：

```json
{
  "data_type": "rfid",
  "payload": [],
  "timestamp": 1783260000.0
}
```

说明：

- RFID 不再混入心跳或航点到达信息。
- 只在最后一个航点完成时上传。

## 当前 ROS 参数验证结果

已在无人机 NX 上执行安全验证，不触发飞行、不启动真实任务：

```bash
python3 -m py_compile /home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/scripts/uav_ground_bridge_node.py
bash -n /home/nvidia/4.sh
roslaunch uav_ground_bridge bridge.launch enable_rfid_reader:=false enable_video_stream:=false --dump-params
```

关键参数结果：

```bash
/uav_ground_bridge/active_planner_waypoints_file: /home/nvidia/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/config/generated/active_planner_waypoints.yaml
/uav_ground_bridge/enable_shelves_sync: true
/uav_ground_bridge/enable_task_fetch: true
/uav_ground_bridge/heartbeat_path: /api/drones/{drone_id}/shelves/sync
/uav_ground_bridge/odom_topic: /Odom_high_freq
/uav_ground_bridge/odom_type: nav_msgs/Odometry
/uav_ground_bridge/rfid_upload_path: /api/drones/{drone_id}/rfid/upload
/uav_ground_bridge/shelves_sync_path: /api/drones/{drone_id}/shelves/sync
/uav_ground_bridge/tasks_available_path: /api/drones/{drone_id}/tasks/available
/uav_ground_bridge/waypoint_arrive_path: /api/drones/{drone_id}/waypoints/{waypoint_id}/commands/arrive
```

## 使用方式

### 1. 启动主飞行系统

```bash
cd ~
./3.sh
```

### 2. 启动地面站桥接、RFID、视频和任务通讯

```bash
cd ~
./4.sh
```

### 3. 查看桥接节点是否启动

```bash
rosnode list | grep uav_ground_bridge
```

### 4. 查看关键参数

```bash
rosparam get /uav_ground_bridge/tasks_available_path
rosparam get /uav_ground_bridge/waypoint_arrive_path
rosparam get /uav_ground_bridge/rfid_upload_path
```

## 注意事项

- 地面站任务接口返回的货柜编号必须能在无人机端 `shelves.yaml` 中找到。
- 如果任务中包含不存在的货柜编号，无人机端不会生成有效航点。
- 心跳接口当前与货架同步接口路径相同，这是按本次需求配置的。
- 如果地面站后端要求心跳走独立接口，修改 `/home/nvidia/4.sh` 的 `heartbeat_path` 即可。
- 本次修改没有自动解锁、自动起飞或自动发布 `/traj_start_trigger`。

## 本次结论

本次已将无人机端地面站通讯整理为 5 条独立链路：

1. 货架坐标同步；
2. 任务顺序与 `task_code` 获取；
3. 心跳上报；
4. 航点到达指令上报；
5. RFID 最终上传。

代码已上传到无人机 NX，并完成语法检查和 ROS 参数展开验证。
