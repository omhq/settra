import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { api, type DeploymentMode } from "@/lib/api";
import { PRODUCT_NAME } from "@/config/product";

const ProductNameContext = createContext(PRODUCT_NAME);
const DeploymentModeContext = createContext<DeploymentMode | null>(null);

export function ProductProvider({ children }: { children: ReactNode }) {
  const [productName, setProductName] = useState(PRODUCT_NAME);
  const [deploymentMode, setDeploymentMode] = useState<DeploymentMode | null>(
    null,
  );

  useEffect(() => {
    let active = true;

    api.settings
      .product()
      .then((settings) => {
        const configuredName = settings.product_name.trim();
        if (active && configuredName) setProductName(configuredName);
        if (active) {
          setDeploymentMode(
            settings.deployment_mode === "managed" ? "managed" : "self_hosted",
          );
        }
      })
      .catch(() => {
        // The frontend build name remains available if the backend is offline.
        if (active) setDeploymentMode("self_hosted");
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    document.title = `${productName} — Sheet data for agents`;
  }, [productName]);

  return (
    <DeploymentModeContext.Provider value={deploymentMode}>
      <ProductNameContext.Provider value={productName}>
        {children}
      </ProductNameContext.Provider>
    </DeploymentModeContext.Provider>
  );
}

export function useProductName(): string {
  return useContext(ProductNameContext);
}

export function useDeploymentMode(): DeploymentMode | null {
  return useContext(DeploymentModeContext);
}
