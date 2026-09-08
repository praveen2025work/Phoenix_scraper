import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function Panel({
  title,
  subtitle,
  children,
  isLoading,
  error,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  isLoading?: boolean;
  error?: unknown;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </CardHeader>
      <CardContent aria-busy={isLoading || undefined}>
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
