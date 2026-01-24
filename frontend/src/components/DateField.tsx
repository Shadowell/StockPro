import React from "react";
import { CalendarDays } from "lucide-react";

type DateFieldProps = {
  value: string;
  text: string;
  onTextChange: (next: string) => void;
  onDatePick: (isoDate: string) => void;
  onBlur?: () => void;
  placeholder?: string;
  className?: string;
};

export const DateField: React.FC<DateFieldProps> = ({
  value,
  text,
  onTextChange,
  onDatePick,
  onBlur,
  placeholder,
  className,
}) => {
  return (
    <div className={`relative mt-1 ${className ?? ""}`}>
      <input
        value={text}
        onChange={(e) => onTextChange(e.target.value)}
        onBlur={onBlur}
        placeholder={placeholder}
        className="w-full px-3 py-2 pr-10 bg-slate-900 border border-slate-700 rounded-md text-sm text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-600"
      />
      <div className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
        <CalendarDays size={18} />
      </div>
      <input
        type="date"
        value={value}
        onChange={(e) => onDatePick(e.target.value)}
        className="absolute inset-y-0 right-0 w-10 opacity-0 cursor-pointer"
        tabIndex={-1}
        aria-hidden="true"
      />
    </div>
  );
};
