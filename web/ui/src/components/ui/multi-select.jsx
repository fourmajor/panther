import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Search, X } from "lucide-react";
import { Input } from "./input.jsx";
import { Button } from "./button.jsx";
import { matchingOptions, addSelection } from "./multi-select-options.js";

// The shadcn Input/Button composition with the WAI-ARIA editable combobox
// pattern. The popup is portalled so filter bars cannot clip its suggestions.
export function MultiSelect({ label, options = [], value = [], onChange, placeholder, disabled = false }) {
  const id = useId();
  const input = useRef(null);
  const wrapper = useRef(null);
  const popup = useRef(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState(null);
  const matches = matchingOptions(options, value, query);
  const highlighted = Math.min(active, Math.max(0, matches.length - 1));
  const selectedNames = new Map(options.map(option => [option.id, option.name ?? option.label ?? option.id]));
  const choose = option => {
    if (!option || disabled) return;
    onChange(addSelection(value, option.id));
    setQuery("");
    setActive(0);
    setOpen(true);
    input.current?.focus();
  };
  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const rect = input.current?.getBoundingClientRect();
      if (!rect) return;
      const below = window.innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const upward = below < 150 && above > below;
      setPosition({ left: rect.left, width: rect.width, maxHeight: Math.max(60, Math.min(260, upward ? above : below)), ...(upward ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }) });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => { window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const dismiss = event => {
      if (!wrapper.current?.contains(event.target) && !popup.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", dismiss);
    return () => { document.removeEventListener("pointerdown", dismiss); document.removeEventListener("focusin", dismiss); };
  }, [open]);
  useEffect(() => {
    popup.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [highlighted, query, value, open]);
  return <div ref={wrapper} className="panther-multi-select grid min-w-0 gap-2">
    <label htmlFor={`${id}-input`} className="text-sm font-medium">{label}</label>
    <div className="relative">
      <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-3 opacity-60" />
      <Input ref={input} id={`${id}-input`} role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={`${id}-list`} aria-activedescendant={open && matches.length ? `${id}-option-${highlighted}` : undefined} autoComplete="off" placeholder={placeholder ?? `Add ${label.toLocaleLowerCase()}`} disabled={disabled} value={query} className="pl-9" style={{ width: "100%", paddingLeft: "2.25rem" }} onFocus={() => setOpen(true)} onChange={event => { setQuery(event.target.value); setActive(0); setOpen(true); }} onKeyDown={event => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const direction = event.key === "ArrowDown" ? 1 : -1;
          setActive(open && matches.length ? (highlighted + direction + matches.length) % matches.length : 0);
          setOpen(true);
        } else if (event.key === "Enter") {
          event.preventDefault();
          if (open) choose(matches[highlighted]);
          else setOpen(true);
        } else if (event.key === "Escape") {
          event.preventDefault(); setOpen(false);
        } else if (event.key === "Tab") {
          setOpen(false);
        } else if (event.key === "Backspace" && !query && value.length) {
          event.preventDefault(); onChange(value.slice(0, -1)); setActive(0);
        }
      }} />
    </div>
    {value.length > 0 && <div className="flex flex-wrap gap-1.5" aria-label={`Selected ${label.toLocaleLowerCase()}`}>
      {value.map(selected => <span key={selected} className="inline-flex max-w-full items-center gap-1 rounded-md border py-0.5 pl-2 text-sm" style={{ borderColor: "var(--line)", background: "var(--panel-raised)", color: "var(--ink)" }}>
        <span className="min-w-0 truncate">{selectedNames.get(selected) ?? selected}</span>
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 p-0" style={{ width: "1.75rem", height: "1.75rem", padding: 0, minHeight: 0 }} aria-label={`Remove ${selectedNames.get(selected) ?? selected} from ${label.toLocaleLowerCase()}`} disabled={disabled} onClick={() => { onChange(value.filter(item => item !== selected)); setActive(0); }}><X size={14} aria-hidden="true" /></Button>
      </span>)}
    </div>}
    {open && position && createPortal(<div ref={popup} id={`${id}-list`} role="listbox" aria-label={`${label} suggestions`} className="panther-multi-select-popup fixed z-50 overflow-y-auto rounded-md border p-1 shadow-lg" style={{ ...position, zIndex: 1000, background: "var(--panel-raised)", borderColor: "var(--line)", color: "var(--ink)" }}>
      {matches.length ? matches.map((option, index) => <div key={option.id} id={`${id}-option-${index}`} role="option" aria-selected={index === highlighted} className="cursor-pointer rounded-sm px-3 py-2 text-sm outline-none" style={index === highlighted ? { background: "var(--accent-dark)", color: "var(--accent)" } : undefined} onPointerMove={() => setActive(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(option)}>{option.name ?? option.label ?? option.id}</div>) : <div role="status" className="px-3 py-2 text-sm opacity-60">No matches</div>}
    </div>, document.body)}
  </div>;
}
