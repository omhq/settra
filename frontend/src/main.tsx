import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { ModalProvider } from "@/components/ui/global-modal";
import { GlobalToastContainer } from "@/components/ui/global-toast";
import { ProductProvider } from "@/config/product-provider";
import { ThemeProvider } from "@/config/theme-provider";
import { AuthProvider } from "@/auth/auth-provider";
import { PRODUCT_NAME } from "@/config/product";
import App from "./App";

import "react-toastify/dist/ReactToastify.css";
import "./index.css";

document.title = PRODUCT_NAME;

const router = createBrowserRouter([
  {
    path: "*",
    element: (
      <AuthProvider>
        <ModalProvider>
          <App />
          <GlobalToastContainer />
        </ModalProvider>
      </AuthProvider>
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
