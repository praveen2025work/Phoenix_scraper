import * as React from "react";
import { cn } from "@/lib/utils";

type Div = React.HTMLAttributes<HTMLDivElement>;

export const Card = ({ className, ...props }: Div) => (
  <div
    className={cn("rounded-lg border border-border bg-card text-foreground", className)}
    {...props}
  />
);

export const CardHeader = ({ className, ...props }: Div) => (
  <div className={cn("flex flex-col gap-1 p-4", className)} {...props} />
);

export const CardTitle = ({ className, ...props }: Div) => (
  <div className={cn("font-semibold leading-tight", className)} {...props} />
);

export const CardDescription = ({ className, ...props }: Div) => (
  <div className={cn("text-sm text-muted-foreground", className)} {...props} />
);

export const CardContent = ({ className, ...props }: Div) => (
  <div className={cn("p-4 pt-0", className)} {...props} />
);

export const CardFooter = ({ className, ...props }: Div) => (
  <div className={cn("flex items-center gap-2 p-4 pt-0", className)} {...props} />
);
