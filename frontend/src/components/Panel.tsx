import type { ReactNode } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function Panel({
  title,
  subtitle,
  children,
  isLoading,
  error,
  emphasis = false,
  className,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  isLoading?: boolean;
  error?: unknown;
  /** High visual weight — used for skill gaps as the primary Results surface. */
  emphasis?: boolean;
  className?: string;
}) {
  return (
    <Card
      className={cn(
        "panel-enter overflow-hidden",
        emphasis
          ? "border-primary/35 bg-surface-strong shadow-sm"
          : "bg-card",
        className,
      )}
    >
      <CardHeader className={cn("space-y-0.5", emphasis && "pb-2 pt-3 sm:px-4")}>
        <h3
          className={cn(
            "tracking-tight",
            emphasis
              ? "font-display text-xl font-semibold"
              : "text-base font-semibold",
          )}
        >
          {title}
        </h3>
        {subtitle && (
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        )}
      </CardHeader>
      <CardContent
        className={cn(emphasis && "sm:px-4 sm:pb-4")}
        aria-busy={isLoading || undefined}
      >
        {isLoading ? (
          <div className="space-y-2" data-testid="panel-skeleton">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        ) : error ? (
          <p className="text-sm text-destructive" role="alert">
            {(error as Error).message}
          </p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
