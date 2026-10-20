import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

const ITEM_SELECTOR = '[role="menuitem"], [role="menuitemradio"]';

/** Open state, outside-click, Escape and arrow-key handling shared by the Sidebar menus. */
export function useMenu() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    buttonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const items = rootRef.current?.querySelectorAll<HTMLElement>(ITEM_SELECTOR);
    const checked = rootRef.current?.querySelector<HTMLElement>('[aria-checked="true"]');
    (checked ?? items?.[0])?.focus();
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const onKeyDown = (event: KeyboardEvent) => {
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "Tab") {
      setOpen(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const items = Array.from(rootRef.current?.querySelectorAll<HTMLElement>(ITEM_SELECTOR) ?? []);
      if (items.length === 0) return;
      const index = items.indexOf(document.activeElement as HTMLElement);
      const step = event.key === "ArrowDown" ? 1 : -1;
      items[(index + step + items.length) % items.length]?.focus();
    }
  };

  return { open, setOpen, close, rootRef, buttonRef, onKeyDown };
}
