"""
DashScope API 连接工具
提供 DNS 故障转移、重试机制等
"""
import logging
import socket
from typing import Optional, Dict, Any
from functools import wraps
import time

logger = logging.getLogger(__name__)


class DashScopeConfig:
    """DashScope 配置和故障转移管理"""
    
    # DashScope API 端点优先级列表
    API_ENDPOINTS = [
        "dashscope.aliyuncs.com",      # 默认端点
        "api.aliyun.com",               # 备用端点
        "dashscope-api.cn-hangzhou.aliyuncs.com"  # 区域端点
    ]
    
    # DNS 服务器配置
    PREFERRED_DNS_SERVERS = [
        "8.8.8.8",          # Google DNS
        "1.1.1.1",          # Cloudflare DNS
        "223.5.5.5",        # 阿里云 DNS
        "119.29.29.29"      # 腾讯 DNS
    ]
    
    @staticmethod
    def test_endpoint_connectivity(endpoint: str, port: int = 443, timeout: int = 3) -> bool:
        """
        测试端点是否可连接
        
        Args:
            endpoint: 端点地址
            port: 端口号
            timeout: 超时时间（秒）
            
        Returns:
            是否可连接
        """
        try:
            sock = socket.create_connection((endpoint, port), timeout=timeout)
            sock.close()
            logger.debug(f"端点 {endpoint}:{port} 可连接")
            return True
        except Exception as e:
            logger.debug(f"端点 {endpoint}:{port} 不可连接: {str(e)}")
            return False
    
    @staticmethod
    def resolve_hostname_with_fallback(hostname: str, fallback_ips: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        尝试解析主机名，如果失败则使用备用 IP
        
        Args:
            hostname: 主机名
            fallback_ips: 备用 IP 映射（hostname -> ip）
            
        Returns:
            IP 地址或 None
        """
        try:
            ip = socket.gethostbyname(hostname)
            logger.debug(f"成功解析 {hostname} -> {ip}")
            return ip
        except socket.gaierror as e:
            logger.warning(f"DNS 解析失败: {hostname} - {str(e)}")
            
            # 尝试使用备用 IP
            if fallback_ips and hostname in fallback_ips:
                fallback_ip = fallback_ips[hostname]
                logger.info(f"使用备用 IP: {hostname} -> {fallback_ip}")
                return fallback_ip
            
            return None


def retry_on_dns_error(max_retries: int = 3, delay: float = 1.0):
    """
    DNS 错误重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 重试延迟（秒）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (socket.gaierror, OSError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)  # 指数退避
                        logger.warning(
                            f"DNS/网络错误 (尝试 {attempt + 1}/{max_retries}), "
                            f"{wait_time}秒后重试: {str(e)}"
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(f"所有重试都失败: {str(e)}")
                except Exception as e:
                    # 其他异常直接抛出
                    raise
            
            # 抛出最后一个异常
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


class DashScopeConnectionManager:
    """DashScope 连接管理器"""
    
    def __init__(self):
        self._working_endpoint: Optional[str] = None
        self._endpoint_cache: Dict[str, bool] = {}
    
    def get_working_endpoint(self, force_refresh: bool = False) -> Optional[str]:
        """
        获取可用的端点
        
        Args:
            force_refresh: 是否强制刷新
            
        Returns:
            可用的端点或 None
        """
        if self._working_endpoint and not force_refresh:
            if DashScopeConfig.test_endpoint_connectivity(self._working_endpoint):
                return self._working_endpoint
        
        # 尝试找到可用的端点
        for endpoint in DashScopeConfig.API_ENDPOINTS:
            if force_refresh or endpoint not in self._endpoint_cache:
                if DashScopeConfig.test_endpoint_connectivity(endpoint):
                    self._working_endpoint = endpoint
                    self._endpoint_cache[endpoint] = True
                    logger.info(f"使用可用端点: {endpoint}")
                    return endpoint
                else:
                    self._endpoint_cache[endpoint] = False
            elif self._endpoint_cache.get(endpoint):
                return endpoint
        
        logger.error("没有可用的 DashScope 端点")
        return None
    
    def reset(self):
        """重置缓存"""
        self._working_endpoint = None
        self._endpoint_cache.clear()


# 全局连接管理器
_connection_manager = DashScopeConnectionManager()


def get_connection_manager() -> DashScopeConnectionManager:
    """获取连接管理器实例"""
    return _connection_manager
