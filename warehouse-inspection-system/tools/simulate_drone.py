#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟无人机端通信程序
=====================

功能：
  1. 自动生成测试二维码图像（用于上传测试）
  2. 模拟完整巡检流程：
     - 心跳上报（间隔5秒）
     - 获取可执行任务
     - 接收任务
     - 获取航点列表
     - 循环上传图像（航点 → 拍摄 → 上传 → 轮询识别结果 → 上报进度）
     - 标记任务完成
     - 查看报告

用法：
  python simulate_drone.py [选项]

选项：
  --host HOST          基站地址 (默认: 127.0.0.1)
  --port PORT          基站端口 (默认: 8000)
  --drone DRONE_CODE   无人机编号 (默认: DRONE001)
  --task TASK_CODE     任务编号 (默认: 自动获取第一个可用任务)
  --auto               全自动模式：创建任务+航点+执行+生成报告 (默认: False)
  --waypoints N        自动创建航点的数量 (默认: 3)
  --gen-qr N           生成 N 个含二维码的测试图像到 test_images/ 目录
  --step-by-step       逐步模式：每个步骤等待回车 (默认: False)
  --help               显示帮助

示例:
  # 基础测试：自动获取并执行已有任务
  python simulate_drone.py

  # 指定基站地址和无人机
  python simulate_drone.py --host 192.168.1.200 --drone DRONE002

  # 生成测试图像后手动测试
  python simulate_drone.py --gen-qr 5

  # 全自动：创建任务→执行→报告
  python simulate_drone.py --auto --waypoints 3

  # 逐步模式（每步等待回车）
  python simulate_drone.py --step-by-step
