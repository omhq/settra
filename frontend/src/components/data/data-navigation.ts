import { Cloud, FileSpreadsheet, FolderOpen } from "lucide-react";

export const dataSections = [
  { label: "Connections", href: "/data", icon: Cloud },
  { label: "Sources", href: "/data/sources", icon: FileSpreadsheet },
  { label: "Apps", href: "/data/apps", icon: FolderOpen },
];

export function isDataSectionActive(pathname: string, href: string) {
  if (href === "/data") return pathname === "/data" || pathname === "/data/";
  if (
    href === "/data/sources" &&
    /^\/data\/(new|\d+\/edit)\/?$/.test(pathname)
  ) {
    return true;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}
