/**
 * 浏览器环境下根据页面协议选用 ws:// 或 wss://（HTTPS 站点必须走 wss，否则会混用被拒连）。
 */
export function getDefaultRealtimeWebSocketUrl(path = '/api/ws'): string {
  if (typeof window === 'undefined') {
    return `ws://localhost${path}`;
  }
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${wsProto}//${window.location.host}${path}`;
}
