import React, { useState } from 'react';
import { MainLayout } from '@/components/MainLayout';
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

  const title = language === 'zh' ? '数据中台' : 'Data Hub';

  return (
    <MainLayout title={title}>
      <div className="flex flex-col gap-4 h-full">
        <div className="rounded border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm text-blue-300">
          <div className="font-semibold mb-1">Data Hub V1</div>
          <div className="text-xs text-blue-200/80">
            当前以“数据资产 -&gt; 生产任务 -&gt; 质量治理 -&gt; 特征服务”为主线。旧版入口保留在“兼容入口”页签。
          </div>
        </div>

        <div className="flex flex-wrap border-b border-slate-800 bg-[#0d121f]">
          <button
            className={`px-5 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'assets' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('assets')}
          >
            <Database size={16} />
            {language === 'zh' ? '数据资产' : 'Data Assets'}
          </button>
          <button
            className={`px-5 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'jobs' ? 'text-emerald-400 border-b-2 border-emerald-400' : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('jobs')}
          >
            <Workflow size={16} />
            {language === 'zh' ? '生产任务' : 'Production Jobs'}
          </button>
          <button
            className={`px-5 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'quality' ? 'text-amber-400 border-b-2 border-amber-400' : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('quality')}
          >
            <ShieldCheck size={16} />
            {language === 'zh' ? '质量治理' : 'Quality Governance'}
          </button>
          <button
            className={`px-5 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'features' ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('features')}
          >
            <Sparkles size={16} />
            {language === 'zh' ? '特征服务' : 'Feature Services'}
          </button>
          <button
            className={`px-5 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'legacy' ? 'text-slate-300 border-b-2 border-slate-400' : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('legacy')}
          >
            <Compass size={16} />
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
              <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                旧版 API/页面处于兼容周期，建议逐步迁移至 Data Hub 统一接口。
              </div>

              <div className="flex flex-wrap border-b border-slate-800 bg-[#0d121f]">
                <button
                  className={`px-4 py-2 text-xs font-bold tracking-wide ${
                    legacyTab === 'batchimport'
                      ? 'text-emerald-400 border-b-2 border-emerald-400'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                  onClick={() => setLegacyTab('batchimport')}
                >
                  <Download size={12} className="inline mr-1" />
                  批量导入
                </button>
                <button
                  className={`px-4 py-2 text-xs font-bold tracking-wide ${
                    legacyTab === 'datadev'
                      ? 'text-purple-400 border-b-2 border-purple-400'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                  onClick={() => setLegacyTab('datadev')}
                >
                  <Package size={12} className="inline mr-1" />
                  Data Dev
                </button>
                <button
                  className={`px-4 py-2 text-xs font-bold tracking-wide ${
                    legacyTab === 'database'
                      ? 'text-blue-400 border-b-2 border-blue-400'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                  onClick={() => setLegacyTab('database')}
                >
                  <Database size={12} className="inline mr-1" />
                  数据库管理
                </button>
                <button
                  className={`px-4 py-2 text-xs font-bold tracking-wide ${
                    legacyTab === 'sql'
                      ? 'text-cyan-400 border-b-2 border-cyan-400'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                  onClick={() => setLegacyTab('sql')}
                >
                  <FileCode2 size={12} className="inline mr-1" />
                  SQL工作台
                </button>
                <button
                  className={`px-4 py-2 text-xs font-bold tracking-wide ${
                    legacyTab === 'repair'
                      ? 'text-orange-400 border-b-2 border-orange-400'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                  onClick={() => setLegacyTab('repair')}
                >
                  <Wrench size={12} className="inline mr-1" />
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
    </MainLayout>
  );
};
