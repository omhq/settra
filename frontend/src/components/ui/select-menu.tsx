import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useMenuPlacement } from "@/components/ui/use-menu-placement";
import { cn } from "@/lib/utils";

export type SelectMenuOption = {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
  meta?: ReactNode;
};

const MENU_MAX_HEIGHT = 288;

export function SelectMenu({
  options,
  value,
  onChange,
  placeholder = "Select option",
  disabled,
  className,
  triggerClassName,
}: {
  options: SelectMenuOption[];
  value: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const { maxHeight, placement } = useMenuPlacement({
    open,
    rootRef,
    menuRef,
    preferredMaxHeight: MENU_MAX_HEIGHT,
  });
  const selectedOption = useMemo(
    () => options.find((option) => option.value === value) ?? null,
    [options, value],
  );

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  function selectOption(option: SelectMenuOption) {
    if (option.disabled) return;
    onChange(option.value);
    setOpen(false);
  }

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <Button
        type="button"
        variant="outline"
        disabled={disabled}
        aria-expanded={open}
        className={cn(
          "h-8 w-full min-w-52 justify-between gap-2 px-2.5 text-left",
          triggerClassName,
        )}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
          {selectedOption ? (
            <span className="truncate">{selectedOption.label}</span>
          ) : (
            <span className="truncate text-muted-foreground">
              {placeholder}
            </span>
          )}
        </span>
        <ChevronDown
          className={cn(
            "size-4 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </Button>

      {open && !disabled && (
        <div
          ref={menuRef}
          role="listbox"
          style={{ maxHeight }}
          className={cn(
            "absolute right-0 z-30 w-full min-w-60 overflow-y-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg",
            placement === "top" ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          {options.map((option) => {
            const selected = option.value === value;

            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={selected}
                disabled={option.disabled}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none",
                  option.disabled && "cursor-not-allowed opacity-50",
                )}
                onClick={() => selectOption(option)}
              >
                <span className="grid size-4 shrink-0 place-items-center">
                  {selected && <Check className="size-3.5" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {option.label}
                  </span>
                  {option.description && (
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {option.description}
                    </span>
                  )}
                </span>
                {option.meta}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
