/**
 * Shared research-desk chrome used to sit under every workspace header
 * (多因子风险预算 / 本页就绪 / 继续盯盘). The operator asked it off the
 * workspace shell. Keep the export so existing page mounts stay compile-safe;
 * the backend GET /workflow/research-desk contract is unchanged.
 */
export function WorkspacePipelineNote({ stageId }: { stageId: string }) {
  void stageId;
  return null;
}
