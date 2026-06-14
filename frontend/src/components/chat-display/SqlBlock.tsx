import { useId, useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, Clipboard } from "lucide-react";
import { format } from "sql-formatter";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SQL_KEYWORDS = new Set([
  "and",
  "as",
  "asc",
  "between",
  "by",
  "case",
  "desc",
  "else",
  "end",
  "from",
  "full",
  "group",
  "having",
  "in",
  "inner",
  "is",
  "join",
  "left",
  "limit",
  "not",
  "null",
  "on",
  "or",
  "order",
  "outer",
  "right",
  "select",
  "then",
  "true",
  "false",
  "when",
  "where",
  "with",
]);

const SQL_FUNCTIONS = new Set([
  "avg",
  "coalesce",
  "count",
  "date_trunc",
  "max",
  "min",
  "sum",
]);

type SqlToken = {
  value: string;
  className?: string;
};

function formatSql(sql: string) {
  try {
    return format(sql, {
      language: "postgresql",
      keywordCase: "upper",
      tabWidth: 2,
      linesBetweenQueries: 1,
    }).trim();
  } catch {
    return sql.trim();
  }
}

function tokenizeSql(line: string): SqlToken[] {
  return line
    .split(/(\s+|'[^']*'|"[^"]*"|\b[\w.]+\b|[(),;=*<>+-])/g)
    .filter(Boolean)
    .map((value) => {
      const normalized = value.toLowerCase();

      if (/^'.*'$/.test(value) || /^".*"$/.test(value)) {
        return { value, className: "text-emerald-700 dark:text-emerald-300" };
      }

      if (/^\d+(?:\.\d+)?$/.test(value)) {
        return { value, className: "text-violet-700 dark:text-violet-300" };
      }

      if (SQL_KEYWORDS.has(normalized)) {
        return {
          value,
          className: "font-semibold text-blue-700 dark:text-blue-300",
        };
      }

      if (SQL_FUNCTIONS.has(normalized)) {
        return {
          value,
          className: "font-medium text-cyan-700 dark:text-cyan-300",
        };
      }

      return { value };
    });
}

function copyWithTextarea(value: string) {
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

export function SqlBlock({ sql }: { sql: string }) {
  const contentId = useId();
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const formattedSql = useMemo(() => formatSql(sql), [sql]);
  const lines = useMemo(() => formattedSql.split("\n"), [formattedSql]);

  async function copySql() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(formattedSql);
      } else {
        copyWithTextarea(formattedSql);
      }
    } catch {
      copyWithTextarea(formattedSql);
    }

    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <section className="mt-3 w-full overflow-hidden rounded-lg border border-blue-200/80 bg-blue-50/45 shadow-sm shadow-blue-950/[0.04] dark:border-blue-400/20 dark:bg-blue-950/20 dark:shadow-black/10">
      <div className="flex min-h-10 items-center justify-between gap-3 border-b border-blue-200/70 bg-blue-100/70 px-3 py-1.5 dark:border-blue-400/15 dark:bg-blue-950/35">
        <button
          type="button"
          className="flex min-h-7 flex-1 select-none items-center gap-1.5 text-xs font-medium text-blue-700 hover:cursor-pointer hover:text-blue-950 outline-none focus-visible:rounded-md focus-visible:ring-3 focus-visible:ring-blue-400/40 dark:text-blue-300 dark:hover:text-blue-100"
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? (
            <ChevronDown className="size-3.5 text-blue-700 hover:cursor-pointer hover:text-blue-950 dark:text-blue-300 dark:hover:text-blue-100" />
          ) : (
            <ChevronRight className="size-3.5 text-blue-700 hover:cursor-pointer hover:text-blue-950 dark:text-blue-300 dark:hover:text-blue-100" />
          )}
          SQL
        </button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={copied ? "SQL copied" : "Copy SQL"}
          title={copied ? "Copied" : "Copy SQL"}
          className="size-7 text-blue-700 hover:bg-blue-200/70 hover:text-blue-950 dark:text-blue-300 dark:hover:bg-blue-400/10 dark:hover:text-blue-100"
          onClick={() => void copySql()}
        >
          {copied ? (
            <Check className="size-3.5" />
          ) : (
            <Clipboard className="size-3.5" />
          )}
        </Button>
      </div>
      {expanded && (
        <div
          id={contentId}
          className="max-h-80 overflow-auto bg-white dark:bg-background"
        >
          <div
            role="region"
            aria-label="Formatted SQL"
            className="min-w-max p-0 font-mono text-xs leading-5 text-slate-900 dark:text-foreground"
          >
            {lines.map((line, index) => (
              <div key={`${index}-${line}`} className="flex">
                <span className="sticky left-0 w-10 shrink-0 border-r border-blue-100 bg-blue-50/90 px-2 text-right text-blue-400 dark:border-blue-400/10 dark:bg-blue-950/60 dark:text-blue-300/70">
                  {index + 1}
                </span>
                <code className="whitespace-pre px-3">
                  {tokenizeSql(line).map((token, tokenIndex) => (
                    <span
                      key={`${token.value}-${tokenIndex}`}
                      className={cn(token.className)}
                    >
                      {token.value}
                    </span>
                  ))}
                </code>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
