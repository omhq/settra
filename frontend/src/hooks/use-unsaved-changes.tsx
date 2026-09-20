import { useCallback, useEffect } from "react";
import { useBeforeUnload, useBlocker } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";

export function useUnsavedChanges({
  dirty,
  title,
  message,
}: {
  dirty: boolean;
  title: string;
  message: string;
}) {
  const { openModal } = useModal();
  const shouldBlock = useCallback(
    ({
      currentLocation,
      nextLocation,
    }: {
      currentLocation: LocationLike;
      nextLocation: LocationLike;
    }) => dirty && locationKey(currentLocation) !== locationKey(nextLocation),
    [dirty],
  );
  const blocker = useBlocker(shouldBlock);

  useBeforeUnload(
    useCallback(
      (event) => {
        if (!dirty) return;
        event.preventDefault();
        event.returnValue = "";
      },
      [dirty],
    ),
  );

  useEffect(() => {
    if (blocker.state !== "blocked") return;

    openModal({
      title,
      body: <p>{message}</p>,
      closeOnBackdrop: false,
      closeOnEscape: false,
      showCloseButton: false,
      actions: ({ close }) => (
        <>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              close();
              blocker.reset();
            }}
          >
            Keep editing
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              close();
              blocker.proceed();
            }}
          >
            Discard changes
          </Button>
        </>
      ),
    });
  }, [blocker, message, openModal, title]);
}

type LocationLike = {
  pathname: string;
  search: string;
  hash: string;
};

function locationKey(location: LocationLike) {
  return location.pathname + location.search + location.hash;
}
