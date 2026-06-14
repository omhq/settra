import { useState, type ComponentProps } from "react";
import { Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type SecretInputProps = Omit<ComponentProps<"input">, "type"> & {
  onConceal?: () => void;
  onReveal?: () => Promise<void> | void;
};

export function SecretInput({
  className,
  disabled,
  onConceal,
  onReveal,
  ...props
}: SecretInputProps) {
  const [visible, setVisible] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const toggleLabel = visible ? "Hide secret" : "Show secret";

  async function toggleVisibility() {
    if (visible) {
      setVisible(false);
      onConceal?.();
      return;
    }

    if (onReveal) {
      setRevealing(true);
      try {
        await onReveal();
      } catch {
        return;
      } finally {
        setRevealing(false);
      }
    }

    setVisible(true);
  }

  return (
    <div className="relative">
      <Input
        {...props}
        disabled={disabled}
        type={visible ? "text" : "password"}
        className={cn("pr-10", className)}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={toggleLabel}
        aria-pressed={visible}
        disabled={disabled || revealing}
        className="absolute right-0.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onClick={() => void toggleVisibility()}
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </Button>
    </div>
  );
}
