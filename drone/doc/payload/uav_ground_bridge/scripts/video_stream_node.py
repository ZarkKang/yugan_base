#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import subprocess

import rospy


class VideoStreamNode:
    def __init__(self):
        self.ffmpeg_path = rospy.get_param("~ffmpeg_path", "/usr/bin/ffmpeg")
        self.video_device = rospy.get_param("~video_device", "/dev/video0")
        self.target_host = rospy.get_param("~target_host", "192.168.1.100")
        self.target_port = int(rospy.get_param("~target_port", 5600))
        self.width = int(rospy.get_param("~width", 640))
        self.height = int(rospy.get_param("~height", 480))
        self.fps = int(rospy.get_param("~fps", 30))
        self.bitrate = rospy.get_param("~bitrate", "1500k")
        self.process = None

    def start(self):
        if not os.path.exists(self.ffmpeg_path):
            rospy.logerr("[uav_video_stream] ffmpeg not found: %s", self.ffmpeg_path)
            return False
        if not os.path.exists(self.video_device):
            rospy.logerr("[uav_video_stream] video device not found: %s", self.video_device)
            return False

        target = "udp://%s:%d?pkt_size=1316" % (self.target_host, self.target_port)
        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "v4l2",
            "-framerate",
            str(self.fps),
            "-video_size",
            "%dx%d" % (self.width, self.height),
            "-i",
            self.video_device,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-b:v",
            str(self.bitrate),
            "-f",
            "mpegts",
            target,
        ]

        rospy.logwarn("[uav_video_stream] starting ffmpeg: %s", " ".join(command))
        self.process = subprocess.Popen(command, preexec_fn=os.setsid)
        rospy.on_shutdown(self.stop)
        return True

    def stop(self):
        if self.process is None or self.process.poll() is not None:
            return
        rospy.logwarn("[uav_video_stream] stopping ffmpeg")
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGINT)
            self.process.wait(timeout=3.0)
        except Exception:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except Exception:
                pass

    def spin(self):
        rate = rospy.Rate(1)
        while not rospy.is_shutdown():
            if self.process is not None and self.process.poll() is not None:
                rospy.logerr("[uav_video_stream] ffmpeg exited with code %s", self.process.returncode)
                rospy.signal_shutdown("ffmpeg exited")
                break
            rate.sleep()


def main():
    rospy.init_node("uav_video_stream")
    node = VideoStreamNode()
    if node.start():
        node.spin()
    else:
        rospy.signal_shutdown("video stream setup failed")


if __name__ == "__main__":
    main()
