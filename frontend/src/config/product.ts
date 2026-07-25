const DEFAULT_PRODUCT_NAME = "Settra";

const configuredProductName = import.meta.env.VITE_PRODUCT_NAME?.trim();

export const PRODUCT_NAME = configuredProductName || DEFAULT_PRODUCT_NAME;

export function productSlug(productName: string): string {
  return (
    productName
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "app"
  );
}
