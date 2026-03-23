import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, BarChart2, Database, BrainCircuit, Newspaper, GripVertical, Activity, CalendarDays, Code, Zap, FlaskConical, Target, Wallet } from 'lucide-react';
import { useStore } from '../stores/useStore';
import { getTranslation, TranslationKey } from '../lib/i18n';
import clsx from 'clsx';

interface NavigationProps {
  orientation?: 'horizontal' | 'vertical';
}

// Drag threshold configuration
const DRAG_DELAY_MS = 200; // Delay before drag activates

export const Navigation: React.FC<NavigationProps> = ({ orientation = 'horizontal' }) => {
  const { language } = useStore();
  const t = (key: TranslationKey) => getTranslation(language, key);

  type TabDef = {
    id: string;
    to: string;
    label: string;
    Icon: React.ComponentType<{ size?: string | number; className?: string }>;
  };

  const tabs: TabDef[] = useMemo(
    () => [
      { id: 'strategy-filter', to: '/', label: t('nav.dashboard'), Icon: LayoutDashboard },
      { id: 'strategy-exec', to: '/strategy-exec', label: language === 'zh' ? '实时策略盯盘' : 'Strategy Watch', Icon: Zap },
      { id: 'live-trading', to: '/trading', label: language === 'zh' ? '实盘交易' : 'Live Trading', Icon: Wallet },
      { id: 'market-overview', to: '/market', label: t('nav.market'), Icon: BarChart2 },
      { id: 'sentiment-analysis', to: '/sentiment', label: t('nav.sentiment'), Icon: Activity },
      { id: 'news-feed', to: '/news', label: language === 'zh' ? '消息中心' : 'News Center', Icon: Newspaper },
      { id: 'ai-analysis', to: '/ai', label: t('nav.ai'), Icon: BrainCircuit },
      { id: 'strategy-dev', to: '/strategy-dev', label: language === 'zh' ? '策略开发' : 'Strategy Dev', Icon: Code },
      { id: 'market-pulse', to: '/pulse', label: language === 'zh' ? '复盘中心' : 'Review Center', Icon: Target },
      { id: 'factor-library', to: '/factors', label: language === 'zh' ? '因子中心' : 'Factor Center', Icon: FlaskConical },
      { id: 'data-analysis', to: '/analysis', label: t('nav.data'), Icon: Database },
      { id: 'trading-calendar', to: '/calendar', label: language === 'zh' ? '交易日历' : 'Calendar', Icon: CalendarDays },
    ],
    [t, language]
  );

  const storageKey = 'nav_tab_order_v1';
  const defaultOrder = useMemo(() => tabs.map((t) => t.id), [tabs]);
  const [order, setOrder] = useState<string[]>(defaultOrder);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [dragReady, setDragReady] = useState<boolean>(false); // New: drag is ready after delay
  
  // Refs for drag delay handling
  const dragStartPos = useRef<{ x: number; y: number } | null>(null);
  const dragDelayTimer = useRef<number | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return;
      const ids = parsed.filter((v): v is string => typeof v === 'string');
      const known = new Set(defaultOrder);
      const merged = [...ids.filter((id) => known.has(id)), ...defaultOrder.filter((id) => !ids.includes(id))];
      if (merged.length) setOrder(merged);
    } catch {
      return;
    }
  }, [defaultOrder]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (dragDelayTimer.current) {
        window.clearTimeout(dragDelayTimer.current);
      }
    };
  }, []);

  const orderedTabs = useMemo(() => {
    const byId = new Map(tabs.map((t) => [t.id, t]));
    return order.map((id) => byId.get(id)).filter((t): t is TabDef => Boolean(t));
  }, [order, tabs]);

  const persistOrder = (next: string[]) => {
    setOrder(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      return;
    }
  };

  const moveItem = (list: string[], fromId: string, toId: string) => {
    if (fromId === toId) return list;
    const fromIndex = list.indexOf(fromId);
    const toIndex = list.indexOf(toId);
    if (fromIndex === -1 || toIndex === -1) return list;
    const next = [...list];
    next.splice(fromIndex, 1);
    next.splice(toIndex, 0, fromId);
    return next;
  };

  const handleDragHandleMouseDown = useCallback((tabId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    
    // Start delay timer
    dragDelayTimer.current = window.setTimeout(() => {
      setDragReady(true);
      setDraggingId(tabId);
    }, DRAG_DELAY_MS);
  }, []);

  const handleDragHandleMouseUp = useCallback(() => {
    if (dragDelayTimer.current) {
      window.clearTimeout(dragDelayTimer.current);
      dragDelayTimer.current = null;
    }
    dragStartPos.current = null;
    if (!isDragging) {
      setDragReady(false);
      setDraggingId(null);
    }
  }, [isDragging]);

  // Global mouse up handler
  useEffect(() => {
    const handleGlobalMouseUp = () => {
      handleDragHandleMouseUp();
    };
    window.addEventListener('mouseup', handleGlobalMouseUp);
    return () => window.removeEventListener('mouseup', handleGlobalMouseUp);
  }, [handleDragHandleMouseUp]);

  return (
    <nav className={clsx(
      "flex gap-2",
      orientation === 'vertical' ? "flex-col" : "flex-row mb-6 border-b border-slate-700 pb-2 overflow-x-auto"
    )}>
      {orderedTabs.map((tab) => (
        <div key={tab.id} className="relative flex items-center group/nav">
          {/* Drag handle - visible on hover */}
          <div
            className={clsx(
              "absolute -left-1 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover/nav:opacity-50 hover:!opacity-100 cursor-grab transition-opacity z-10",
              dragReady && draggingId === tab.id && "opacity-100 cursor-grabbing"
            )}
            onMouseDown={(e) => handleDragHandleMouseDown(tab.id, e)}
            title={language === 'zh' ? '拖拽排序' : 'Drag to reorder'}
          >
            <GripVertical size={12} className="text-slate-500" />
          </div>
          
          <NavLink
            to={tab.to}
            draggable={dragReady && draggingId === tab.id}
            onDragStart={(e) => {
              if (!dragReady || draggingId !== tab.id) {
                e.preventDefault();
                return;
              }
              e.stopPropagation();
              setIsDragging(true);
              e.dataTransfer.effectAllowed = 'move';
              e.dataTransfer.setData('text/plain', tab.id);
            }}
            onDragOver={(e) => {
              if (!isDragging) return;
              e.preventDefault();
              e.stopPropagation();
              if (dragOverId !== tab.id) setDragOverId(tab.id);
            }}
            onDragLeave={(e) => {
              e.stopPropagation();
              if (dragOverId === tab.id) setDragOverId(null);
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const from = draggingId || e.dataTransfer.getData('text/plain');
              if (!from) return;
              persistOrder(moveItem(order, from, tab.id));
              setDraggingId(null);
              setDragOverId(null);
              setIsDragging(false);
              setDragReady(false);
            }}
            onDragEnd={(e) => {
              e.stopPropagation();
              setDraggingId(null);
              setDragOverId(null);
              setIsDragging(false);
              setDragReady(false);
            }}
            onClick={(e) => {
              // Prevent navigation if we're dragging
              if (isDragging) {
                e.preventDefault();
                setIsDragging(false);
                setDragReady(false);
              }
            }}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-4 py-2.5 rounded-lg transition-all select-none group',
                isActive 
                  ? 'bg-blue-600/10 text-blue-400 font-bold border border-blue-500/20 shadow-inner' 
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50',
                draggingId === tab.id && isDragging && 'opacity-60 ring-2 ring-blue-500',
                dragOverId === tab.id && draggingId && draggingId !== tab.id && 'ring-2 ring-blue-600 ring-offset-2 ring-offset-slate-900'
              )
            }
          >
            <tab.Icon size={20} className="group-hover:scale-110 transition-transform" />
            <span className="text-sm">{tab.label}</span>
          </NavLink>
        </div>
      ))}
    </nav>
  );
};
