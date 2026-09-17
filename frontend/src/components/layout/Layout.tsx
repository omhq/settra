import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Activity,
  ChevronDown,
  Database,
  ListTree,
  LogOut,
  Settings,
  UserRound,
  Workflow,
} from "lucide-react";

import { ActionMenu } from "@/components/ui/action-menu";
import {
  dataSections,
  isDataSectionActive,
} from "@/components/data/data-navigation";
import { CollapsibleColumn } from "@/components/ui/collapsible-column";
import { Tooltip } from "@/components/ui/tooltip";
import { useDeploymentMode, useProductName } from "@/config/product-provider";
import { cn } from "@/lib/utils";
import { useAuth } from "@/auth/auth-provider";
import logo from "@/logo-dark.svg";

const nav = [
  { label: "Requests", href: "/requests", icon: ListTree },
  { label: "Status", href: "/status", icon: Activity },
  { label: "Settings", href: "/settings", icon: Settings },
];

export default function Layout({
  children,
  showNavigation = true,
}: {
  children: ReactNode;
  showNavigation?: boolean;
}) {
  const location = useLocation();
  const productName = useProductName();
  const deploymentMode = useDeploymentMode();
  const auth = useAuth();
  const { pathname } = location;
  const [collapsed, setCollapsed] = useState(false);
  const dataActive = pathname === "/data" || pathname.startsWith("/data/");
  const [dataExpanded, setDataExpanded] = useState(dataActive);
  const visibleNav = nav.filter(
    (item) => item.href !== "/status" || deploymentMode === "self_hosted",
  );

  useEffect(() => {
    if (dataActive) setDataExpanded(true);
  }, [pathname, dataActive]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px), (max-height: 680px)");
    const collapseWhenCompact = () => {
      if (media.matches) setCollapsed(true);
    };

    collapseWhenCompact();
    media.addEventListener("change", collapseWhenCompact);
    return () => media.removeEventListener("change", collapseWhenCompact);
  }, []);

  const dataToggle = (
    <button
      type="button"
      aria-label="Data"
      aria-expanded={!collapsed && dataExpanded}
      aria-controls="data-navigation"
      onClick={() => {
        if (collapsed) {
          setCollapsed(false);
          setDataExpanded(true);
        } else {
          setDataExpanded((expanded) => !expanded);
        }
      }}
      className={cn(
        "relative inline-flex h-9 items-center rounded-lg text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        collapsed ? "w-9 justify-center" : "w-full gap-2 px-2.5",
        dataActive
          ? "bg-muted font-medium text-foreground"
          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
      )}
    >
      <Database className="size-4 shrink-0" />
      <span className={cn(collapsed && "sr-only")}>Data</span>
      {!collapsed && (
        <ChevronDown
          className={cn(
            "ml-auto size-3.5 transition-transform",
            !dataExpanded && "-rotate-90",
          )}
        />
      )}
    </button>
  );

  return (
    <div className="min-h-screen bg-[#144bc6] dark:bg-[#176be7]">
      <header className="flex h-12 w-full items-center justify-between px-5 sm:px-6">
        <Link
          to={showNavigation ? "/data" : "/login"}
          className="inline-flex items-center text-white"
        >
          <img className="h-5 w-auto" src={logo} alt={productName} />
        </Link>
        <div className="flex items-center gap-3 text-white">
          {showNavigation && (
            <ActionMenu
              label="Open account menu"
              triggerIcon={<UserRound className="size-4" />}
              triggerClassName="rounded-full border-white/50 bg-white/10 text-white hover:border-white/70 hover:bg-white/20 hover:text-white aria-expanded:border-white/70 aria-expanded:bg-white/20 aria-expanded:text-white dark:hover:bg-white/20"
              actions={[
                {
                  label: "Sign out",
                  icon: <LogOut className="size-4" />,
                  onSelect: () => void auth.logout(),
                },
              ]}
            />
          )}
        </div>
      </header>

      <div className="h-[calc(100vh-3rem)] min-h-0 w-full overflow-hidden rounded-t-2xl bg-background shadow-sm">
        {showNavigation ? (
          <div
            className={cn(
              "grid h-full min-h-0 transition-[grid-template-columns] duration-200",
              collapsed
                ? "grid-cols-[4rem_minmax(0,1fr)]"
                : "grid-cols-[13rem_minmax(0,1fr)]",
            )}
          >
            <CollapsibleColumn
              collapsed={collapsed}
              className="border-r"
              collapseLabel="Collapse navigation"
              expandLabel="Expand navigation"
              onCollapsedChange={setCollapsed}
            >
              <nav
                className={cn(
                  "flex h-full min-h-0 flex-col gap-1 overflow-y-auto pb-3 pt-6",
                  collapsed ? "items-center px-2" : "px-3",
                )}
              >
                <div className={cn(!collapsed && "space-y-1")}>
                  {collapsed ? (
                    <Tooltip content="Data" side="right">
                      {dataToggle}
                    </Tooltip>
                  ) : (
                    dataToggle
                  )}
                  <div
                    id="data-navigation"
                    hidden={collapsed || !dataExpanded}
                    className="ml-4 space-y-1 border-l pl-2"
                  >
                    {dataSections.map((item) => {
                      const Icon = item.icon;
                      const active = isDataSectionActive(pathname, item.href);
                      return (
                        <Link
                          key={item.href}
                          to={item.href}
                          aria-current={active ? "page" : undefined}
                          className={cn(
                            "flex h-8 items-center gap-2 rounded-lg px-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            active
                              ? "bg-muted font-medium text-foreground"
                              : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                          )}
                        >
                          <Icon className="size-3.5 shrink-0" />
                          {item.label}
                        </Link>
                      );
                    })}
                  </div>
                </div>
                {visibleNav.map((item) => {
                  const Icon = item.icon;
                  const active =
                    pathname === item.href ||
                    pathname.startsWith(`${item.href}/`);

                  const link = (
                    <Link
                      key={item.href}
                      to={item.href}
                      aria-label={item.label}
                      className={cn(
                        "group/nav-link relative inline-flex h-9 items-center rounded-lg text-sm transition-colors",
                        collapsed ? "w-9 justify-center px-0" : "gap-2 px-2.5",
                        active
                          ? "bg-muted font-medium text-foreground"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                      )}
                    >
                      <Icon className="size-4" />
                      <span className={cn(collapsed && "sr-only")}>
                        {item.label}
                      </span>
                    </Link>
                  );

                  if (!collapsed) return link;

                  return (
                    <Tooltip key={item.href} content={item.label} side="right">
                      {link}
                    </Tooltip>
                  );
                })}
              </nav>
            </CollapsibleColumn>

            <main className="min-h-0 min-w-0 overflow-hidden">{children}</main>
          </div>
        ) : (
          <main className="h-full min-h-0 min-w-0 overflow-hidden">
            {children}
          </main>
        )}
      </div>
    </div>
  );
}
