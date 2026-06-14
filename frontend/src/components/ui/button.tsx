import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import { Link, type LinkProps } from "react-router-dom";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center rounded-lg border border-transparent text-sm font-medium whitespace-nowrap transition-all outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary/80",
        outline:
          "border-border bg-background hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
        ghost:
          "hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:hover:bg-muted/50",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:hover:bg-destructive/30 dark:focus-visible:ring-destructive/40",
      },
      size: {
        default: "h-8 gap-1.5 px-2.5",
        sm: "h-7 gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] [&_svg:not([class*='size-'])]:size-3.5",
        icon: "size-8",
        "icon-round": "size-8 rounded-full",
        "icon-sm": "size-7 rounded-[min(var(--radius-md),12px)]",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  },
);

type ButtonStyleProps = VariantProps<typeof buttonVariants>;
type ButtonAsButtonProps = ButtonPrimitive.Props &
  ButtonStyleProps & {
    className?: string;
    to?: never;
  };
type ButtonAsLinkProps = Omit<LinkProps, "className"> &
  ButtonStyleProps & {
    className?: string;
    disabled?: never;
  };
type ButtonProps = ButtonAsButtonProps | ButtonAsLinkProps;

function Button({
  className,
  variant = "primary",
  size = "default",
  ...props
}: ButtonProps) {
  const classes = cn(buttonVariants({ variant, size, className }));

  if ("to" in props && props.to !== undefined) {
    return <Link data-slot="button" className={classes} {...props} />;
  }

  return (
    <ButtonPrimitive
      data-slot="button"
      className={classes}
      {...(props as ButtonAsButtonProps)}
    />
  );
}

export { Button };
