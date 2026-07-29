import React, { useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle2,
  Info,
  ShieldAlert,
  BarChart3,
  Layers,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
} from 'lucide-react';
import clsx from 'clsx';

/**
 * Tremor Design System Components & Styles Showcase
 * Tremor 是现代前端最出名的 Dashboard / Analytics UI 规范之一。
 * 此面板示范了 Tremor 经典的核心 Visual Style：
 * 1. Tremor Card + Delta Badges
 * 2. Tremor Tracker (数据流/运行健康度条)
 * 3. Tremor BarList (高密度数据占比/排序条)
 * 4. Tremor Callouts (状态通知盒)
 * 5. Tremor Progress & Metric Panels
 */

export type DeltaType = 'increase' | 'moderate-increase' | 'decrease' | 'moderate-decrease' | 'unchanged';

interface TremorDeltaBadgeProps {
  type: DeltaType;
  value: string;
}

export function TremorDeltaBadge({ type, value }: TremorDeltaBadgeProps) {
  const getStyle = () => {
    switch (type) {
      case 'increase':
      case 'moderate-increase':
        return {
          bg: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
          icon: <ArrowUpRight className="h-3.5 w-3.5 mr-0.5" />,
        };
      case 'decrease':
      case 'moderate-decrease':
        return {
          bg: 'bg-rose-500/10 border-rose-500/20 text-rose-400',
          icon: <ArrowDownRight className="h-3.5 w-3.5 mr-0.5" />,
        };
      case 'unchanged':
      default:
        return {
          bg: 'bg-gray-500/10 border-gray-500/20 text-gray-400',
          icon: null,
        };
    }
  };

  const style = getStyle();

  return (
    <span className={clsx('inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium tabular-nums', style.bg)}>
      {style.icon}
      {value}
    </span>
  );
}

interface TremorTrackerItem {
  color: 'emerald' | 'amber' | 'rose' | 'gray' | 'blue';
  tooltip: string;
}

interface TremorTrackerProps {
  data: TremorTrackerItem[];
}

export function TremorTracker({ data }: TremorTrackerProps) {
  const getColorClass = (color: TremorTrackerItem['color']) => {
    switch (color) {
      case 'emerald':
        return 'bg-emerald-500 hover:bg-emerald-400';
      case 'amber':
        return 'bg-amber-500 hover:bg-amber-400';
      case 'rose':
        return 'bg-rose-500 hover:bg-rose-400';
      case 'blue':
        return 'bg-blue-500 hover:bg-blue-400';
      case 'gray':
      default:
        return 'bg-gray-700 hover:bg-gray-600';
    }
  };

  return (
    <div className="flex h-8 w-full items-center gap-1 overflow-hidden rounded-md bg-crypto-bg/60 p-1 border border-crypto-border/50">
      {data.map((item, index) => (
        <div
          key={index}
          className={clsx('h-full flex-1 rounded-sm transition-all cursor-pointer', getColorClass(item.color))}
          title={item.tooltip}
        />
      ))}
    </div>
  );
}

interface TremorBarListItem {
  name: string;
  value: number;
  icon?: React.ReactNode;
  href?: string;
}

interface TremorBarListProps {
  data: TremorBarListItem[];
  valueFormatter?: (value: number) => string;
  color?: 'emerald' | 'rose' | 'blue' | 'amber';
}

