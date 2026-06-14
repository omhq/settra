import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Activity,
  Bot,
  Moon,
  MessageSquare,
  MessageSquarePlus,
  Network,
  PlugZap,
  Radio,
  Sun,
} from "lucide-react";

import { CollapsibleColumn } from "@/components/ui/collapsible-column";
import { Tooltip } from "@/components/ui/tooltip";
import { api, type ChatThread } from "@/lib/api";
import { cn } from "@/lib/utils";

const nav = [
  { label: "New chat", href: "/chat", icon: MessageSquarePlus },
  { label: "Chats", href: "/chat/chats", icon: MessageSquare },
  { label: "Connections", href: "/connections", icon: PlugZap },
  { label: "Semantics", href: "/semantics", icon: Network },
  { label: "Models", href: "/models", icon: Bot },
  { label: "Channels", href: "/channels", icon: Radio },
  { label: "Status", href: "/status", icon: Activity },
];

const THEME_STORAGE_KEY = "settra:theme";

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

export default function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const isDark = theme === "dark";
  const visibleNav = nav.filter(
    (item) => item.href !== "/chat/chats" || threads.length > 0,
  );

  const loadThreads = useCallback(async () => {
    try {
      const items = await api.chat.threads.list();
      setThreads(items);
    } catch {
      setThreads([]);
    }
  }, []);

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
    void loadThreads();
  }, [loadThreads, pathname]);

  useEffect(() => {
    const onThreadsUpdated = () => {
      void loadThreads();
    };

    window.addEventListener("settra:threads-updated", onThreadsUpdated);
    return () =>
      window.removeEventListener("settra:threads-updated", onThreadsUpdated);
  }, [loadThreads]);

  return (
    <div className="min-h-screen bg-[#144bc6] dark:bg-[#176be7]">
      <header className="flex h-12 w-full items-center justify-between px-5 sm:px-6">
        <Link to="/chat" className="inline-flex items-center text-white">
          <span className="font-semibold tracking-tight">Settra</span>
        </Link>
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
            {isDark ? <Moon className="size-3" /> : <Sun className="size-3" />}
          </span>
        </button>
      </header>

      <div className="h-[calc(100vh-3rem)] min-h-0 w-full overflow-hidden rounded-t-2xl bg-background shadow-sm">
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
                "flex flex-col gap-1 pb-3 pt-6",
                collapsed ? "items-center px-2" : "px-3",
              )}
            >
              {visibleNav.map((item) => {
                const Icon = item.icon;
                const active =
                  item.href === "/chat"
                    ? pathname === "/chat"
                    : pathname === item.href ||
                      pathname.startsWith(`${item.href}/`);

                const link = (
                  <Link
                    key={item.href}
                    to={item.href}
                    aria-label={item.label}
                    onClick={
                      item.href === "/chat"
                        ? () =>
                            window.dispatchEvent(new Event("settra:new-chat"))
                        : undefined
                    }
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
      </div>
    </div>
  );
}
