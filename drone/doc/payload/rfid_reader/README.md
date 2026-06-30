# rfid_reader for E720 UHF RFID reader

Copy this folder into your catkin workspace, for example:

```bash
cd ~/Auto-planner/REAL_DRONE_400-main
mkdir -p src/payload
cp -r /path/to/rfid_reader src/payload/
source /opt/ros/noetic/setup.bash
catkin_make --pkg rfid_reader -DCMAKE_BUILD_TYPE=Release
source devel/setup.bash
roslaunch rfid_reader e720.launch port:=/dev/rfid_e720 power_dbm:=18
```

Published topics:

- `/rfid/tags`: `std_msgs/String`, JSON containing `epc`, `rssi_dbm`, `pc`, `crc`, `stamp`.
- `/rfid/raw_frames`: raw validated E720 frames for debugging.

Parameters:

- `~port`: default `/dev/rfid_e720`
- `~baud`: default `115200`
- `~power_dbm`: default `20`, clamped to 5-28
- `~inventory_count`: default `65535`
- `~auto_start`: default `true`
- `~dedup_seconds`: default `0.5`
