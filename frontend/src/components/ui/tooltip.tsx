import {
  type FocusEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

type TooltipSide = "top" | "right" | "bottom" | "left";

type TooltipPosition = {
  left: number;
  top: number;
  transform: string;
};

const sideTransforms: Record<TooltipSide, string> = {
  top: "translate(-50%, calc(-100% - 8px))",
  right: "translate(8px, -50%)",
  bottom: "translate(-50%, 8px)",
  left: "translate(calc(-100% - 8px), -50%)",
};

export function Tooltip({
  children,
  content,
  side = "top",
  className,
}: {
  children: ReactNode;
  content: ReactNode;
  side?: TooltipSide;
  className?: string;
}) {
  const triggerRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<TooltipPosition | null>(null);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;

    const rect = trigger.getBoundingClientRect();

    if (side === "top") {
      setPosition({
        left: rect.left + rect.width / 2,
        top: rect.top,
        transform: sideTransforms.top,
      });
      return;
    }

    if (side === "right") {
      setPosition({
        left: rect.right,
        top: rect.top + rect.height / 2,
        transform: sideTransforms.right,
      });
      return;
    }

    if (side === "bottom") {
      setPosition({
        left: rect.left + rect.width / 2,
        top: rect.bottom,
        transform: sideTransforms.bottom,
      });
      return;
    }

    setPosition({
      left: rect.left,
      top: rect.top + rect.height / 2,
      transform: sideTransforms.left,
    });
  }, [side]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open) return;

    const handleLayoutChange = () => updatePosition();
    window.addEventListener("resize", handleLayoutChange);
    window.addEventListener("scroll", handleLayoutChange, true);

    return () => {
      window.removeEventListener("resize", handleLayoutChange);
      window.removeEventListener("scroll", handleLayoutChange, true);
    };
  }, [open, updatePosition]);

  const handleBlur = (event: FocusEvent<HTMLSpanElement>) => {
    if (event.currentTarget.contains(event.relatedTarget as Node | null))
      return;
    setOpen(false);
  };

  const tooltipNode =
    open && position && typeof document !== "undefined"
      ? createPortal(
          <span
            role="tooltip"
            className="pointer-events-none fixed z-[80] whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs font-medium text-popover-foreground shadow-sm"
            style={{
              left: `${position.left}px`,
              top: `${position.top}px`,
              transform: position.transform,
            }}
          >
            {content}
          </span>,
          document.body,
        )
      : null;

  return (
    <span
      ref={triggerRef}
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => {
        updatePosition();
        setOpen(true);
      }}
      onMouseLeave={() => setOpen(false)}
      onFocusCapture={() => {
        updatePosition();
        setOpen(true);
      }}
      onBlurCapture={handleBlur}
    >
      {children}
      {tooltipNode}
    </span>
  );
}
