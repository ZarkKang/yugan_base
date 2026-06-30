from fastapi import WebSocket, WebSocketDisconnect, Depends
from typing import Dict, List, Set
import json
from datetime import datetime
import uuid
import asyncio
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # 活跃连接: {client_id: WebSocket}
        self.active_connections: Dict[str, WebSocket] = {}
        # 频道订阅: {channel: {client_id}}
        self.channel_subscriptions: Dict[str, Set[str]] = {}
        # 客户端信息
        self.client_info: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str = None) -> str:
        """连接客户端"""
        if not client_id:
            client_id = str(uuid.uuid4())
        
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.client_info[client_id] = {
            'connected_at': datetime.now().isoformat(),
            'last_activity': datetime.now().isoformat()
        }
        
        logger.info(f"Client connected: {client_id}")
        return client_id
    
    def disconnect(self, client_id: str):
        """断开连接"""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        
        if client_id in self.client_info:
            del self.client_info[client_id]
        
        # 从所有频道中移除
        for channel in list(self.channel_subscriptions.keys()):
            if client_id in self.channel_subscriptions[channel]:
                self.channel_subscriptions[channel].remove(client_id)
        
        logger.info(f"Client disconnected: {client_id}")
    
    async def send_personal_message(self, message: dict, client_id: str):
        """发送个人消息"""
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {client_id}: {e}")
                self.disconnect(client_id)
    
    async def broadcast(self, message: dict, channel: str = None):
        """广播消息"""
        if channel:
            # 发送到指定频道
            if channel in self.channel_subscriptions:
                for client_id in self.channel_subscriptions[channel]:
                    await self.send_personal_message(message, client_id)
        else:
            # 发送给所有人
            for client_id in list(self.active_connections.keys()):
                await self.send_personal_message(message, client_id)
    
    def subscribe(self, client_id: str, channel: str):
        """订阅频道"""
        if channel not in self.channel_subscriptions:
            self.channel_subscriptions[channel] = set()
        
        self.channel_subscriptions[channel].add(client_id)
        logger.info(f"Client {client_id} subscribed to {channel}")
    
    def unsubscribe(self, client_id: str, channel: str):
        """取消订阅"""
        if channel in self.channel_subscriptions:
            if client_id in self.channel_subscriptions[channel]:
                self.channel_subscriptions[channel].remove(client_id)
                logger.info(f"Client {client_id} unsubscribed from {channel}")
    
    def get_active_clients(self) -> List[dict]:
        """获取活跃客户端列表"""
        return [
            {
                'client_id': cid,
                'info': self.client_info[cid]
            }
            for cid in self.active_connections.keys()
        ]


# 全局连接管理器
manager = ConnectionManager()


class VideoStreamHandler:
    """视频流处理器"""
    
    def __init__(self):
        self.active_streams: Dict[str, dict] = {}
        self.frame_buffer: Dict[str, List[bytes]] = {}
    
    async def start_stream(self, stream_id: str, source: str, client_id: str):
        """开始视频流"""
        self.active_streams[stream_id] = {
            'source': source,
            'started_by': client_id,
            'started_at': datetime.now().isoformat(),
            'viewers': set()
        }
        
        # 广播流开始消息
        await manager.broadcast({
            'type': 'stream_started',
            'stream_id': stream_id,
            'source': source
        }, 'video_streams')
    
    async def send_frame(self, stream_id: str, frame_data: bytes):
        """发送视频帧"""
        if stream_id not in self.active_streams:
            return
        
        # 广播帧数据
        await manager.broadcast({
            'type': 'video_frame',
            'stream_id': stream_id,
            'frame': frame_data.hex(),
            'timestamp': datetime.now().isoformat()
        }, f'stream_{stream_id}')
    
    async def stop_stream(self, stream_id: str):
        """停止视频流"""
        if stream_id in self.active_streams:
            del self.active_streams[stream_id]
        
        await manager.broadcast({
            'type': 'stream_stopped',
            'stream_id': stream_id
        }, 'video_streams')


video_handler = VideoStreamHandler()


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket端点"""
    client_id = None
    
    try:
        client_id = await manager.connect(websocket)
        
        # 发送欢迎消息
        await manager.send_personal_message({
            'type': 'connected',
            'client_id': client_id,
            'timestamp': datetime.now().isoformat()
        }, client_id)
        
        # 消息处理循环
        while True:
            try:
                data = await websocket.receive_json()
                await handle_websocket_message(websocket, client_id, data)
            except json.JSONDecodeError:
                # 尝试接收文本
                text_data = await websocket.receive_text()
                await handle_websocket_text(websocket, client_id, text_data)
            except Exception as e:
                logger.error(f"WebSocket error for {client_id}: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected")
    finally:
        if client_id:
            manager.disconnect(client_id)


async def handle_websocket_message(websocket: WebSocket, client_id: str, data: dict):
    """处理WebSocket消息"""
    message_type = data.get('type')
    
    if message_type == 'ping':
        # 心跳
        await manager.send_personal_message({
            'type': 'pong',
            'timestamp': datetime.now().isoformat()
        }, client_id)
    
    elif message_type == 'subscribe':
        # 订阅频道
        channel = data.get('channel')
        if channel:
            manager.subscribe(client_id, channel)
            await manager.send_personal_message({
                'type': 'subscribed',
                'channel': channel
            }, client_id)
    
    elif message_type == 'unsubscribe':
        # 取消订阅
        channel = data.get('channel')
        if channel:
            manager.unsubscribe(client_id, channel)
    
    elif message_type == 'start_stream':
        # 开始视频流
        stream_id = data.get('stream_id') or str(uuid.uuid4())
        source = data.get('source')
        await video_handler.start_stream(stream_id, source, client_id)
        manager.subscribe(client_id, f'stream_{stream_id}')
    
    elif message_type == 'stop_stream':
        # 停止视频流
        stream_id = data.get('stream_id')
        await video_handler.stop_stream(stream_id)
    
    elif message_type == 'video_frame':
        # 视频帧数据
        stream_id = data.get('stream_id')
        frame_hex = data.get('frame')
        if stream_id and frame_hex:
            frame_data = bytes.fromhex(frame_hex)
            await video_handler.send_frame(stream_id, frame_data)
    
    # 更新客户端最后活跃时间
    if client_id in manager.client_info:
        manager.client_info[client_id]['last_activity'] = datetime.now().isoformat()


async def handle_websocket_text(websocket: WebSocket, client_id: str, text: str):
    """处理文本消息（备用）"""
    # 简单回显
    await manager.send_personal_message({
        'type': 'echo',
        'text': text,
        'timestamp': datetime.now().isoformat()
    }, client_id)


async def broadcast_system_notification(message: str, level: str = 'info'):
    """广播系统通知"""
    await manager.broadcast({
        'type': 'notification',
        'level': level,
        'message': message,
        'timestamp': datetime.now().isoformat()
    })
