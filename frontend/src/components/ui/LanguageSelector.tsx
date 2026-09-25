"use client";

import { Globe, Loader2 } from "lucide-react";

export type Language = "english" | "hindi" | "kannada" | "telugu" | "tamil";

export const LANGUAGE_OPTIONS: { value: Language; label: string; native: string }[] = [
  { value: "english", label: "English",  native: "English"  },
  { value: "hindi",   label: "Hindi",    native: "हिन्दी"   },
  { value: "kannada", label: "Kannada",  native: "ಕನ್ನಡ"   },
  { value: "telugu",  label: "Telugu",   native: "తెలుగు"  },
  { value: "tamil",   label: "Tamil",    native: "தமிழ்"    },
];

interface Props {
  value: Language;
  onChange: (lang: Language) => void;
  translating?: boolean;
  className?: string;
}

export function LanguageSelector({ value, onChange, translating, className }: Props) {
  return (
    <div className={`flex items-center gap-1.5 ${className ?? ""}`}>
      {translating
        ? <Loader2 className="h-3.5 w-3.5 text-indigo-500 animate-spin" />
        : <Globe className="h-3.5 w-3.5 text-slate-400" />
      }
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Language)}
        disabled={translating}
        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 shadow-sm focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-300 disabled:opacity-60 cursor-pointer"
      >
        {LANGUAGE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.native}{opt.value !== "english" ? ` (${opt.label})` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
