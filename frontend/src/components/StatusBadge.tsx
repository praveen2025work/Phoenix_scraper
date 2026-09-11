import { Badge, type BadgeProps } from "@/components/ui/badge";
import { statusBadgeVariant } from "@/lib/statusStyles";
import { cn } from "@/lib/utils";

/** Shared status chip — display label is uppercase via CSS; `data-status` keeps the raw API value. */
export function StatusBadge({
  status,
  children,
  className,
  ...props
}: { status: string } & Omit<BadgeProps, "variant">) {
  return (
    <Badge
      variant={statusBadgeVariant(status)}
      data-status={status}
      className={cn("uppercase tracking-wide", className)}
      {...props}
    >
      {children ?? status}
    </Badge>
  );
}
