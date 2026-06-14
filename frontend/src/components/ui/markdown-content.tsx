import ReactMarkdown, { type Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

const components: Components = {
  a({ className, children, ...props }) {
    return (
      <a
        className={cn(
          "font-medium text-primary underline underline-offset-2 hover:text-primary/80",
          className,
        )}
        target="_blank"
        rel="noreferrer"
        {...props}
      >
        {children}
      </a>
    );
  },
  blockquote({ className, ...props }) {
    return (
      <blockquote
        className={cn(
          "my-2 border-l-2 border-border pl-3 text-muted-foreground",
          className,
        )}
        {...props}
      />
    );
  },
  code({ className, children, ...props }) {
    const text = String(children);
    const isBlock = text.includes("\n") || className?.startsWith("language-");

    return (
      <code
        className={cn(
          isBlock
            ? "font-mono text-xs"
            : "rounded border bg-muted px-1 py-0.5 font-mono text-[0.85em]",
          className,
        )}
        {...props}
      >
        {children}
      </code>
    );
  },
  h1({ className, ...props }) {
    return (
      <h1
        className={cn(
          "mt-4 mb-2 text-base font-semibold first:mt-0",
          className,
        )}
        {...props}
      />
    );
  },
  h2({ className, ...props }) {
    return (
      <h2
        className={cn("mt-4 mb-2 text-sm font-semibold first:mt-0", className)}
        {...props}
      />
    );
  },
  h3({ className, ...props }) {
    return (
      <h3
        className={cn(
          "mt-3 mb-1.5 text-sm font-semibold first:mt-0",
          className,
        )}
        {...props}
      />
    );
  },
  hr({ className, ...props }) {
    return <hr className={cn("my-3 border-border", className)} {...props} />;
  },
  li({ className, ...props }) {
    return (
      <li
        className={cn("pl-1 marker:text-muted-foreground", className)}
        {...props}
      />
    );
  },
  ol({ className, ...props }) {
    return (
      <ol
        className={cn("my-2 list-decimal space-y-1 pl-5", className)}
        {...props}
      />
    );
  },
  p({ className, ...props }) {
    return (
      <p className={cn("my-2 first:mt-0 last:mb-0", className)} {...props} />
    );
  },
  pre({ className, ...props }) {
    return (
      <pre
        className={cn(
          "my-2 max-w-full overflow-x-auto rounded-md border bg-muted p-3 text-xs",
          className,
        )}
        {...props}
      />
    );
  },
  table({ className, ...props }) {
    return (
      <div className="my-2 max-w-full overflow-x-auto">
        <table
          className={cn("w-full min-w-max border-collapse text-xs", className)}
          {...props}
        />
      </div>
    );
  },
  td({ className, ...props }) {
    return (
      <td
        className={cn("border border-border px-2 py-1 align-top", className)}
        {...props}
      />
    );
  },
  th({ className, ...props }) {
    return (
      <th
        className={cn(
          "border border-border bg-muted px-2 py-1 text-left font-medium align-top",
          className,
        )}
        {...props}
      />
    );
  },
  ul({ className, ...props }) {
    return (
      <ul
        className={cn("my-2 list-disc space-y-1 pl-5", className)}
        {...props}
      />
    );
  },
};

type MarkdownContentProps = {
  content: string;
  className?: string;
};

function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div className={cn("min-w-0 break-words leading-6", className)}>
      <ReactMarkdown
        components={components}
        remarkPlugins={[remarkGfm, remarkBreaks]}
        skipHtml
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export { MarkdownContent };
