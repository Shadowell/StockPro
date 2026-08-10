type DiagnosticField = readonly [label: string, value: unknown];

const rawValue = (value: unknown) => {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

export function DiagnosticDetails({
  ariaLabel,
  fields,
}: {
  ariaLabel: string;
  fields: DiagnosticField[];
}) {
  return (
    <details
      role="group"
      aria-label={ariaLabel}
      className="mt-2 rounded-md border border-white/[0.06] bg-black/10 px-2.5 py-1.5 text-[10px] text-slate-500"
    >
      <summary className="cursor-pointer select-none font-medium text-slate-500 hover:text-slate-300">
        查看诊断原值
      </summary>
      <dl className="mt-2 space-y-1.5 border-t border-white/[0.05] pt-2">
        {fields.map(([label, value]) => (
          <div key={label} className="grid gap-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <dt className="font-mono text-slate-600">{label}</dt>
            <dd className="break-all font-mono text-slate-400">{rawValue(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
