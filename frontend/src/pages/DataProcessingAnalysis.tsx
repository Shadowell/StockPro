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
import { OperatorPageHeader, SegmentedControl } from '@/components/OperatorShell';

type DataHubTab = 'assets' | 'jobs' | 'quality' | 'features' | 'legacy';
type LegacyTab = 'batchimport' | 'datadev' | 'database' | 'sql' | 'repair';

export const DataProcessingAnalysis: React.FC = () => {
  const { language } = useStore();

  const [activeTab, setActiveTab] = useState<DataHubTab>('assets');
  const [legacyTab, setLegacyTab] = useState<LegacyTab>('batchimport');

  return (
    <div className="flex h-full flex-col gap-4" data-operator-page="data-processing">
      <OperatorPageHeader
        icon={Database}
        title={language === 'zh' ? '数据处理' : 'Data Processing'}
        subtitle={
          language === 'zh'
            ? '五个子区 + 兼容入口五子页：资产 / 任务 / 质量 / 特征 / 兼容。'
            : 'Assets, jobs, quality, features, and legacy tools.'
        }
      />
      <SegmentedControl<DataHubTab>
        aria-label={language === 'zh' ? '数据处理分区' : 'Data processing sections'}
        value={activeTab}
        onChange={setActiveTab}
        options={[
          { value: 'assets', label: language === 'zh' ? '数据资产' : 'Data Assets', icon: Database },
          { value: 'jobs', label: language === 'zh' ? '生产任务' : 'Production Jobs', icon: Workflow },
          { value: 'quality', label: language === 'zh' ? '质量治理' : 'Quality', icon: ShieldCheck },
          { value: 'features', label: language === 'zh' ? '特征服务' : 'Features', icon: Sparkles },
          { value: 'legacy', label: language === 'zh' ? '兼容入口' : 'Legacy', icon: Compass },
        ]}
      />

      {activeTab === 'assets' && <DataHubDatasetPanel />}
      {activeTab === 'jobs' && <DataHubJobsPanel />}
      {activeTab === 'quality' && <DataQualityPanel />}
      {activeTab === 'features' && <DataHubFeaturePanel />}
      {activeTab === 'legacy' && (
        <div className="space-y-4">
          <SegmentedControl<LegacyTab>
            aria-label={language === 'zh' ? '兼容工具' : 'Legacy tools'}
            size="sm"
            value={legacyTab}
            onChange={setLegacyTab}
            options={[
              { value: 'batchimport', label: language === 'zh' ? '批量导入' : 'Import', icon: Download },
              { value: 'datadev', label: language === 'zh' ? '数据开发' : 'Data Dev', icon: Package },
              { value: 'database', label: language === 'zh' ? '数据库' : 'Database', icon: Database },
              { value: 'sql', label: 'SQL', icon: FileCode2 },
              { value: 'repair', label: language === 'zh' ? '回补修复' : 'Repair', icon: Wrench },
            ]}
          />
          {legacyTab === 'batchimport' && <BatchImportPanel />}
          {legacyTab === 'datadev' && <DataDevManager />}
          {legacyTab === 'database' && <DatabaseManager />}
          {legacyTab === 'sql' && <SQLWorkbench />}
          {legacyTab === 'repair' && <BackfillRepairPanel />}
        </div>
      )}
    </div>
  );
};

export default DataProcessingAnalysis;
