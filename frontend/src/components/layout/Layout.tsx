import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Activity,
  Database,
  ListTree,
  Moon,
  LogOut,
  Network,
  Settings,
  Sun,
} from "lucide-react";

import { CollapsibleColumn } from "@/components/ui/collapsible-column";
import { SelectMenu } from "@/components/ui/select-menu";
import { Tooltip } from "@/components/ui/tooltip";
import { useProductName } from "@/config/product-provider";
import { cn } from "@/lib/utils";
import { useAuth } from "@/auth/auth-provider";
import { api, type AccountOrganization } from "@/lib/api";

const nav = [
  { label: "Data", href: "/data", icon: Database },
  { label: "Semantics", href: "/semantics", icon: Network },
  { label: "Requests", href: "/requests", icon: ListTree },
  { label: "Status", href: "/status", icon: Activity },
  { label: "Settings", href: "/settings", icon: Settings },
];

const THEME_STORAGE_KEY = "app:theme";

type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";

  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (storedTheme === "light" || storedTheme === "dark") return storedTheme;

    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

export default function Layout({
  children,
  showNavigation = true,
}: {
  children: ReactNode;
  showNavigation?: boolean;
}) {
  const location = useLocation();
  const productName = useProductName();
  const auth = useAuth();
  const { pathname } = location;
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [organizations, setOrganizations] = useState<AccountOrganization[]>([]);
  const [switchingOrganization, setSwitchingOrganization] = useState(false);
  const isDark = theme === "dark";

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px), (max-height: 680px)");
    const collapseWhenCompact = () => {
      if (media.matches) setCollapsed(true);
    };

    collapseWhenCompact();
    media.addEventListener("change", collapseWhenCompact);
    return () => media.removeEventListener("change", collapseWhenCompact);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.style.colorScheme = theme;

    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Ignore storage failures; the theme still updates for the active session.
    }
  }, [isDark, theme]);

  useEffect(() => {
    if (!showNavigation || auth.status !== "authenticated") return;

    let active = true;
    api.organizations
      .list()
      .then(({ organizations: values }) => {
        if (active) setOrganizations(values);
      })
      .catch(() => {
        if (active) setOrganizations([]);
      });

    return () => {
      active = false;
    };
  }, [auth.session?.organization.name, auth.status, showNavigation]);

  async function switchOrganization(value: string) {
    const organizationId = Number(value);
    if (organizationId === auth.session?.organization.id) return;

    setSwitchingOrganization(true);
    try {
      await auth.switchOrganization(organizationId);
      window.location.assign("/data");
    } finally {
      setSwitchingOrganization(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#144bc6] dark:bg-[#176be7]">
      <header className="flex h-12 w-full items-center justify-between px-5 sm:px-6">
        <Link
          to={showNavigation ? "/data" : "/login"}
          className="inline-flex items-center text-white"
        >
          <span className="font-semibold tracking-tight">{productName}</span>
        </Link>
        <div className="flex items-center gap-3 text-white">
          {showNavigation && organizations.length > 1 ? (
            <SelectMenu
              value={String(auth.session?.organization.id ?? "")}
              options={organizations.map((organization) => ({
                value: String(organization.id),
                label: organization.name,
                description: organization.role,
              }))}
              disabled={switchingOrganization}
              triggerClassName="min-w-44 border-white/20 bg-white/10 text-white hover:bg-white/20 hover:text-white"
              onChange={(value) => void switchOrganization(value)}
            />
          ) : showNavigation ? (
            <span className="hidden max-w-52 truncate text-xs text-white/80 sm:inline">
              {auth.session?.organization.name}
            </span>
          ) : null}
          <button
            type="button"
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            aria-pressed={isDark}
            className="inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-white/20 bg-white/15 p-0.5 text-white shadow-sm transition-colors hover:bg-white/25 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-white/35"
            onClick={() =>
              setTheme((current) => (current === "dark" ? "light" : "dark"))
            }
          >
            <span
              className={cn(
                "flex size-5 items-center justify-center rounded-full bg-white text-blue-700 shadow-sm transition-transform duration-200",
                isDark && "translate-x-5 bg-blue-950 text-blue-100",
              )}
            >
              {isDark ? (
                <Moon className="size-3" />
              ) : (
                <Sun className="size-3" />
              )}
            </span>
          </button>
          {showNavigation && (
            <button
              type="button"
              aria-label="Sign out"
              title={`Sign out ${auth.session?.user.email ?? ""}`}
              className="inline-flex size-7 items-center justify-center rounded-md text-white/80 transition-colors hover:bg-white/15 hover:text-white"
              onClick={() => void auth.logout()}
            >
              <LogOut className="size-4" />
            </button>
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
                {nav.map((item) => {
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
