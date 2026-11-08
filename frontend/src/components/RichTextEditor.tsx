import { useEffect, useRef } from "react";

/** Minimal dependency-free rich text editor (bold / italic / underline / lists). HTML is sanitized server-side. */
export default function RichTextEditor({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== value) ref.current.innerHTML = value || "";
  }, [value]);

  const cmd = (c: string) => {
    ref.current?.focus();
    document.execCommand(c);
    onChange(ref.current?.innerHTML ?? "");
  };

  const btn = "rounded px-2 py-1 text-sm text-slate-700 hover:bg-slate-200";
  return (
    <div className="rounded-lg border border-slate-300 focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500">
      <div className="flex gap-1 border-b border-slate-200 bg-slate-50 px-2 py-1">
        <button type="button" className={`${btn} font-bold`} onClick={() => cmd("bold")} aria-label="Bold">B</button>
        <button type="button" className={`${btn} italic`} onClick={() => cmd("italic")} aria-label="Italic">I</button>
        <button type="button" className={`${btn} underline`} onClick={() => cmd("underline")} aria-label="Underline">U</button>
        <button type="button" className={btn} onClick={() => cmd("insertUnorderedList")} aria-label="Bullet list">• List</button>
        <button type="button" className={btn} onClick={() => cmd("insertOrderedList")} aria-label="Numbered list">1. List</button>
      </div>
      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        data-placeholder={placeholder}
        onInput={() => onChange(ref.current?.innerHTML ?? "")}
        className="rich-text min-h-[140px] px-3 py-2 text-sm text-slate-800 focus:outline-none"
      />
    </div>
  );
}
