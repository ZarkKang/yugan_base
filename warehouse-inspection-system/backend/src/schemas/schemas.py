"""
Pydantic schemas - API请求/响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class InspectionStatusEnum(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABNORMAL = "abnormal"


class TaskStatusEnum(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


# ========== 巡检记录 Schema ==========

class InspectionRecordBase(BaseModel):
    drone_id: int
    shelf_id: Optional[int] = None
    rfid_tag_id: Optional[int] = None
    qr_code_data: Optional[str] = None
    rfid_data: Optional[str] = None


class InspectionRecordCreate(InspectionRecordBase):
    record_code: str
    image_path: Optional[str] = None


class InspectionRecordUpdate(BaseModel):
    status: Optional[InspectionStatusEnum] = None
    qr_code_data: Optional[str] = None
    rfid_data: Optional[str] = None
    is_matched: Optional[bool] = None
    mismatch_reason: Optional[str] = None


class InspectionRecordResponse(InspectionRecordBase):
    id: int
    record_code: str
    status: InspectionStatusEnum
    image_path: Optional[str]
    is_matched: Optional[bool]
    mismatch_reason: Optional[str]
    inspection_time: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# ========== 无人机 Schema ==========

class DroneBase(BaseModel):
    drone_code: str
    drone_name: Optional[str] = None
    model: Optional[str] = None


class DroneCreate(DroneBase):
    pass


class DroneUpdate(BaseModel):
    drone_name: Optional[str] = None
    status: Optional[str] = None
    battery_level: Optional[float] = None
    last_position_x: Optional[float] = None
    last_position_y: Optional[float] = None
    last_position_z: Optional[float] = None


class DroneResponse(DroneBase):
    id: int
    status: str
    battery_level: float
    last_position_x: Optional[float]
    last_position_y: Optional[float]
    last_position_z: Optional[float]
    last_seen: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# ========== 货架 Schema ==========

class ShelfBase(BaseModel):
    shelf_code: str
    shelf_name: Optional[str] = None
    zone: Optional[str] = None


class ShelfCreate(ShelfBase):
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    position_z: Optional[float] = None
    rows: int = 1
    columns: int = 1
    levels: int = 1


class ShelfUpdate(BaseModel):
    shelf_name: Optional[str] = None
    zone: Optional[str] = None
    qr_code: Optional[str] = None
    status: Optional[str] = None


class ShelfResponse(ShelfBase):
    id: int
    position_x: Optional[float]
    position_y: Optional[float]
    position_z: Optional[float]
    qr_code: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ========== RFID标签 Schema ==========

class RFIDTagBase(BaseModel):
    tag_id: str
    tag_type: Optional[str] = None
    shelf_id: Optional[int] = None
    goods_name: Optional[str] = None


class RFIDTagCreate(RFIDTagBase):
    pass


class RFIDTagResponse(RFIDTagBase):
    id: int
    goods_quantity: int
    last_read_time: Optional[datetime]
    last_read_strength: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


# ========== 任务 Schema ==========

class TaskBase(BaseModel):
    task_code: str
    task_name: str
    task_type: str = "routine"


class TaskCreate(TaskBase):
    drone_id: Optional[int] = None
    target_shelves: Optional[List[int]] = None
    altitude: float = 5.0
    speed: float = 2.0


class TaskUpdate(BaseModel):
    status: Optional[TaskStatusEnum] = None
    drone_id: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class TaskResponse(TaskBase):
    id: int
    status: TaskStatusEnum
    drone_id: Optional[int]
    altitude: float
    speed: float
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    total_records: int
    abnormal_records: int
    created_at: datetime

    class Config:
        from_attributes = True


# ========== 数据接收 Schema ==========

class DataReceiveRequest(BaseModel):
    """数据接收请求"""
    drone_code: str
    data_type: str = Field(..., description="数据类型: sbus/rfid/qr_code/video/image")
    payload: str = Field(..., description="数据载荷")
    timestamp: Optional[datetime] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    position_z: Optional[float] = None
    metadata: Optional[dict] = Field(None, description="附加元数据: task_code, waypoint_id, event, video_stream, battery 等")


class DataReceiveResponse(BaseModel):
    """数据接收响应"""
    success: bool
    message: str
    record_id: Optional[int] = None


class QRCodeProcessRequest(BaseModel):
    """二维码处理请求"""
    image_path: Optional[str] = None
    image_base64: Optional[str] = None


class QRCodeProcessResponse(BaseModel):
    """二维码处理响应"""
    success: bool
    codes: List[str] = []


# ========== 通用响应 ==========

class APIResponse(BaseModel):
    success: bool = True
    message: str = "操作成功"
    data: Optional[dict] = None


class PaginatedResponse(BaseModel):
    success: bool = True
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: List[dict] = []


# ========== 认证 Schema ==========

class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class TokenData(BaseModel):
    """Token数据"""
    username: Optional[str] = None


class UserResponse(BaseModel):
    """用户响应"""
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """登录响应"""
    success: bool
    message: str
    access_token: str
    token_type: str = "bearer"
    user: Optional[UserResponse] = None


# ========== 无人机整合 Schema ==========

class DroneDeviceRegisterRequest(BaseModel):
    """设备注册请求"""
    drone_id: int
    device_name: str
    ip_address: str = "192.168.1.201"
    port: int = 8080
    protocol: str = "HTTP"
    device_model: Optional[str] = None
    firmware_version: Optional[str] = None
    auth_type: str = "none"
    auth_credential: Optional[str] = None
    encryption_enabled: bool = False
    encryption_type: Optional[str] = None
    encryption_key: Optional[str] = None
    heartbeat_interval: int = 5


class DroneDeviceResponse(BaseModel):
    """设备响应"""
    id: int
    drone_id: int
    device_name: str
    device_model: Optional[str]
    firmware_version: Optional[str]
    ip_address: str
    port: int
    protocol: str
    auth_type: str
    encryption_enabled: bool
    encryption_type: Optional[str]
    status: str
    last_connected_at: Optional[datetime]
    heartbeat_interval: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class AutomatedTaskRequest(BaseModel):
    """自动化任务创建请求"""
    device_id: int
    task_name: str
    task_type: str = Field(..., description="video_capture/rfid_read/both")
    schedule_type: str = "interval"
    schedule_value: str = Field(..., description="秒数/cron/ISO时间")
    target_storage_path: str = "drone_data"
    video_duration: int = 30
    video_resolution: str = "1920x1080"
    rfid_read_duration: int = 10
    json_filename_pattern: str = "drone_{device_id}_{timestamp}.json"
    enabled: bool = True


class AutomatedTaskResponse(BaseModel):
    """自动化任务响应"""
    id: int
    device_id: int
    task_name: str
    task_type: str
    schedule_type: str
    schedule_value: str
    target_storage_path: str
    video_duration: int
    video_resolution: str
    rfid_read_duration: int
    json_filename_pattern: str
    enabled: bool
    last_run_at: Optional[datetime]
    last_run_status: Optional[str]
    next_run_at: Optional[datetime]
    run_count: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class NetworkVerifyResponse(BaseModel):
    """网络验证响应"""
    source_ip: str
    target_ip: str
    ping_success: bool
    ping_ms: Optional[float]
    packet_loss_percent: float
    stability: str
    open_ports: List[dict]
    summary: str


class CommunicationLogResponse(BaseModel):
    """通信日志响应"""
    id: int
    device_id: int
    log_type: str
    direction: str
    data_type: Optional[str]
    payload_summary: Optional[str]
    payload_size: Optional[int]
    status: str
    error_message: Optional[str]
    response_time_ms: Optional[int]
    source_ip: Optional[str]
    target_ip: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
