import { Activity, CircleDot, LayoutDashboard } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import MarketUniversePanel from '../components/MarketUniversePanel';
import { useStore } from '../stores/useStore';

export default function Home() {
  const { selectedExchange } = useStore();
  const navigate = useNavigate();

  const handleSelectSymbol = (symbol: string) => {
    useStore.getState().setSelectedSymbol(symbol);
    navigate('/market');
  };

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg">
      <header className="border-b border-crypto-border/70 bg-slate-950/35 px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
              <LayoutDashboard className="h-5 w-5 text-blue-300" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">
                <Activity className="h-3 w-3" />
                Market Command
              </div>
              <h1 className="mt-0.5 text-xl font-bold text-white">市场大盘</h1>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className="flex items-center gap-2 rounded-md border border-emerald-500/20 bg-emerald-500/[0.07] px-3 py-1.5 font-medium text-emerald-300">
              <CircleDot className="h-3.5 w-3.5" />
              OKX PUBLIC DATA
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-300">
              USDT-SWAP
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-400">
              24H MARKET PULSE
            </span>
          </div>
        </div>
        <p className="mt-3 max-w-3xl border-l-2 border-blue-500/40 pl-3 text-xs leading-5 text-gray-500">
          聚合 OKX 公开行情的大盘广度、成交活跃度和强弱排行；点击榜单标的后进入行情页查看 K 线详情。
        </p>
      </header>

      <div className="px-6 py-5 pb-7">
        <MarketUniversePanel
          variant="summary"
          selectedExchange={selectedExchange}
          onSelectSymbol={handleSelectSymbol}
        />
      </div>
    </div>
  );
}
