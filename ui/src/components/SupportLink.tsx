// Single support contact affordance for the whole app. It replaced the upstream
// "Hire an Expert" / "Enterprise Enquiry" lead funnel and the docs links, so this
// is now the only way a user is invited to reach a human from inside the product.
// Keep the address in ONE place — three call sites render it (sidebar footer,
// Overview resources card, auth brand panel).

import { LifeBuoy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export const SUPPORT_EMAIL = "alok.kumar@nextwebspark.com";
export const SUPPORT_MAILTO = `mailto:${SUPPORT_EMAIL}`;

type SupportLinkProps = {
  label?: string;
  className?: string;
  variant?: React.ComponentProps<typeof Button>["variant"];
  size?: React.ComponentProps<typeof Button>["size"];
  /** Render as an icon-only button with the label moved into a tooltip. */
  iconOnly?: boolean;
  /** Tooltip side, only used when `iconOnly`. */
  tooltipSide?: "top" | "right" | "bottom" | "left";
};

export function SupportLink({
  label = "Contact support",
  className,
  variant = "default",
  size,
  iconOnly = false,
  tooltipSide = "right",
}: SupportLinkProps) {
  if (iconOnly) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            asChild
            size={size ?? "icon"}
            variant={variant}
            className={cn("h-7 w-7 rounded-full", className)}
          >
            <a href={SUPPORT_MAILTO} aria-label={label}>
              <LifeBuoy className="h-3.5 w-3.5" />
            </a>
          </Button>
        </TooltipTrigger>
        <TooltipContent side={tooltipSide}>
          <p>{label}</p>
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Button asChild size={size} variant={variant} className={className}>
      <a href={SUPPORT_MAILTO}>
        <LifeBuoy className="h-3.5 w-3.5" />
        {label}
      </a>
    </Button>
  );
}
