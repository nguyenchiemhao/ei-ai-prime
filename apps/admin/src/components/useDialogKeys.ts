import { type KeyboardEvent, type RefObject, useEffect, useRef } from "react";

const FOCUSABLE = "input:not([disabled]), select:not([disabled]), button:not([disabled])";

/**
 * Keyboard and focus handling of a modal dialog: Escape closes it, Tab stays inside it, focus
 * returns to the opening element when it unmounts, and focus that falls to the page body (for
 * example when the focused button becomes disabled) moves back into the dialog.
 * Call it before the component's own autofocus effect.
 * Input: the dialog element ref and the close callback.
 * Output: a keydown handler for the dialog element.
 */
export function useDialogKeys(
  dialogRef: RefObject<HTMLElement | null>,
  onClose: () => void,
): (event: KeyboardEvent) => void {
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    openerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const opener = openerRef.current;
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || document.activeElement !== document.body) return;
    dialog.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  });

  return (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
}
