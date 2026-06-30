import uuid
import time
from datetime import datetime
from typing import Optional, Dict, List, Any
from contextvars import ContextVar
from functools import wraps
from fastapi import Request, Response
import logging
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# 上下文变量
trace_id_var: ContextVar[str] = ContextVar('trace_id', default='')


class TraceContext:
    """追踪上下文"""
    
    @staticmethod
    def get_trace_id() -> str:
        """获取当前追踪ID"""
        return trace_id_var.get()
    
    @staticmethod
    def set_trace_id(trace_id: str):
        """设置追踪ID"""
        trace_id_var.set(trace_id)
    
    @staticmethod
    def new_trace_id() -> str:
        """生成新的追踪ID"""
        return str(uuid.uuid4())


class Span:
    """追踪跨度"""
    
    def __init__(self, name: str, parent_id: str = None, trace_id: str = None):
        self.span_id = str(uuid.uuid4())
        self.trace_id = trace_id or TraceContext.new_trace_id()
        self.parent_id = parent_id
        self.name = name
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.duration: Optional[float] = None
        self.attributes: Dict[str, Any] = {}
        self.events: List[dict] = []
        self.status = 'ok'
    
    def start(self):
        """开始"""
        self.start_time = time.time()
    
    def end(self, status: str = 'ok'):
        """结束"""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.status = status
    
    def set_attribute(self, key: str, value: Any):
        """设置属性"""
        self.attributes[key] = value
    
    def add_event(self, name: str, attributes: Dict[str, Any] = None):
        """添加事件"""
        self.events.append({
            'name': name,
            'timestamp': time.time(),
            'attributes': attributes or {}
        })
    
    def to_dict(self) -> dict:
        return {
            'span_id': self.span_id,
            'trace_id': self.trace_id,
            'parent_id': self.parent_id,
            'name': self.name,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_ms': self.duration * 1000 if self.duration else None,
            'attributes': self.attributes,
            'events': self.events,
            'status': self.status
        }


class TracingService:
    """全链路追踪服务"""
    
    def __init__(self, log_dir: str = "./traces"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.trace_buffer: List[dict] = []
        self.max_buffer_size = 100
    
    def create_span(self, name: str, parent_id: str = None, trace_id: str = None) -> Span:
        """创建新跨度"""
        span = Span(name, parent_id, trace_id)
        if not trace_id:
            trace_id = span.trace_id
            TraceContext.set_trace_id(trace_id)
        return span
    
    def record_span(self, span: Span):
        """记录跨度"""
        self.trace_buffer.append(span.to_dict())
        
        if len(self.trace_buffer) >= self.max_buffer_size:
            self._flush_buffer()
    
    def _flush_buffer(self):
        """刷新缓冲区到文件"""
        if not self.trace_buffer:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = self.log_dir / f"trace_{timestamp}.jsonl"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            for trace in self.trace_buffer:
                f.write(json.dumps(trace, ensure_ascii=False) + '\n')
        
        self.trace_buffer = []
    
    def query_traces(self, filters: dict = None) -> List[dict]:
        """查询追踪记录"""
        results = []
        for log_file in sorted(self.log_dir.glob("trace_*.jsonl"), reverse=True):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            trace = json.loads(line)
                            if self._match_filter(trace, filters):
                                results.append(trace)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                pass
        
        return results
    
    def _match_filter(self, trace: dict, filters: dict) -> bool:
        """匹配过滤条件"""
        if not filters:
            return True
        
        for key, value in filters.items():
            if key in trace and trace[key] != value:
                return False
        
        return True
    
    def get_trace_details(self, trace_id: str) -> List[dict]:
        """获取追踪详情"""
        return self.query_traces({'trace_id': trace_id})


# 全局追踪服务
tracing_service = TracingService()


def trace(name: str):
    """追踪装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            span = tracing_service.create_span(name)
            try:
                span.start()
                result = await func(*args, **kwargs)
                span.end('ok')
                return result
            except Exception as e:
                span.end('error')
                span.set_attribute('error', str(e))
                raise
            finally:
                tracing_service.record_span(span)
        return wrapper
    return decorator


async def tracing_middleware(request: Request, call_next):
    """FastAPI追踪中间件"""
    # 获取或生成追踪ID
    trace_id = request.headers.get('X-Trace-ID') or TraceContext.new_trace_id()
    TraceContext.set_trace_id(trace_id)
    
    # 创建HTTP跨度
    span = tracing_service.create_span(
        f"{request.method} {request.url.path}",
        trace_id=trace_id
    )
    span.set_attribute('method', request.method)
    span.set_attribute('path', request.url.path)
    span.set_attribute('client_host', request.client.host if request.client else None)
    
    span.start()
    
    start_time = time.time()
    
    try:
        response = await call_next(request)
        
        # 记录响应信息
        duration = time.time() - start_time
        span.set_attribute('status_code', response.status_code)
        span.set_attribute('duration_ms', duration * 1000)
        
        span.end('ok' if response.status_code < 400 else 'error')
        
        # 添加追踪头
        response.headers['X-Trace-ID'] = trace_id
        
        return response
    except Exception as e:
        span.end('error')
        span.set_attribute('error', str(e))
        raise
    finally:
        tracing_service.record_span(span)
