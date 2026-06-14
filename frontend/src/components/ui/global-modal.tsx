import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ModalControls = {
  close: () => void;
};

type ModalSlot = ReactNode | ((controls: ModalControls) => ReactNode);

type ModalOptions = {
  title: ReactNode;
  body?: ModalSlot;
  actions?: ModalSlot;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
};

type ModalContextValue = {
  openModal: (options: ModalOptions) => void;
  closeModal: () => void;
};

const ModalContext = createContext<ModalContextValue | null>(null);

function renderSlot(slot: ModalSlot | undefined, controls: ModalControls) {
  if (typeof slot === "function") return slot(controls);
  return slot;
}

export function ModalProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<ModalOptions | null>(null);
  const titleId = useId();
  const bodyId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);

  const closeModal = useCallback(() => setModal(null), []);
  const openModal = useCallback(
    (options: ModalOptions) => setModal(options),
    [],
  );
  const controls = useMemo(() => ({ close: closeModal }), [closeModal]);
  const value = useMemo(
    () => ({ openModal, closeModal }),
    [openModal, closeModal],
  );

  useEffect(() => {
    if (!modal || modal.closeOnEscape === false) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeModal();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [closeModal, modal]);

  useEffect(() => {
    if (!modal) return;

    const previousActiveElement =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;

    document.body.style.overflow = "hidden";
    window.setTimeout(() => dialogRef.current?.focus(), 0);

    return () => {
      document.body.style.overflow = previousOverflow;
      previousActiveElement?.focus();
    };
  }, [modal]);

  const modalContent =
    modal && typeof document !== "undefined"
      ? createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            onMouseDown={() => {
              if (modal.closeOnBackdrop !== false) closeModal();
            }}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby={titleId}
              aria-describedby={modal.body ? bodyId : undefined}
              tabIndex={-1}
              ref={dialogRef}
              className="w-full max-w-md rounded-lg border bg-background p-5 shadow-lg"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-4">
                <h2 id={titleId} className="text-base font-semibold">
                  {modal.title}
                </h2>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8 text-muted-foreground hover:text-foreground"
                  aria-label="Close modal"
                  onClick={closeModal}
                >
                  <X className="size-4" />
                </Button>
              </div>

              {modal.body && (
                <div id={bodyId} className="mt-3 text-sm text-muted-foreground">
                  {renderSlot(modal.body, controls)}
                </div>
              )}

              {modal.actions && (
                <div
                  className={cn(
                    "mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
                  )}
                >
                  {renderSlot(modal.actions, controls)}
                </div>
              )}
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <ModalContext.Provider value={value}>
      {children}
      {modalContent}
    </ModalContext.Provider>
  );
}

export function useModal() {
  const context = useContext(ModalContext);
  if (!context) throw new Error("useModal must be used inside ModalProvider");
  return context;
}
