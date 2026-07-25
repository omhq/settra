import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ModalProvider } from "@/components/ui/global-modal";
import { ProductProvider } from "@/config/product-provider";
import { PRODUCT_NAME } from "@/config/product";
import App from "./App";

import "./index.css";

document.title = PRODUCT_NAME;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ProductProvider>
      <BrowserRouter>
        <ModalProvider>
          <App />
        </ModalProvider>
      </BrowserRouter>
    </ProductProvider>
  </React.StrictMode>,
);