export function TremorBarList({
  data,
  valueFormatter = (v) => v.toString(),
  color = 'blue',
}: TremorBarListProps) {
  const maxValue = Math.max(...data.map((d) => d.value), 1);

  const getBgClass = () => {
    switch (color) {
      case 'emerald':
        return 'bg-emerald-500/15 border-l-2 border-emerald-500';
      case 'rose':
        return 'bg-rose-500/15 border-l-2 border-rose-500';
      case 'amber':
        return 'bg-amber-500/15 border-l-2 border-amber-500';
      case 'blue':
      default:
        return 'bg-blue-500/15 border-l-2 border-blue-500';
    }
  };

  return (
    <div className="space-y-1.5 text-xs">
      {data.map((item, idx) => {
        const widthPercent = Math.min(100, Math.max(4, (item.value / maxValue) * 100));
        return (
          <div key={idx} className="group relative flex items-center justify-between py-1 px-1.5 rounded hover:bg-crypto-bg/40">
            {/* Background progress bar */}
            <div
              className={clsx('absolute left-0 top-0 bottom-0 rounded transition-all duration-300', getBgClass())}
              style={{ width: `${widthPercent}%` }}
            />
            <div className="relative z-10 flex items-center gap-2 truncate pr-2 font-medium text-gray-200">
              {item.icon}
              <span className="truncate">{item.name}</span>
            </div>
            <div className="relative z-10 font-bold tabular-nums text-gray-300">
              {valueFormatter(item.value)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface TremorCalloutProps {
  title: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
  color?: 'emerald' | 'amber' | 'rose' | 'blue';
}

export function TremorCallout({ title, children, icon, color = 'blue' }: TremorCalloutProps) {
  const getStyle = () => {
    switch (color) {
      case 'emerald':
        return {
          border: 'border-l-4 border-l-emerald-500 border-emerald-500/20',
          bg: 'bg-emerald-500/5',
          text: 'text-emerald-300',
          defaultIcon: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
        };
      case 'amber':
        return {
          border: 'border-l-4 border-l-amber-500 border-amber-500/20',
          bg: 'bg-amber-500/5',
          text: 'text-amber-300',
          defaultIcon: <AlertTriangle className="h-4 w-4 text-amber-400" />,
        };
      case 'rose':
        return {
          border: 'border-l-4 border-l-rose-500 border-rose-500/20',
          bg: 'bg-rose-500/5',
          text: 'text-rose-300',
          defaultIcon: <ShieldAlert className="h-4 w-4 text-rose-400" />,
        };
      case 'blue':
      default:
        return {
          border: 'border-l-4 border-l-blue-500 border-blue-500/20',
          bg: 'bg-blue-500/5',
          text: 'text-blue-300',
          defaultIcon: <Info className="h-4 w-4 text-blue-400" />,
        };
    }
  };

  const style = getStyle();

  return (
    <div className={clsx('rounded-r-lg border p-4 text-xs', style.border, style.bg)}>
      <div className="flex items-center gap-2 font-bold mb-1">
        {icon || style.defaultIcon}
        <span className={style.text}>{title}</span>
      </div>
      <div className="text-gray-400 leading-relaxed pl-6">{children}</div>
    </div>
  );
}

export function TremorShowcasePanel() {
  const [activeTab, setActiveTab] = useState<'metrics' | 'tracker' | 'barlist'>('metrics');

  // Sample data for Tremor Tracker (30-day API/Server health stream)
  const trackerData: TremorTrackerItem[] = Array.from({ length: 30 }, (_, i) => {
    if (i === 12 || i === 25) return { color: 'amber', tooltip: `Day ${i + 1}: 延迟波动 (120ms)` };
    if (i === 18) return { color: 'rose', tooltip: `Day ${i + 1}: 策略断连告警` };
    return { color: 'emerald', tooltip: `Day ${i + 1}: 运行正常 (99.98% 响应率)` };
  });

  // Sample data for BarList (Industry Sector Money Inflow)
  const sectorInflowData: TremorBarListItem[] = [
    { name: '半导体 & 光刻机概念', value: 128.4 },
    { name: 'AI算力与服务器集群', value: 94.2 },
    { name: '新能源汽车 & 电池', value: 68.7 },
    { name: '低空经济与无人机', value: 52.1 },
    { name: '生物医药 & 创新药', value: 39.5 },
  ];

  const sectorOutflowData: TremorBarListItem[] = [
    { name: '房地产开发与建筑', value: 87.2 },
    { name: '传统白酒与消费', value: 62.4 },
    { name: '煤炭采选与能源', value: 45.1 },
    { name: '钢铁冶炼', value: 31.8 },
  ];

  return (
    <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
      {/* Panel Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4 bg-gradient-to-r from-crypto-card via-crypto-card to-blue-950/20">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-400">
            <BarChart3 className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-black text-white">Tremor UI Style 风格展示面板</h2>
              <span className="rounded bg-blue-500/20 px-2 py-0.5 text-[10px] font-bold text-blue-300 border border-blue-500/30">
                Tremor Analytics System
              </span>
            </div>
            <p className="mt-0.5 text-xs text-gray-400">
              引入 GitHub 高星级 Tremor 仪表盘样式（包含 Delta Badges, Tracker 健康流, BarList 比率图, Callout 告警盒）
            </p>
          </div>
        </div>

        {/* Tab Controls */}
        <div className="flex rounded-lg border border-crypto-border bg-crypto-bg/80 p-0.5 text-xs">
          <button
            onClick={() => setActiveTab('metrics')}
            className={clsx(
              'px-3 py-1.5 font-bold transition-colors rounded-md',
              activeTab === 'metrics' ? 'bg-blue-600 text-white shadow' : 'text-gray-400 hover:text-gray-200'
            )}
          >
            KPI Metric 增量卡
          </button>
          <button
            onClick={() => setActiveTab('tracker')}
            className={clsx(
              'px-3 py-1.5 font-bold transition-colors rounded-md',
              activeTab === 'tracker' ? 'bg-blue-600 text-white shadow' : 'text-gray-400 hover:text-gray-200'
            )}
          >
            Tracker 状态条
          </button>
          <button
            onClick={() => setActiveTab('barlist')}
            className={clsx(
              'px-3 py-1.5 font-bold transition-colors rounded-md',
              activeTab === 'barlist' ? 'bg-blue-600 text-white shadow' : 'text-gray-400 hover:text-gray-200'
            )}
          >
            BarList 比例条
          </button>
        </div>
      </div>

      <div className="p-5 space-y-5">
        {/* Tab 1: Tremor KPI Cards */}
        {activeTab === 'metrics' && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {/* Metric 1 */}
            <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4 transition-all hover:border-crypto-border/80">
              <div className="flex items-center justify-between text-xs font-semibold text-gray-400">
                <span>策略组合总收益 (PnL)</span>
                <TremorDeltaBadge type="increase" value="+14.8%" />
              </div>
              <div className="mt-3 text-2xl font-black tabular-nums text-white">¥ 1,482,900</div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500">
                <span>基准对比 (沪深300)</span>
                <span className="font-semibold text-emerald-400">+6.2% 超额</span>
              </div>
            </div>

            {/* Metric 2 */}
            <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4 transition-all hover:border-crypto-border/80">
              <div className="flex items-center justify-between text-xs font-semibold text-gray-400">
                <span>夏普比率 (Sharpe)</span>
                <TremorDeltaBadge type="moderate-increase" value="2.31" />
              </div>
              <div className="mt-3 text-2xl font-black tabular-nums text-blue-400">2.45</div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500">
                <span>年化波动率</span>
                <span className="font-semibold text-gray-300">11.4%</span>
              </div>
            </div>

            {/* Metric 3 */}
            <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4 transition-all hover:border-crypto-border/80">
              <div className="flex items-center justify-between text-xs font-semibold text-gray-400">
                <span>最大回撤 (MaxDD)</span>
                <TremorDeltaBadge type="decrease" value="-4.12%" />
              </div>
              <div className="mt-3 text-2xl font-black tabular-nums text-rose-400">-3.85%</div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500">
                <span>风控预警线</span>
                <span className="font-semibold text-amber-400">-8.00%</span>
              </div>
            </div>

            {/* Metric 4 */}
            <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4 transition-all hover:border-crypto-border/80">
              <div className="flex items-center justify-between text-xs font-semibold text-gray-400">
                <span>胜率 (Win Rate)</span>
                <TremorDeltaBadge type="unchanged" value="68.5%" />
              </div>
              <div className="mt-3 text-2xl font-black tabular-nums text-emerald-400">68.5%</div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500">
                <span>盈亏比 (P/L Ratio)</span>
                <span className="font-semibold text-gray-300">2.15 : 1</span>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Tremor Tracker */}
        {activeTab === 'tracker' && (
          <div className="space-y-4">
            <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-emerald-400" />
                  <span className="font-bold text-gray-200">行情报速与数据源节点可用性 (过去 30 天)</span>
                </div>
                <span className="font-semibold text-emerald-400">99.8% 在线</span>
              </div>

              {/* Tremor Tracker component */}
              <TremorTracker data={trackerData} />

              <div className="flex items-center justify-between text-[11px] text-gray-500 pt-1">
                <span>30 天前</span>
                <div className="flex items-center gap-3 text-gray-400">
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" /> 正常</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-500" /> 延迟</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-rose-500" /> 离线</span>
                </div>
                <span>今天</span>
              </div>
            </div>

            <TremorCallout title="Tremor Tracker 说明" color="blue">
              Tremor Tracker 极适合用于实时监控系统服务可用性、数据流水线健康度或因子更新状态，每格悬停即刻查看详细节点状态。
            </TremorCallout>
          </div>
        )}

        {/* Tab 3: Tremor BarList */}
        {activeTab === 'barlist' && (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4 space-y-3">
              <div className="flex items-center justify-between border-b border-crypto-border/60 pb-2">
                <span className="text-xs font-bold text-emerald-400 flex items-center gap-1.5">
                  <TrendingUp className="h-3.5 w-3.5" /> 净流入前五大板块 (亿元)
                </span>
                <span className="text-[10px] text-gray-500">主力资金</span>
              </div>
              <TremorBarList data={sectorInflowData} valueFormatter={(v) => `+${v} 亿`} color="emerald" />
            </div>

            <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4 space-y-3">
              <div className="flex items-center justify-between border-b border-crypto-border/60 pb-2">
                <span className="text-xs font-bold text-rose-400 flex items-center gap-1.5">
                  <TrendingDown className="h-3.5 w-3.5" /> 净流出前四大板块 (亿元)
                </span>
                <span className="text-[10px] text-gray-500">主力资金</span>
              </div>
              <TremorBarList data={sectorOutflowData} valueFormatter={(v) => `-${v} 亿`} color="rose" />
            </div>
          </div>
        )}

        {/* Tremor Callout Box Demo */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 pt-1">
          <TremorCallout title="Tremor 风格特点说明" color="emerald">
            Tremor 采用强对比度的暗色背景搭配微弱边框、高亮增量 Badges 和清晰数据层级，能让高密度金融数据一目了然。
          </TremorCallout>
          <TremorCallout title="风控与风向提醒" color="amber">
            当前半导体板块资金抱团集中度达到 28.4%，注意高位分歧与短线换手率变化。
          </TremorCallout>
        </div>
      </div>
    </section>
  );
}

export default TremorShowcasePanel;
