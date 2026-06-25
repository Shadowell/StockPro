type AshareGuardrail = {
  label: string;
  detail: string;
};

type AshareGuardrailStripProps = {
  title: string;
  description: string;
  items: AshareGuardrail[];
};

export function AshareGuardrailStrip({ title, description, items }: AshareGuardrailStripProps) {
  return (
    <section className="rounded-xl border border-blue-500/20 bg-blue-500/[0.06] p-4 shadow-sm shadow-black/20" aria-label={title}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-sm font-black text-blue-100">{title}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
        </div>
        <div className="grid min-w-0 gap-2 sm:grid-cols-3 lg:min-w-[620px]">
          {items.map((item) => (
            <div key={item.label} className="min-w-0 rounded-lg border border-crypto-border bg-crypto-card/80 px-3 py-2">
              <div className="truncate text-xs font-black text-slate-100">{item.label}</div>
              <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{item.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
