import {
  Code,
  Zap,
  type LucideIcon,
} from 'lucide-react';

export type AppModule = {
  id: string;
  path: string;
  labelKey: string;
  groupId: string;
  Icon: LucideIcon;
  aliases?: string[];
};

export const appModules: AppModule[] = [
  { id: 'strategy-dev', path: '/strategy-dev', labelKey: 'nav.strategy_dev', groupId: 'strategy-factory', Icon: Code },
  { id: 'strategy-exec', path: '/strategy-exec', labelKey: 'nav.strategy_exec', groupId: 'strategy-factory', Icon: Zap },
];

export const moduleGroups = [
  { id: 'strategy-factory', labelKey: 'module_group.strategy_factory' },
];

export const moduleAliases = appModules.flatMap((module) =>
  (module.aliases || []).map((alias) => ({ alias, path: module.path }))
);
