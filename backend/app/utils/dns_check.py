"""
DNS 检查和连接诊断工具
用于检查 Qwen/DashScope API 的 DNS 连接问题
"""
import socket
import logging
from typing import Dict, Any, Optional
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class DNSChecker:
    """检查 DNS 和网络连接的工具类"""
    
    # DashScope API 的主要端点
    DASHSCOPE_ENDPOINTS = [
        "api.aliyun.com",
        "dashscope.aliyuncs.com",
        "dashscope-api.cn-hangzhou.aliyuncs.com",
    ]
    
    @staticmethod
    def check_dns_resolution(hostname: str) -> Dict[str, Any]:
        """
        检查 DNS 解析
        
        Args:
            hostname: 要解析的主机名
            
        Returns:
            包含解析结果的字典
        """
        try:
            ip_address = socket.gethostbyname(hostname)
            return {
                "success": True,
                "hostname": hostname,
                "ip_address": ip_address,
                "error": None
            }
        except socket.gaierror as e:
            return {
                "success": False,
                "hostname": hostname,
                "ip_address": None,
                "error": f"DNS 解析失败: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "hostname": hostname,
                "ip_address": None,
                "error": f"未知错误: {str(e)}"
            }
    
    @staticmethod
    def check_socket_connection(hostname: str, port: int = 443, timeout: int = 5) -> Dict[str, Any]:
        """
        检查 socket 连接
        
        Args:
            hostname: 主机名
            port: 端口号（默认 443 HTTPS）
            timeout: 超时时间（秒）
            
        Returns:
            包含连接结果的字典
        """
        try:
            sock = socket.create_connection((hostname, port), timeout=timeout)
            sock.close()
            return {
                "success": True,
                "hostname": hostname,
                "port": port,
                "error": None
            }
        except socket.timeout:
            return {
                "success": False,
                "hostname": hostname,
                "port": port,
                "error": f"连接超时 (timeout={timeout}s)"
            }
        except socket.gaierror as e:
            return {
                "success": False,
                "hostname": hostname,
                "port": port,
                "error": f"DNS 或网络错误: {str(e)}"
            }
        except ConnectionRefusedError as e:
            return {
                "success": False,
                "hostname": hostname,
                "port": port,
                "error": f"连接被拒绝: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "hostname": hostname,
                "port": port,
                "error": f"连接错误: {str(e)}"
            }
    
    @staticmethod
    def check_http_connectivity(url: str, timeout: int = 5) -> Dict[str, Any]:
        """
        检查 HTTP 连接
        
        Args:
            url: 要检查的 URL
            timeout: 超时时间（秒）
            
        Returns:
            包含连接结果的字典
        """
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            return {
                "success": True,
                "url": url,
                "status_code": response.status_code,
                "error": None
            }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "url": url,
                "status_code": None,
                "error": f"HTTP 请求超时 (timeout={timeout}s)"
            }
        except requests.exceptions.ConnectionError as e:
            return {
                "success": False,
                "url": url,
                "status_code": None,
                "error": f"连接错误: {str(e)}"
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "url": url,
                "status_code": None,
                "error": f"请求错误: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "url": url,
                "status_code": None,
                "error": f"未知错误: {str(e)}"
            }
    
    @classmethod
    def check_dashscope_connectivity(cls) -> Dict[str, Any]:
        """
        检查 DashScope API 的连接
        
        Returns:
            包含所有检查结果的字典
        """
        results = {
            "dns_checks": [],
            "socket_checks": [],
            "http_checks": [],
            "summary": {
                "all_passed": True,
                "failed_checks": []
            }
        }
        
        # 1. DNS 检查
        for endpoint in cls.DASHSCOPE_ENDPOINTS:
            dns_result = cls.check_dns_resolution(endpoint)
            results["dns_checks"].append(dns_result)
            if not dns_result["success"]:
                results["summary"]["all_passed"] = False
                results["summary"]["failed_checks"].append(f"DNS: {endpoint}")
        
        # 2. Socket 连接检查
        for endpoint in cls.DASHSCOPE_ENDPOINTS:
            socket_result = cls.check_socket_connection(endpoint, port=443)
            results["socket_checks"].append(socket_result)
            if not socket_result["success"]:
                results["summary"]["all_passed"] = False
                results["summary"]["failed_checks"].append(f"Socket: {endpoint}:443")
        
        # 3. HTTP 连接检查
        http_urls = [
            "https://dashscope.aliyuncs.com/",
            "https://api.aliyun.com/",
        ]
        for url in http_urls:
            http_result = cls.check_http_connectivity(url)
            results["http_checks"].append(http_result)
            if not http_result["success"]:
                results["summary"]["all_passed"] = False
                results["summary"]["failed_checks"].append(f"HTTP: {url}")
        
        return results
    
    @classmethod
    def get_diagnostic_report(cls) -> str:
        """
        获取诊断报告
        
        Returns:
            诊断报告文本
        """
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("DashScope/Qwen API 连接诊断报告")
        report_lines.append("=" * 60)
        
        # 系统信息
        report_lines.append("\n【系统信息】")
        import platform
        report_lines.append(f"操作系统: {platform.system()} {platform.release()}")
        report_lines.append(f"Python 版本: {platform.python_version()}")
        
        # 网络配置
        report_lines.append("\n【网络配置】")
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            report_lines.append(f"本地主机名: {hostname}")
            report_lines.append(f"本地 IP: {local_ip}")
        except Exception as e:
            report_lines.append(f"获取网络信息失败: {e}")
        
        # 运行检查
        report_lines.append("\n【连接检查结果】")
        results = cls.check_dashscope_connectivity()
        
        # DNS 检查结果
        report_lines.append("\n DNS 解析检查:")
        for dns_result in results["dns_checks"]:
            status = "✓ 通过" if dns_result["success"] else "✗ 失败"
            report_lines.append(f"  {status} - {dns_result['hostname']}")
            if dns_result["error"]:
                report_lines.append(f"         {dns_result['error']}")
            else:
                report_lines.append(f"         IP: {dns_result['ip_address']}")
        
        # Socket 检查结果
        report_lines.append("\n Socket 连接检查:")
        for socket_result in results["socket_checks"]:
            status = "✓ 通过" if socket_result["success"] else "✗ 失败"
            report_lines.append(f"  {status} - {socket_result['hostname']}:{socket_result['port']}")
            if socket_result["error"]:
                report_lines.append(f"         {socket_result['error']}")
        
        # HTTP 检查结果
        report_lines.append("\n HTTP 连接检查:")
        for http_result in results["http_checks"]:
            status = "✓ 通过" if http_result["success"] else "✗ 失败"
            report_lines.append(f"  {status} - {http_result['url']}")
            if http_result["error"]:
                report_lines.append(f"         {http_result['error']}")
            else:
                report_lines.append(f"         状态码: {http_result['status_code']}")
        
        # 总结
        report_lines.append("\n【诊断总结】")
        if results["summary"]["all_passed"]:
            report_lines.append("✓ 所有检查通过，网络连接正常")
        else:
            report_lines.append("✗ 存在以下连接问题:")
            for issue in results["summary"]["failed_checks"]:
                report_lines.append(f"  - {issue}")
            report_lines.append("\n【排查建议】")
            report_lines.append("1. 检查网络连接是否正常")
            report_lines.append("2. 检查防火墙设置是否阻止了连接")
            report_lines.append("3. 尝试使用其他 DNS 服务器（如 8.8.8.8）")
            report_lines.append("4. 检查代理设置是否正确")
            report_lines.append("5. 确认 Qwen API Key 是否有效")
        
        report_lines.append("\n" + "=" * 60)
        return "\n".join(report_lines)


def diagnose_dns_issues() -> None:
    """
    运行 DNS 诊断
    """
    print(DNSChecker.get_diagnostic_report())


if __name__ == "__main__":
    diagnose_dns_issues()