"""

import sys
import os
import time
import json
import uuid
import hashlib
import argparse
import base64
import io
import threading
from datetime import datetime
from pathlib import Path

# ============================================================
# 依赖检查
# ============================================================
MISSING = []

try:
    import requests
except ImportError:
    MISSING.append("requests")

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    MISSING.append("Pillow (用于生成测试图像)")

try:
    import qrcode as pyqrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

if MISSING:
    print(f"[!] 缺少依赖: {', '.join(MISSING)}")
    print(f"    安装: pip install {' '.join(MISSING)}")
    if "Pillow" in MISSING:
        print("    或:   pip install Pillow qrcode[pil]  (推荐)")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================

class Colors:
    """ANSI 颜色"""
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


class SimDroneTest:
    """模拟无人机"""

    def __init__(self, host="127.0.0.1", port=8000, drone_code="DRONE001",
                 task_code=None, auto=False, waypoints=3, step_by_step=False):
        self.base_url = f"http://{host}:{port}"
        self.api_prefix = "/api/v1"
        self.drone_code = drone_code
        self.task_code = task_code
        self.auto = auto
        self.waypoints_n = waypoints
        self.step_by_step = step_by_step

        self.session = requests.Session()
        self.session.timeout = 15
        self.task_started = False
        self.images_uploaded = 0
        self.images_recognized = 0
        self.heartbeat_running = False
        self._hb_thread = None

    # ── 工具 ────────────────────────────────────
    def _url(self, path: str) -> str:
        """构造完整 API URL"""
        return f"{self.base_url}{self.api_prefix}{path}"

    def _ok(self, label: str):
        print(f"  {Colors.GREEN}✓{Colors.RESET} {label}")

    def _fail(self, label: str):
        print(f"  {Colors.RED}✗{Colors.RESET} {label}")

    def _info(self, label: str):
        print(f"  {Colors.CYAN}→{Colors.RESET} {label}")

    def _warn(self, label: str):
        print(f"  {Colors.YELLOW}⚠{Colors.RESET} {label}")

    def _section(self, title: str):
        print(f"\n{Colors.BOLD}{Colors.HEADER}{'─' * 55}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.HEADER}  {title}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.HEADER}{'─' * 55}{Colors.RESET}")

    def _wait(self, msg="按回车继续..."):
        if self.step_by_step:
            input(f"\n{Colors.DIM}{msg}{Colors.RESET}")

    def _get(self, path, **kwargs):
        """GET 请求"""
        try:
            r = self.session.get(self._url(path), **kwargs)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            self._fail(f"无法连接基站: {self.base_url}")
            return None
        except requests.exceptions.Timeout:
            self._fail(f"请求超时: {path}")
            return None
        except Exception as e:
            self._fail(f"GET {path} 失败: {e}")
            return None

    def _post(self, path, **kwargs):
        """POST 请求"""
        try:
            r = self.session.post(self._url(path), **kwargs)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            self._fail(f"无法连接基站: {self.base_url}")
            return None
        except Exception as e:
            self._fail(f"POST {path} 失败: {e}")
            return None

    # ── 1. 健康检查 ─────────────────────────────
    def check_health(self):
        self._section("1. 检查基站连通性")
        self._info(f"目标: {self.base_url}")

        # health端点在根路径，不走 /api/v1 前缀
        try:
            r = self.session.get(f"{self.base_url}/health", timeout=10)
            result = r.json() if r.status_code == 200 else None
        except Exception as e:
            self._fail(f"GET /health 失败: {e}")
            return False

        if result and result.get("status") == "healthy":
            self._ok(f"基站运行正常")
            if "database" in result:
                self._info(f"数据库: {result.get('database')}")
            if "redis" in result:
                self._info(f"Redis: {result.get('redis')}")
            return True
        else:
            self._fail(f"基站不可用: {result}")
            return False

    # ── 2. 心跳 ─────────────────────────────────
    def start_heartbeat(self):
        """启动后台心跳线程"""
        def _hb():
            self.heartbeat_running = True
            count = 0
            while self.heartbeat_running:
                time.sleep(5)
                count += 1
                r = self._post(f"/drones/{self.drone_code}/heartbeat", json={
                    "status": "flying" if self.task_started else "idle",
                    "battery": max(10, 100 - count * 2),
                    "position": {"x": count * 1.0, "y": 0.0, "z": 5.0},
                })
                if r and r.get("success"):
                    if count <= 2 or count % 6 == 0:
                        self._info(f"心跳 #{count}: OK")
                else:
                    self._warn(f"心跳 #{count}: 失败")

        self._section("2. 启动心跳上报")
        self._hb_thread = threading.Thread(target=_hb, daemon=True)
        self._hb_thread.start()
        self._ok("心跳线程已启动（间隔 5 秒）")
        time.sleep(1)

    def stop_heartbeat(self):
        self.heartbeat_running = False

    # ── 3. 获取任务 ─────────────────────────────
    def fetch_tasks(self):
        self._section("3. 获取可用任务")
        self._info(f"无人机: {self.drone_code}")

        result = self._get(f"/drones/{self.drone_code}/tasks/available")
        if not result or not result.get("success"):
            self._fail("获取任务列表失败")
            return None

        items = result.get("data", {}).get("items", [])
        if not items:
            self._warn("无可用任务，将尝试自动创建")
            if self.auto:
                return self._auto_create_task()
            return None

        print(f"  找到 {len(items)} 个可用任务:")
        for t in items:
            status_icon = "✓" if t.get("status") == "created" else "○"
            print(f"    {status_icon} {t.get('task_code')} - {t.get('task_name')} "
                  f"(航点: {t.get('total_waypoints', '?')})")

        # 选择任务
        if self.task_code:
            for t in items:
                if t.get("task_code") == self.task_code:
                    self._ok(f"使用指定任务: {self.task_code}")
                    return t
            self._fail(f"指定任务 {self.task_code} 不在可用列表中")
            return None

        chosen = items[0]
        self.task_code = chosen.get("task_code")
        self._ok(f"自动选择任务: {self.task_code} - {chosen.get('task_name')}")
        return chosen

    # ── 4. 接受任务 ─────────────────────────────
    def accept_task(self):
        self._section("4. 接收任务")
        result = self._post(f"/drones/{self.drone_code}/tasks/{self.task_code}/accept")
        if result and result.get("success"):
            self._ok(f"任务 {self.task_code} 已接收，状态: running")
            self.task_started = True
            return True
        self._fail(f"接收任务失败: {result}")
        return False

    # ── 5. 获取航点 ─────────────────────────────
    def fetch_waypoints(self):
        self._section("5. 获取航点列表")
        result = self._get(f"/inspection/tasks/{self.task_code}/waypoints")
        if not result or not result.get("success"):
            self._fail("获取航点列表失败")
            return []

        waypoints = result.get("data", {}).get("items", [])
        if not waypoints:
            self._warn("任务无航点，将尝试自动创建")
            if self.auto:
                self._auto_create_waypoints()
                return self.fetch_waypoints()
            return []

        print(f"  共 {len(waypoints)} 个航点:")
        for wp in waypoints:
            p = wp.get("position", {})
            sku = wp.get("expected_sku") or "无预期SKU"
            print(f"    • {wp.get('waypoint_id')}  "
                  f"({p.get('x',0):.1f}, {p.get('y',0):.1f}, {p.get('z',0):.1f})  "
                  f"预期SKU: {sku}  角度: {wp.get('camera_angle',45)}°")

        return waypoints

    # ── 6. 航点巡检循环 ─────────────────────────
    def execute_waypoints(self, waypoints):
        self._section("6. 执行巡检（航点循环）")

        captured_dirs = {}

        for idx, wp in enumerate(waypoints):
            wp_id = wp.get("waypoint_id")
            expected_sku = wp.get("expected_sku")
            position = wp.get("position", {})

            print(f"\n{Colors.BOLD}[航点 {idx+1}/{len(waypoints)}]{Colors.RESET} "
                  f"{wp_id}")

            # 6a. 模拟飞行到航点
            self._info(f"飞行到 ({position.get('x',0):.1f}, "
                       f"{position.get('y',0):.1f}, {position.get('z',0):.1f})")
            time.sleep(0.5)  # 模拟飞行时间

            # 6b. 采集和上传图像
            recognized = False
            max_retries = 3

            for capture_idx in range(max_retries):
                # 获取或生成测试图像
                img_path, img_suk = self._get_test_image(
                    wp_id, capture_idx, expected_sku, captured_dirs
                )
                if not img_path:
                    self._fail("无法获取测试图像")
                    break

                file_size = os.path.getsize(img_path)
                self._info(f"拍摄第 {capture_idx+1} 张: {os.path.basename(img_path)} "
                           f"({file_size/1024:.1f}KB)")

                # 上传图像
                self._info("上传中...")
                with open(img_path, "rb") as f:
                    upload_result = self._post(
                        "/images/upload",
                        files={"image": (os.path.basename(img_path), f, "image/jpeg")},
                        data={
                            "drone_code": self.drone_code,
                            "task_code": self.task_code,
                            "waypoint_id": wp_id,
                            "position_x": position.get("x", 0),
                            "position_y": position.get("y", 0),
                            "position_z": position.get("z", 0),
                            "camera_angle": wp.get("camera_angle", 45),
                            "capture_index": capture_idx,
                        }
                    )

                if not upload_result or not upload_result.get("success"):
                    self._fail("上传失败")
                    time.sleep(1)
                    continue

                image_id = upload_result["data"]["image_id"]
                self._ok(f"已接收: {image_id}")

                # 轮询识别结果
                self._info("等待识别结果...")
                result = self._poll_recognition(image_id, timeout=15, interval=1.5)

                if not result:
                    self._warn("轮询超时，继续下一张")
                    time.sleep(0.5)
                    continue

                if result.get("status") == "processed":
                    qr_data = result.get("qr_data")
                    confidence = result.get("confidence", 0)
                    inventory = result.get("inventory_status", "-")
                    quality = result.get("image_quality", 0)

                    if qr_data:
                        self.images_recognized += 1
                        self._ok(f"识别成功: SKU={qr_data} "
                                 f"(置信度={confidence:.2f}, "
                                 f"质量={quality:.1f}, "
                                 f"库存={inventory})")
                        recognized = True
                        break
                    else:
                        self._warn(f"未识别到二维码 (质量={quality:.1f}, {result.get('message')})")
                elif result.get("status") == "failed":
                    self._warn(f"识别失败: {result.get('message', '')}")
                else:
                    self._warn(f"未知状态: {result.get('status')}")

                time.sleep(0.3)

            self.images_uploaded += 1

            if not recognized:
                self._warn("该航点未成功识别")

            if wp.get("status") == "scanning":
                # 更新航点状态（可选）
                pass

            # 6c. 上报进度
            self._info("上报进度...")
            self._post(f"/inspection/tasks/{self.task_code}/progress", json={
                "scanned": idx + 1,
                "total": len(waypoints),
                "recognized": self.images_recognized,
                "current_waypoint": wp_id,
            })

            self._wait()
            time.sleep(0.5)

    # ── 7. 完成任务 ─────────────────────────────
    def complete_task(self, waypoints_count):
        self._section("7. 标记任务完成")
        result = self._post(f"/inspection/tasks/{self.task_code}/complete", json={
            "total_scanned": waypoints_count,
            "recognized": self.images_recognized,
        })
        if result and result.get("success"):
            self._ok(f"任务 {self.task_code} 已完成")
            self.task_started = False

            t = result.get("data", {})
            self._info(f"完成时间: {t.get('completed_at', '-')}")
            return True
        self._fail(f"完成任务失败: {result}")
        return False

    # ── 8. 查看报告 ─────────────────────────────
    def view_report(self):
        self._section("8. 查看盘点报告")

        # 生成报告
        self._info("生成报告...")
        r = self._post(f"/inspection/tasks/{self.task_code}/report")
        if not r or not r.get("success"):
            self._warn("报告生成可能已由任务完成时自动触发")

        # 获取任务详情（含报告信息）
        result = self._get(f"/inspection/tasks/{self.task_code}")
        if result and result.get("success"):
            t = result.get("data", {})
            print(f"\n{Colors.BOLD}任务摘要:{Colors.RESET}")
            print(f"  任务: {t.get('task_code')} - {t.get('task_name')}")
            print(f"  状态: {t.get('status')}")
            print(f"  总航点: {t.get('total_waypoints', 0)}")
            print(f"  已扫描: {t.get('scanned_waypoints', 0)}")
            print(f"  总图像: {t.get('total_images', 0)}")
            print(f"  已识别: {t.get('total_recognized', 0)}")
            print(f"  未识别: {t.get('total_failed', 0)}")
            print(f"  待处理: {t.get('pending_count', 0)}")

            # 查看任务图像列表
            img_result = self._get(f"/images/task/{self.task_code}")
            if img_result and img_result.get("success"):
                items = img_result.get("data", {}).get("items", [])
                if items:
                    print(f"\n{Colors.BOLD}图像识别详情:{Colors.RESET}")
                    for i, img in enumerate(items):
                        status_icon = {
                            "processed": "✓", "pending": "○",
                            "processing": "⟳", "failed": "✗"
                        }.get(img.get("status"), "?")
                        inv_status = img.get("inventory_status") or "-"
                        sku = img.get("qr_data") or "未识别"
                        conf = img.get("confidence") or 0
                        print(f"  {status_icon} [{i+1}] {img.get('waypoint_id','?')} "
                              f"SKU={sku} "
                              f"(置信={conf:.2f}) "
                              f"库存={inv_status} "
                              f"状态={img.get('status')}")

        # 尝试查找报告ID
        self._info("\n查找报告...")
        # 简单方式：导出（如果没有 report_id，说明自动生成还没完成或未生成）
        self._info("提示: 可在桌面应用中查看完整报告和证据图片")
        self._info(f"任务详情: GET {self._url(f'/inspection/tasks/{self.task_code}')}")
        self._info(f"任务图像: GET {self._url(f'/images/task/{self.task_code}')}")

    # ── 工具方法 ───────────────────────────────
    def _poll_recognition(self, image_id, timeout=15, interval=1.5):
        """轮询识别结果"""
        start = time.time()
        while time.time() - start < timeout:
            r = self._get(f"/images/{image_id}/result")
            if not r or not r.get("success"):
                return None
            data = r.get("data", {})
            if data.get("status") in ("processed", "failed"):
                return data
            time.sleep(interval)
        return None

    def _get_test_image(self, wp_id, capture_idx, expected_sku, cached_dirs):
        """获取或生成测试图像"""
        if expected_sku and expected_sku not in cached_dirs:
            # 生成一张含二维码的图像
            test_dir = Path("tools/test_images")
            test_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{expected_sku}.jpg"
            fpath = test_dir / fname
            if not fpath.exists():
                try:
                    _generate_qr_image(str(fpath), expected_sku, expected_sku)
                except Exception as e:
                    print(f"    [警告] 生成QR图像失败: {e}，使用占位图像")
                    return _create_placeholder(test_dir, wp_id, capture_idx), expected_sku
            cached_dirs[expected_sku] = str(fpath)
            return str(fpath), expected_sku

        if expected_sku:
            return cached_dirs.get(expected_sku), expected_sku

        # 无预期SKU: 使用占位图或用随机QR
        test_dir = Path("tools/test_images")
        test_dir.mkdir(parents=True, exist_ok=True)
        return _create_placeholder(test_dir, wp_id, capture_idx), None

    def _auto_create_task(self):
        """自动创建任务"""
        self._section("3a. 自动创建任务")
        task_code = f"TASK{datetime.utcnow().strftime('%m%d_%H%M%S')}"
        self.task_code = task_code

        r = self._post("/inspection/tasks", json={
            "task_code": task_code,
            "task_name": f"自动测试任务 {task_code}",
            "task_type": "routine",
            "altitude": 5.0,
            "speed": 2.0,
            "target_shelves": list(range(1, self.waypoints_n + 1)),
        })
        if r and r.get("success"):
            self._ok(f"任务已创建: {task_code}")
            self._auto_create_waypoints()
            return {"task_code": task_code, "task_name": f"自动测试任务 {task_code}", "total_waypoints": self.waypoints_n}
        self._fail("创建任务失败")
        return None

    def _auto_create_waypoints(self):
        """自动创建航点"""
        self._info(f"自动创建 {self.waypoints_n} 个航点...")

        # 预生成测试SKU和QR图像
        test_dir = Path("tools/test_images")
        test_dir.mkdir(parents=True, exist_ok=True)
        test_skus = [f"SKU-TEST{i:03d}" for i in range(1, self.waypoints_n + 1)]

        # 生成QR图像
        for sku in test_skus:
            fpath = test_dir / f"{sku}.jpg"
            if not fpath.exists():
                try:
                    _generate_qr_image(str(fpath), sku, sku)
                    self._info(f"生成测试图像: {sku}.jpg")
                except Exception as e:
                    self._warn(f"生成 {sku} 图像失败: {e}")
                    _create_placeholder(test_dir, sku, 0)

        wps = []
        for i, sku in enumerate(test_skus):
            wps.append({
                "position_x": i * 2.0 + 1.0,
                "position_y": 2.0,
                "position_z": 3.0,
                "expected_sku": sku,
                "expected_location": f"测试货架-{i+1:02d}",
                "camera_angle": 45.0,
                "sort_order": i + 1,
            })

        r = self._post(f"/inspection/tasks/{self.task_code}/waypoints", json={
            "waypoints": wps
        })
        if r and r.get("success"):
            self._ok(f"已创建 {len(wps)} 个航点")
        else:
            self._fail("创建航点失败")


# ============================================================
# 图像生成
# ============================================================

def _generate_qr_image(filepath: str, text: str, label: str = None):
    """生成含二维码的测试图像 (1920x1080)"""
    if HAS_QRCODE:
        qr = pyqrcode.QRCode(version=2, box_size=10, border=4)
        qr.add_data(text)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    else:
        qr_img = Image.new("RGB", (400, 400), "white")
        d = ImageDraw.Draw(qr_img)
        for x in range(0, 400, 20):
            for y in range(0, 400, 20):
                if (hash(f"{x},{y},{text}") % 3) == 0:
                    d.rectangle([x, y, x+18, y+18], fill="black")

    # 放到 1920x1080 画布中央偏左位置（模拟实际航拍画面）
    canvas = Image.new("RGB", (1920, 1080), color=(240, 240, 245))
    qr_scaled = qr_img.resize((500, 500), Image.LANCZOS)
    canvas.paste(qr_scaled, (300, 290))

    # 绑定画一些 "货架边缘" 线条（模拟真实场景）
    draw = ImageDraw.Draw(canvas)
    for y in range(0, 1080, 120):
        draw.line([(0, y), (1920, y)], fill=(200, 200, 210), width=2)
    for x in range(250, 900, 120):
        draw.line([(x, 0), (x, 1080)], fill=(210, 210, 220), width=1)

    # 添加标签
    if label:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), f"SKU: {label}", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((900, 800 - th), f"航点: {label}", fill=(80, 80, 80), font=font)
        draw.text((900, 840 - th), f"SKU: {label}", fill=(40, 40, 200), font=font)

    canvas.save(filepath, "JPEG", quality=85)


def _create_placeholder(test_dir: Path, identifier, index=0) -> str:
    """创建占位图像（无二维码但有标签）"""
    fpath = test_dir / f"placeholder_{identifier}_{index}.jpg"
    if fpath.exists():
        return str(fpath)

    canvas = Image.new("RGB", (1920, 1080), color=(230, 230, 240))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except:
        font = ImageFont.load_default()
    draw.text((800, 500), f"测试航点: {identifier}", fill=(100, 100, 100), font=font)
    draw.text((800, 550), "无二维码", fill=(200, 100, 100), font=font)
    canvas.save(str(fpath), "JPEG", quality=85)
    return str(fpath)


# ============================================================
# gen-qr 模式：生成测试二维码图像
# ============================================================

def generate_qr_images(count: int):
    """生成 N 个含二维码的测试图像"""
    test_dir = Path("tools/test_images")
    test_dir.mkdir(parents=True, exist_ok=True)

    print(f"{Colors.BOLD}生成 {count} 个测试图像到 {test_dir}/{Colors.RESET}\n")

    for i in range(1, count + 1):
        sku = f"SKU-TEST{i:03d}"
        fpath = test_dir / f"{sku}.jpg"
        _generate_qr_image(str(fpath), sku, sku)
        size = os.path.getsize(str(fpath))
        print(f"  {Colors.GREEN}✓{Colors.RESET} {sku}.jpg ({size/1024:.1f}KB)")

    print(f"\n{Colors.GREEN}已生成 {count} 个测试图像!{Colors.RESET}")
    print(f"可在测试时使用 --auto 自动创建任务并执行巡检。")


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="模拟无人机端通信程序",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python simulate_drone.py
  python simulate_drone.py --host 192.168.1.200 --drone DRONE002
  python simulate_drone.py --auto --waypoints 3
  python simulate_drone.py --gen-qr 5
  python simulate_drone.py --step-by-step
        """
    )
    parser.add_argument("--host", default="127.0.0.1", help="基站地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8001, help="基站端口 (默认: 8001)")
    parser.add_argument("--drone", default="DRONE001", help="无人机编号 (默认: DRONE001)")
    parser.add_argument("--task", default=None, help="指定任务编号 (默认: 自动选择)")
    parser.add_argument("--auto", action="store_true", help="全自动模式：创建任务+航点+执行")
    parser.add_argument("--waypoints", type=int, default=3, help="自动创建航点数量 (默认: 3)")
    parser.add_argument("--step-by-step", action="store_true", help="逐步模式")
    parser.add_argument("--gen-qr", type=int, default=0, help="生成测试二维码图像的数量")

    args = parser.parse_args()

    # gen-qr 模式
    if args.gen_qr > 0:
        generate_qr_images(args.gen_qr)
        return

    # 检查依赖
    if not HAS_PIL:
        print("[!] 缺少 Pillow 库，无法生成测试图像")
        print("    安装: pip install Pillow qrcode[pil]")
        return

    # 启动模拟
    drone = SimDroneTest(
        host=args.host,
        port=args.port,
        drone_code=args.drone,
        task_code=args.task,
        auto=args.auto,
        waypoints=args.waypoints,
        step_by_step=args.step_by_step,
    )

    print(f"\n{Colors.CYAN}{Colors.BOLD}"
          f"╔══════════════════════════════════════════════╗\n"
          f"║        无人机模拟通信程序 v1.0                 ║\n"
          f"║        基站: {args.host}:{args.port:<5}                       ║\n"
          f"╚══════════════════════════════════════════════╝"
          f"{Colors.RESET}")

    # 步骤 1: 健康检查
    if not drone.check_health():
        print(f"\n{Colors.RED}基站不可用，请先启动后端服务{Colors.RESET}")
        return
    drone._wait()

    # 步骤 2: 启动心跳
    drone.start_heartbeat()
    drone._wait()

    # 步骤 3: 获取任务
    task = drone.fetch_tasks()
    if not task:
        print(f"\n{Colors.RED}无可用任务，退出{Colors.RESET}")
        return
    drone._wait()

    # 步骤 4: 接收任务
    if not drone.accept_task():
        return
    drone._wait()

    # 步骤 5: 获取航点
    waypoints = drone.fetch_waypoints()
    if not waypoints:
        return
    drone._wait()

    # 步骤 6: 执行巡检
    drone.execute_waypoints(waypoints)

    # 步骤 7: 完成任务
    drone.complete_task(len(waypoints))
    drone._wait()

    # 步骤 8: 查看报告
    drone.view_report()

    # 停止心跳
    drone.stop_heartbeat()
    time.sleep(1)

    print(f"\n{Colors.GREEN}{Colors.BOLD}"
          f"╔══════════════════════════════════════════════╗\n"
          f"║        测试完成!                               ║\n"
          f"║        上传图像: {drone.images_uploaded:<3}                             ║\n"
          f"║        识别成功: {drone.images_recognized:<3}                             ║\n"
          f"╚══════════════════════════════════════════════╝"
          f"{Colors.RESET}")


if __name__ == "__main__":
    main()