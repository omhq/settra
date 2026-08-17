import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { api } from "@/lib/api";
import { PRODUCT_NAME } from "@/config/product";

const ProductNameContext = createContext(PRODUCT_NAME);

export function ProductProvider({ children }: { children: ReactNode }) {
  const [productName, setProductName] = useState(PRODUCT_NAME);

  useEffect(() => {
    let active = true;

    api.settings
      .product()
      .then((settings) => {
        const configuredName = settings.product_name.trim();
        if (active && configuredName) setProductName(configuredName);
      })
      .catch(() => {
        // The frontend build name remains available if the backend is offline.
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    document.title = `${productName} — Sheet data for agents`;
  }, [productName]);

  return (
    <ProductNameContext.Provider value={productName}>
      {children}
    </ProductNameContext.Provider>
  );
}

export function useProductName(): string {
  return useContext(ProductNameContext);
}
