export type DataStatus={storage:'postgresql';provider_state:'ready'|'restricted'|'unavailable';datasets:number;published_partitions:number;published_rows:number;sealed_snapshots:number;sync_jobs:number;quality_issues:number;staged_imports:number;provider_calls_performed:number}
export type DatasetRecord=Record<string,any>&{id:number;code:string;name:string;primary_source:string;fallback_source?:string|null;enabled:boolean;partition_count:number;row_count:number}
export type SnapshotRecord=Record<string,any>&{id:number;name:string;status:string;knowledge_cutoff_at:string;item_count:number}
export type DataJob=Record<string,any>&{id:number;job_name:string;source:string;status:string;created_at:string}
export type ExtensionImport=Record<string,any>&{id:string;name:string;file_format:string;status:string;row_count:number;mapping_state?:string;created_at:string}
