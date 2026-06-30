# 2026-06-27 REAL_DRONE_400 修改总结

## 一、总体目标

今天主要完成了无人机 NX 端的“货架标定 + 本地任务生成 + 任务模式启动”闭环。

核心目标是：

- 保留原有 `3.sh`、`4.sh` 默认流程不变；
- 新增长期货架库 `shelves.yaml`；
- 新增本地任务接收脚本，根据货架编号生成本次任务；
- 新增任务航点导出脚本，将任务转换为 EGO-Planner mode4 航点格式；
- 新增 `3_active.sh`，让无人机任务模式读取本次任务生成的航点，而不是默认 `points.yaml`；
- 保留 RFID、心跳、视频、HTTP 上报等原有桥接逻辑。

## 二、新增和修改的文件

### 1. `~/Auto-planner/REAL_DRONE_400-main/3_active.sh`

新增任务模式启动脚本。

作用：

- 参考原 `3.sh` 启动流程；
- 启动 `roscore`、MAVROS、Livox MID360、Fast-LIO、EGO-Planner、px4ctrl；
- 启动 EGO-Planner 时指定本次任务航点文件：

```bash
$HOME/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/config/generated/active_planner_waypoints.yaml
```

关键命令：

```bash
roslaunch ego_planner single_run_in_exp.launch \
  mode4_points_file:="$ACTIVE_WAYPOINTS"
```

安全设计：

- 不修改 `3.sh`；
- 不修改 `4.sh`；
- 启动前检查核心节点是否已运行；
- 如果检测到 `3.sh`、MAVROS、Fast-LIO、EGO-Planner、px4ctrl 等已运行，会拒绝启动；
- 不主动发布 `/traj_start_trigger`；
- 不主动解锁；
- 不主动起飞。

验证结果：

- `bash -n 3_active.sh` 通过；
- 安全测试中 EGO-Planner 成功加载任务航点；
- EGO-Planner 保持在 `WAIT_TARGET` 状态，等待触发。

## 三、货架库与标定功能

### 1. `src/payload/uav_ground_bridge/config/shelves.yaml`

新增长期货架库。

示例内容：

```yaml
version: 1
coordinate_frame: "camera_init"
shelves:
  - shelf_id: "A01"
    shelf_name: "Area A shelf 01"
    position:
      x: 0.0
      y: 0.0
      z: 0.8
    yaw_rad: 0.0
    arrival_radius_m: 0.30
    dwell_time_s: 5.0
```

说明：

- `shelves.yaml` 是长期货架库；
- 日常任务不会覆盖它；
- 保存的是无人机安全悬停扫描点，不是货架实体中心点；
- 坐标来自 Fast-LIO 本地坐标系。

### 2. `src/payload/uav_ground_bridge/scripts/shelf_waypoint_recorder.py`

新增货架标定节点。

功能：

- 默认订阅 `/Odom_high_freq`；
- 显示当前 `frame_id`、`x/y/z`、`yaw`、定位更新时间；
- 支持终端命令：

```text
show
add
list
delete <shelf_id>
save
quit
```

标定时：

- 至少采样 40 帧或约 1 秒；
- 计算 `x/y/z/yaw` 平均值；
- 检查位置标准差；
- 标准差过大时拒绝保存；
- 使用临时文件 + 原子替换保存，降低异常中断损坏配置的风险。

### 3. `~/Auto-planner/REAL_DRONE_400-main/record_shelves.sh`

新增独立货架标定启动脚本。

作用：

- 启动标定所需的最小定位链路：
  - `roscore`
  - Livox MID360
  - Fast-LIO
  - `shelf_waypoint_recorder.py`
- 不启动 EGO-Planner 自动航点执行；
- 不启动 px4ctrl；
- 不启动 RFID 巡检状态机；
- 不启动视频流；
- 不启动地面站桥接上传。

使用：

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
./record_shelves.sh
```

## 四、本地任务生成

### 1. `src/payload/uav_ground_bridge/scripts/apply_mission_task.py`

新增本地任务接收脚本。

输入任务 JSON 示例：

```json
{
  "task_id": "TASK-20260627-001",
  "drone_code": "DRONE001",
  "shelf_ids": ["A01", "A03", "B02"]
}
```

作用：

- 读取 `shelves.yaml`；
- 根据 `shelf_ids` 顺序查找货架坐标；
- 生成本次任务文件：

```bash
src/payload/uav_ground_bridge/config/active_mission.yaml
```

校验规则：

- `task_id` 不能为空；
- `drone_code` 不能为空；
- `shelf_ids` 不能为空；
- `shelf_ids` 不能重复；
- 每个 `shelf_id` 必须存在于 `shelves.yaml`；
- `coordinate_frame` 必须存在；
- 如果当前任务标记为运行中，不允许直接覆盖。

生成任务命令：

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
source /opt/ros/noetic/setup.bash
source devel/setup.bash

rosrun uav_ground_bridge apply_mission_task.py --task-file /tmp/task.json
```

dry-run：

```bash
rosrun uav_ground_bridge apply_mission_task.py --task-file /tmp/task.json --dry-run
```

### 2. `src/payload/uav_ground_bridge/config/active_mission.yaml`

测试生成的当前任务文件。

内容包含：

- `task_id`
- `drone_code`
- `status`
- `coordinate_frame`
- `generated_at`
- 按顺序排列的货架列表
- 每个货架的坐标、yaw、到达半径、停留时间

## 五、任务航点导出

### 1. `src/payload/uav_ground_bridge/scripts/export_active_mission_to_planner.py`

新增任务航点导出脚本。

作用：

- 读取 `active_mission.yaml`；
- 按任务顺序提取货架坐标；
- 生成 EGO-Planner mode4 格式航点文件：

