import React from 'react';
import clsx from 'clsx';

interface SkeletonProps {
  className?: string;
}

// Base skeleton pulse animation
export const SkeletonPulse: React.FC<SkeletonProps & { children?: React.ReactNode }> = ({ className, children }) => (
  <div className={clsx("animate-pulse", className)}>
    {children}
  </div>
);

// Single skeleton line/block
export const SkeletonBlock: React.FC<SkeletonProps & { width?: string; height?: string }> = ({ 
  className, 
  width = 'w-full', 
  height = 'h-4' 
}) => (
  <div className={clsx("bg-slate-700/50 rounded", width, height, className)} />
);

// Table skeleton
interface TableSkeletonProps extends SkeletonProps {
  rows?: number;
  cols?: number;
}

export const TableSkeleton: React.FC<TableSkeletonProps> = ({ 
  className, 
  rows = 8, 
  cols = 4 
}) => (
  <SkeletonPulse className={className}>
    <div className="w-full">
      {/* Header */}
      <div className="flex gap-4 px-4 py-3 bg-slate-800/50 border-b border-slate-700">
        {Array.from({ length: cols }).map((_, i) => (
          <SkeletonBlock key={i} width={i === 0 ? "w-16" : "flex-1"} height="h-3" />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <div key={rowIdx} className="flex gap-4 px-4 py-3 border-b border-slate-800/30">
          {Array.from({ length: cols }).map((_, colIdx) => (
            <SkeletonBlock 
              key={colIdx} 
              width={colIdx === 0 ? "w-16" : "flex-1"} 
              height="h-4" 
            />
          ))}
        </div>
      ))}
    </div>
  </SkeletonPulse>
);

// Chart skeleton
interface ChartSkeletonProps extends SkeletonProps {
  showVolume?: boolean;
}

export const ChartSkeleton: React.FC<ChartSkeletonProps> = ({ className, showVolume = true }) => (
  <SkeletonPulse className={clsx("w-full h-full min-h-[280px] flex flex-col", className)}>
    {/* Title */}
    <div className="flex justify-center mb-4">
      <SkeletonBlock width="w-32" height="h-5" />
    </div>
    {/* Main chart area */}
    <div className="flex-1 relative px-4">
      <div className="absolute inset-0 flex items-end justify-around gap-1 px-8 pb-8">
        {Array.from({ length: 20 }).map((_, i) => (
          <div 
            key={i} 
            className="bg-slate-700/30 rounded-t"
            style={{ 
              width: '4%', 
              height: `${30 + Math.random() * 50}%` 
            }} 
          />
        ))}
      </div>
      {/* Y-axis labels */}
      <div className="absolute left-0 top-0 bottom-8 flex flex-col justify-between py-2">
        <SkeletonBlock width="w-10" height="h-3" />
        <SkeletonBlock width="w-10" height="h-3" />
        <SkeletonBlock width="w-10" height="h-3" />
      </div>
    </div>
    {/* Volume area */}
    {showVolume && (
      <div className="h-16 mt-2 px-4">
        <div className="h-full flex items-end justify-around gap-1 px-8">
          {Array.from({ length: 20 }).map((_, i) => (
            <div 
              key={i} 
              className="bg-slate-700/20 rounded-t"
              style={{ 
                width: '4%', 
                height: `${20 + Math.random() * 60}%` 
              }} 
            />
          ))}
        </div>
      </div>
    )}
    {/* X-axis */}
    <div className="flex justify-between px-8 mt-2">
      <SkeletonBlock width="w-12" height="h-3" />
      <SkeletonBlock width="w-12" height="h-3" />
      <SkeletonBlock width="w-12" height="h-3" />
    </div>
  </SkeletonPulse>
);

// Card skeleton
interface CardSkeletonProps extends SkeletonProps {
  lines?: number;
  showTitle?: boolean;
}

export const CardSkeleton: React.FC<CardSkeletonProps> = ({ 
  className, 
  lines = 3, 
  showTitle = true 
}) => (
  <SkeletonPulse className={clsx("bg-slate-800/50 rounded-lg p-4", className)}>
    {showTitle && (
      <div className="flex items-center gap-3 mb-4">
        <SkeletonBlock width="w-8" height="h-8" className="rounded-full" />
        <SkeletonBlock width="w-32" height="h-5" />
      </div>
    )}
    <div className="space-y-3">
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonBlock 
          key={i} 
          width={i === lines - 1 ? "w-2/3" : "w-full"} 
          height="h-4" 
        />
      ))}
    </div>
  </SkeletonPulse>
);

// List skeleton
interface ListSkeletonProps extends SkeletonProps {
  items?: number;
  showAvatar?: boolean;
}

export const ListSkeleton: React.FC<ListSkeletonProps> = ({ 
  className, 
  items = 5, 
  showAvatar = false 
}) => (
  <SkeletonPulse className={clsx("space-y-3", className)}>
    {Array.from({ length: items }).map((_, i) => (
      <div key={i} className="flex items-center gap-3 p-2">
        {showAvatar && (
          <SkeletonBlock width="w-10" height="h-10" className="rounded-full flex-shrink-0" />
        )}
        <div className="flex-1 space-y-2">
          <SkeletonBlock width="w-3/4" height="h-4" />
          <SkeletonBlock width="w-1/2" height="h-3" />
        </div>
        <SkeletonBlock width="w-16" height="h-4" />
      </div>
    ))}
  </SkeletonPulse>
);

// Search results skeleton
export const SearchResultsSkeleton: React.FC<SkeletonProps & { count?: number }> = ({ 
  className, 
  count = 5 
}) => (
  <SkeletonPulse className={clsx("bg-slate-800 border border-slate-700 rounded-lg overflow-hidden", className)}>
    {Array.from({ length: count }).map((_, i) => (
      <div key={i} className="flex items-center gap-3 px-4 py-3 border-b border-slate-700 last:border-b-0">
        <SkeletonBlock width="w-16" height="h-4" />
        <SkeletonBlock width="flex-1" height="h-4" />
        <SkeletonBlock width="w-20" height="h-4" />
      </div>
    ))}
  </SkeletonPulse>
);

export default {
  SkeletonPulse,
  SkeletonBlock,
  TableSkeleton,
  ChartSkeleton,
  CardSkeleton,
  ListSkeleton,
  SearchResultsSkeleton,
};
