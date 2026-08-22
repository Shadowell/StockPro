import type { ReactNode } from 'react';

export type MarketColor = 'up' | 'down' | 'neutral' | 'blue' | 'green' | 'red' | 'amber';

export interface BitProThemeProps {
  children: ReactNode;
  className?: string;
  colorScheme?: 'red-up-green-down' | 'green-up-red-down';
}

export interface DataPanelProps {
  children: ReactNode;
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export interface MetricCardProps {
  label: ReactNode;
  value: ReactNode;
  icon?: ReactNode;
  color?: MarketColor;
  detail?: ReactNode;
  className?: string;
}

export interface StatusBadgeProps {
  children: ReactNode;
  tone?: MarketColor;
  className?: string;
}

export interface LogStreamItem {
  id: string;
  time: string;
  label: string;
  message: string;
  tone?: 'neutral' | 'blue' | 'green' | 'red' | 'amber';
  meta?: string;
}

export interface LogStreamProps {
  items: LogStreamItem[];
  emptyText: ReactNode;
  className?: string;
}

export function BitProTheme(props: BitProThemeProps): ReactNode;
export function DataPanel(props: DataPanelProps): ReactNode;
export function MetricCard(props: MetricCardProps): ReactNode;
export function StatusBadge(props: StatusBadgeProps): ReactNode;
export function LogStream(props: LogStreamProps): ReactNode;
