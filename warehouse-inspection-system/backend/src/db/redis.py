"""
数据库模块 - Redis缓存
"""
import redis
import json
from typing import Optional, Any, Union
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis客户端封装"""

    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.REDIS_URL
        self._client: Optional[redis.Redis] = None

    def connect(self) -> bool:
        """建立Redis连接"""
        try:
            self._client = redis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=5
            )
            self._client.ping()
            logger.info("Redis连接成功")
            return True
        except redis.ConnectionError as e:
            logger.error(f"Redis连接失败: {e}")
            return False

    def disconnect(self) -> None:
        """断开Redis连接"""
        if self._client:
            self._client.close()
            self._client = None

    def get(self, key: str) -> Optional[str]:
        """获取值"""
        if self._client:
            return self._client.get(key)
        return None

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """设置值"""
        if self._client:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            return self._client.set(key, value, ex=ex)
        return False

    def delete(self, key: str) -> bool:
        """删除键"""
        if self._client:
            return bool(self._client.delete(key))
        return False

    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if self._client:
            return bool(self._client.exists(key))
        return False

    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """递增"""
        if self._client:
            return self._client.incrby(key, amount)
        return None

    def get_json(self, key: str) -> Optional[Any]:
        """获取JSON值"""
        value = self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    def set_json(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """设置JSON值"""
        return self.set(key, json.dumps(value), ex=ex)

    @property
    def client(self) -> Optional[redis.Redis]:
        return self._client


class RedisStream:
    """Redis Stream消息队列封装"""

    def __init__(self, client: redis.Redis):
        self.client = client

    def xadd(self, stream: str, data: dict, maxlen: Optional[int] = None) -> Optional[str]:
        """
        添加消息到流

        Args:
            stream: 流名称
            data: 消息数据字典
            maxlen: 最大消息数量

        Returns:
            消息ID
        """
        try:
            if maxlen:
                return self.client.xadd(stream, data, maxlen=maxlen, approximate=True)
            return self.client.xadd(stream, data)
        except redis.RedisError as e:
            logger.error(f"XADD失败: {e}")
            return None

    def xread(self, streams: dict,
              count: Optional[int] = None,
              block: Optional[int] = None) -> list:
        """
        读取流消息

        Args:
            streams: {stream_name: last_id}
            count: 每次读取的最大消息数
            block: 阻塞等待毫秒数

        Returns:
            消息列表
        """
        try:
            return self.client.xread(streams, count=count, block=block)
        except redis.RedisError as e:
            logger.error(f"XREAD失败: {e}")
            return []

    def xrange(self, stream: str,
               start: str = "-",
               end: str = "+",
               count: Optional[int] = None) -> list:
        """范围读取流消息"""
        try:
            return self.client.xrange(stream, start, end, count=count)
        except redis.RedisError as e:
            logger.error(f"XRANGE失败: {e}")
            return []

    def xack(self, stream: str, group: str, *ids: str) -> int:
        """确认消息已处理"""
        try:
            return self.client.xack(stream, group, *ids)
        except redis.RedisError as e:
            logger.error(f"XACK失败: {e}")
            return 0

    def create_group(self, stream: str, group: str, id: str = "0") -> bool:
        """创建消费者组"""
        try:
            self.client.xgroup_create(stream, group, id=id, mkstream=True)
            return True
        except redis.ResponseError:
            # 组已存在
            return True
        except redis.RedisError as e:
            logger.error(f"创建消费者组失败: {e}")
            return False


redis_client = RedisClient()


def get_redis() -> RedisClient:
    return redis_client
