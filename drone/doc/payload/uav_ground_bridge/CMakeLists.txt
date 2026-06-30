cmake_minimum_required(VERSION 3.0.2)
project(uav_ground_bridge)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  geometry_msgs
  nav_msgs
  sensor_msgs
)

catkin_package()

catkin_install_python(PROGRAMS
  scripts/uav_ground_bridge_node.py
  scripts/video_stream_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
