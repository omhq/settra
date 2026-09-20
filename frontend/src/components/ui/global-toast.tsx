import { ToastContainer, toast, type ToastOptions } from "react-toastify";

import { useTheme } from "@/config/theme-provider";

const DEFAULT_AUTO_CLOSE = 3500;

function options(
  kind: "success" | "error" | "info" | "warning",
  message: string,
  overrides?: ToastOptions,
): ToastOptions {
  return {
    toastId: `${kind}:${message}`,
    ...overrides,
  };
}

export const notify = {
  success(message: string, overrides?: ToastOptions) {
    return toast.success(message, options("success", message, overrides));
  },
  error(message: string, overrides?: ToastOptions) {
    return toast.error(message, options("error", message, overrides));
  },
  info(message: string, overrides?: ToastOptions) {
    return toast.info(message, options("info", message, overrides));
  },
  warning(message: string, overrides?: ToastOptions) {
    return toast.warning(message, options("warning", message, overrides));
  },
};

export function GlobalToastContainer() {
  const { theme } = useTheme();

  return (
    <ToastContainer
      position="bottom-right"
      autoClose={DEFAULT_AUTO_CLOSE}
      hideProgressBar
      newestOnTop
      closeOnClick
      pauseOnFocusLoss
      pauseOnHover
      draggable
      limit={4}
      theme={theme}
      aria-label="Notifications"
    />
  );
}
