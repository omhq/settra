import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModalProvider } from "@/components/ui/global-modal";
import { GlobalToastContainer } from "@/components/ui/global-toast";
import { ProductProvider } from "@/config/product-provider";
import { ThemeProvider } from "@/config/theme-provider";
import { AuthProvider } from "@/auth/auth-provider";
import { PRODUCT_NAME } from "@/config/product";
import { WorkspaceEventsProvider } from "@/realtime/workspace-events";
import App from "./App";

import "react-toastify/dist/ReactToastify.css";
import "./index.css";

document.title = PRODUCT_NAME;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: true,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

const router = createBrowserRouter([
  {
    path: "*",
    element: (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <WorkspaceEventsProvider>
            <ModalProvider>
              <App />
              <GlobalToastContainer />
            </ModalProvider>
          </WorkspaceEventsProvider>
        </AuthProvider>
      </QueryClientProvider>
    ),
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ProductProvider>
        <RouterProvider router={router} />
      </ProductProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
