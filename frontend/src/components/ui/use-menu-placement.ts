import { useCallback, useLayoutEffect, useState, type RefObject } from "react";

type MenuPlacement = "bottom" | "top";

const MENU_GAP = 4;
const VIEWPORT_PADDING = 12;

export function useMenuPlacement({
  open,
  rootRef,
  menuRef,
  preferredMaxHeight,
}: {
  open: boolean;
  rootRef: RefObject<HTMLElement>;
  menuRef: RefObject<HTMLElement>;
  preferredMaxHeight: number;
}) {
  const [placement, setPlacement] = useState<MenuPlacement>("bottom");
  const [maxHeight, setMaxHeight] = useState(preferredMaxHeight);

  const updatePlacement = useCallback(() => {
    const root = rootRef.current;
    const menu = menuRef.current;
    if (!root || !menu) return;

    const rootRect = root.getBoundingClientRect();
    const spaceBelow =
      window.innerHeight - rootRect.bottom - MENU_GAP - VIEWPORT_PADDING;
    const spaceAbove = rootRect.top - MENU_GAP - VIEWPORT_PADDING;
    const desiredHeight = Math.min(menu.scrollHeight, preferredMaxHeight);
    const nextPlacement =
      spaceBelow < desiredHeight && spaceAbove > spaceBelow ? "top" : "bottom";
    const availableSpace = nextPlacement === "top" ? spaceAbove : spaceBelow;

    setPlacement(nextPlacement);
    setMaxHeight(
      Math.min(preferredMaxHeight, Math.max(0, Math.floor(availableSpace))),
    );
  }, [menuRef, preferredMaxHeight, rootRef]);

  useLayoutEffect(() => {
    if (!open) return;

    updatePlacement();
    window.addEventListener("resize", updatePlacement);
    window.addEventListener("scroll", updatePlacement, true);

    return () => {
      window.removeEventListener("resize", updatePlacement);
      window.removeEventListener("scroll", updatePlacement, true);
    };
  }, [open, updatePlacement]);

  return { maxHeight, placement };
}
