import * as React from "react";
import { cn } from "@/lib/utils";

export const Table = ({ className, ...p }: React.HTMLAttributes<HTMLTableElement>) => (
  <div className="w-full overflow-x-auto">
    <table className={cn("w-full border-collapse text-sm", className)} {...p} />
  </div>
);
export const THead = (p: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <thead className="text-left text-xs uppercase text-muted-foreground" {...p} />
);
export const TBody = (p: React.HTMLAttributes<HTMLTableSectionElement>) => <tbody {...p} />;
export const TR = ({ className, ...p }: React.HTMLAttributes<HTMLTableRowElement>) => (
  <tr className={cn("border-b border-border", className)} {...p} />
);
export const TH = ({ className, ...p }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
  <th className={cn("px-2 py-1.5 font-medium", className)} {...p} />
);
export const TD = ({ className, ...p }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn("px-2 py-1.5", className)} {...p} />
);
