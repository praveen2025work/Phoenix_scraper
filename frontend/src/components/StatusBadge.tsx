import { Badge, type BadgeProps } from "@/components/ui/badge";
import { statusBadgeVariant } from "@/lib/statusStyles";

export function StatusBadge({
  status,
  children,
  ...props
}: { status: string } & Omit<BadgeProps, "variant">) {
  return (
    <Badge variant={statusBadgeVariant(status)} data-status={status} {...props}>
      {children ?? status}
    </Badge>
  );
}
