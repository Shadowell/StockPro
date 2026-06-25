import React, { useState } from 'react';
import { useStore } from '@/stores/useStore';
import {
  Database,
  Workflow,
  ShieldCheck,
  Sparkles,
  Compass,
  Wrench,
  FileCode2,
  Download,
  Package,
} from 'lucide-react';
import { DataHubDatasetPanel } from '@/components/DataHubDatasetPanel';
import { DataHubJobsPanel } from '@/components/DataHubJobsPanel';
import { DataQualityPanel } from '@/components/DataQualityPanel';
import { DataHubFeaturePanel } from '@/components/DataHubFeaturePanel';
import { BatchImportPanel } from '@/components/BatchImportPanel';
import { DataDevManager } from '@/components/DataDevManager';
import { DatabaseManager } from '@/components/DatabaseManager';
import { SQLWorkbench } from '@/components/SQLWorkbench';
import { BackfillRepairPanel } from '@/components/BackfillRepairPanel';

type DataHubTab = 'assets' | 'jobs' | 'quality' | 'features' | 'legacy';
type LegacyTab = 'batchimport' | 'datadev' | 'database' | 'sql' | 'repair';

export const DataProcessingAnalysis: React.FC = () => {
  const { language } = useStore();

  const [activeTab, setActiveTab] = useState<DataHubTab>('assets');
  const [legacyTab, setLegacyTab] = useState<LegacyTab>('batchimport');

  return (
    <div className="flex flex-col gap-4 h-full">
        <div className="inline-flex items-center rounded-xl border border-crypto-border bg-crypto-card p-1">
          <button
            className={`inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold transition-colors ${
              activeTab === 'assets' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
            }`}
            onClick={() => setActiveTab('assets')}
          >
            <Database size={14} />
            {language === 'zh' ? '数据资产' : 'Data Assets'}
          </button>
          <button
            className={`inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold transition-colors ${
              activeTab === 'jobs' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
            }`}
            onClick={() => setActiveTab('jobs')}
          >
            <Workflow size={14} />
            {language === 'zh' ? '生产任务' : 'Production Jobs'}
          </button>
          <button
            className={`inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold transition-colors ${
              activeTab === 'quality' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
            }`}
            onClick={() => setActiveTab('quality')}
          >
            <ShieldCheck size={14} />
            {language === 'zh' ? '质量治理' : 'Quality Governance'}
          </button>
          <button
            className={`inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold transition-colors ${
              activeTab === 'features' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
            }`}
            onClick={() => setActiveTab('features')}
          >
            <Sparkles size={14} />
            {language === 'zh' ? '特征服务' : 'Feature Services'}
          </button>
          <button
            className={`inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold transition-colors ${
              activeTab === 'legacy' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300'
            }`}
            onClick={() => setActiveTab('legacy')}
          >
            <Compass size={14} />
            {language === 'zh' ? '兼容入口' : 'Legacy'}
          </button>
        </div>

        <div className="flex-1 min-h-0">
          {activeTab === 'assets' && <DataHubDatasetPanel />}
          {activeTab === 'jobs' && <DataHubJobsPanel />}
          {activeTab === 'quality' && <DataQualityPanel />}
          {activeTab === 'features' && <DataHubFeaturePanel />}

          {activeTab === 'legacy' && (
            <div className="h-full flex flex-col gap-3">
              <div className="inline-flex items-center rounded-lg border border-crypto-border bg-crypto-card p-0.5">
                <button
                  className={`inline-flex h-8 items-center gap-1 rounded-md px-3 text-xs font-semibold transition-colors ${
                    legacyTab === 'batchimport'
                      ? 'bg-blue-500/20 text-blue-300'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                  onClick={() => setLegacyTab('batchimport')}
                >
                  <Download size={12} />
                  批量导入
                </button>
                <button
                  className={`inline-flex h-8 items-center gap-1 rounded-md px-3 text-xs font-semibold transition-colors ${
                    legacyTab === 'datadev'
                      ? 'bg-blue-500/20 text-blue-300'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                  onClick={() => setLegacyTab('datadev')}
                >
                  <Package size={12} />
                  Data Dev
                </button>
                <button
                  className={`inline-flex h-8 items-center gap-1 rounded-md px-3 text-xs font-semibold transition-colors ${
                    legacyTab === 'database'
                      ? 'bg-blue-500/20 text-blue-300'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                  onClick={() => setLegacyTab('database')}
                >
                  <Database size={12} />
                  数据库管理
                </button>
                <button
                  className={`inline-flex h-8 items-center gap-1 rounded-md px-3 text-xs font-semibold transition-colors ${
                    legacyTab === 'sql'
                      ? 'bg-blue-500/20 text-blue-300'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                  onClick={() => setLegacyTab('sql')}
                >
                  <FileCode2 size={12} />
                  SQL工作台
                </button>
                <button
                  className={`inline-flex h-8 items-center gap-1 rounded-md px-3 text-xs font-semibold transition-colors ${
                    legacyTab === 'repair'
                      ? 'bg-blue-500/20 text-blue-300'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                  onClick={() => setLegacyTab('repair')}
                >
                  <Wrench size={12} />
                  回补修复
                </button>
              </div>

              <div className="flex-1 min-h-0">
                {legacyTab === 'batchimport' && <BatchImportPanel />}
                {legacyTab === 'datadev' && <DataDevManager />}
                {legacyTab === 'database' && <DatabaseManager />}
                {legacyTab === 'sql' && <SQLWorkbench />}
                {legacyTab === 'repair' && <BackfillRepairPanel />}
              </div>
            </div>
          )}
        </div>
        </div>
  );
};
