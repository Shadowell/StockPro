import type { PageView } from './types';

/** 详情是否指向一个已确认存在的实例。目录未返回前不能把空列表当成「还在加载」。 */
export function shouldAbandonStaleDetail(input: {
  view: PageView;
  activeInstanceId: string | null;
  instancesReady: boolean;
  instanceKnown: boolean;
}): boolean {
  if (input.view !== 'detail' || !input.activeInstanceId) return false;
  if (input.instanceKnown) return false;
  return input.instancesReady;
}