```bash
src/payload/uav_ground_bridge/config/generated/active_planner_waypoints.yaml
```

生成格式：

```yaml
mode: 4
points:
  - [x, y, z, yaw, time]
```

使用：

```bash
rosrun uav_ground_bridge export_active_mission_to_planner.py
```

dry-run：

```bash
rosrun uav_ground_bridge export_active_mission_to_planner.py --dry-run
```

### 2. `src/payload/uav_ground_bridge/config/generated/active_planner_waypoints.yaml`

测试生成的任务航点文件。

当前测试任务 `A01 -> A03 -> B02` 生成内容：

```yaml
mode: 4
source:
  task_id: TASK-20260627-001
  drone_code: DRONE001
  coordinate_frame: camera_init
points:
  - [0.0, 0.0, 0.8, 0.0, 5.0]
  - [1.0, 0.0, 0.8, 0.0, 5.0]
  - [1.0, 1.0, 0.8, 1.57, 5.0]
```

## 六、EGO-Planner 航点链路验证

### 1. 默认 `3.sh` 读取的航点

最后一次验证确认：

原 `3.sh` 默认读取：

```bash
src/user_command/multipoint/config/points.yaml
```

运行时加载到：

```bash
/mode4/points
```

默认内容：

```yaml
- [0.0, 0.0, 1.0, 0.0, 2.0]
- [1.0, 0.0, 1.0, 0.0, 2.0]
- [1.0, 1.0, 1.0, 1.57, 2.0]
```

结论：

- `points.yaml` 已经真实接入 EGO-Planner 默认航点链路；
- `active_planner_waypoints.yaml` 在修改前只是导出文件，不会被默认 `3.sh` 读取。

### 2. 新 `3_active.sh` 读取的航点

安全测试确认：

```bash
rosparam get /mode4/points
```

输出为：

```yaml
- [0.0, 0.0, 0.8, 0.0, 5.0]
- [1.0, 0.0, 0.8, 0.0, 5.0]
- [1.0, 1.0, 0.8, 1.57, 5.0]
```

并且脚本输出：

```text
Verified: /mode4/points matches active_planner_waypoints.yaml.
EGO-Planner is running and using: .../active_planner_waypoints.yaml
No /traj_start_trigger was published by this script.
```

## 七、修改过的安装配置

### `src/payload/uav_ground_bridge/CMakeLists.txt`

新增安装以下 Python 脚本：

```cmake
scripts/shelf_waypoint_recorder.py
scripts/apply_mission_task.py
scripts/export_active_mission_to_planner.py
```

作用：

- 让这些脚本可以通过 `rosrun uav_ground_bridge ...` 执行。

## 八、验证记录

已执行：

```bash
catkin_make
python3 -m py_compile ...
bash -n record_shelves.sh
bash -n 3_active.sh
rosrun uav_ground_bridge apply_mission_task.py --task-file /tmp/task_ok.json --dry-run
rosrun uav_ground_bridge apply_mission_task.py --task-file /tmp/task_ok.json
rosrun uav_ground_bridge export_active_mission_to_planner.py --dry-run
rosrun uav_ground_bridge export_active_mission_to_planner.py
```

异常任务验证：

- 不存在的货架编号：拒绝；
- 重复货架编号：拒绝；
- 空任务：拒绝。

`3_active.sh` 安全测试结果：

- MAVROS 启动成功；
- Livox MID360 启动成功；
- Fast-LIO 启动成功；
- EGO-Planner 启动成功；
- `/mode4/points` 成功读取 `active_planner_waypoints.yaml`；
- EGO-Planner 保持 `WAIT_TARGET`；
- 脚本没有主动发布 `/traj_start_trigger`；
- 测试结束后无核心进程残留。

## 九、完整使用流程

### 1. 标定货架

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
./record_shelves.sh
```

交互命令：

```text
show
add
list
delete A01
save
quit
```

### 2. 查看货架库

```bash
cat ~/Auto-planner/REAL_DRONE_400-main/src/payload/uav_ground_bridge/config/shelves.yaml
```

### 3. 准备任务 JSON

```bash
cat > /tmp/task.json <<'EOF'
{"task_id":"TASK-20260627-001","drone_code":"DRONE001","shelf_ids":["A01","A03","B02"]}
EOF
```

### 4. 生成本次任务

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
source /opt/ros/noetic/setup.bash
source devel/setup.bash

rosrun uav_ground_bridge apply_mission_task.py --task-file /tmp/task.json
```

### 5. 导出 EGO-Planner 航点

```bash
rosrun uav_ground_bridge export_active_mission_to_planner.py
```

### 6. 启动任务模式

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
./3_active.sh
```

### 7. 验证任务航点是否生效

```bash
rosparam get /mode4/points
```

应看到 `active_planner_waypoints.yaml` 中的航点。

## 十、仍然只是预留的部分

以下内容今天只做了无人机端接口和文件闭环，尚未实现完整网络下发：

- 地面站 HTTP 任务下发服务；
- 地面站网页任务选择；
- 地面站直接调用 `apply_mission_task(task_data)`；
- 任务执行状态回传与任务取消/替换机制。

当前已经预留的接口是：

```python
apply_mission_task(task_data)
```

未来地面站收到 JSON 后，可以直接调用该函数生成本次任务文件。

## 十一、重要限制

Fast-LIO 当前使用本地坐标系。货架标定和后续巡检必须尽量满足：

- 从相同初始位置启动；
- 初始朝向尽量一致；
- Livox/Fast-LIO 初始化环境一致；
- 不要假设已经实现跨重启、跨场地的全局重定位。

目前没有实现全局重定位或地图重定位，因此 `shelves.yaml` 中坐标的可靠性依赖启动条件一致性。
