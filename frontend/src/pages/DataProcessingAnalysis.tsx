import React, { useState } from 'react';
import { MainLayout } from '@/components/MainLayout';
import { useStore } from '@/stores/useStore';
import { getTranslation } from '@/lib/i18n';
import { Database, Download } from 'lucide-react';
import { DatabaseManager } from '@/components/DatabaseManager';
import { BatchImportPanel } from '@/components/BatchImportPanel';

export const DataProcessingAnalysis: React.FC = () => {
  const { language } = useStore();
  const t = (key: any) => getTranslation(language, key);

  const [activeTab, setActiveTab] = useState<'database' | 'batchimport'>('database');

  return (
    <MainLayout title={language === 'zh' ? '数据中心' : 'Data Center'}>
      <div className="flex flex-col gap-6 h-full">
        {/* Tab Selector */}
        <div className="flex border-b border-slate-800 bg-[#0d121f]">
          <button
            className={`px-6 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'database'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('database')}
          >
            <Database size={16} />
            {language === 'zh' ? '数据库管理' : 'Database Management'}
          </button>
          <button
            className={`px-6 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'batchimport'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('batchimport')}
          >
            <Download size={16} />
            {language === 'zh' ? '批量导入' : 'Batch Import'}
          </button>
        </div>

        {/* Database Management Tab */}
        {activeTab === 'database' && (
          <div className="flex-1">
            <DatabaseManager />
          </div>
        )}

        {/* Batch Import Tab */}
        {activeTab === 'batchimport' && (
          <div className="flex-1">
            <BatchImportPanel />
          </div>
        )}
      </div>
    </MainLayout>
  );
};
