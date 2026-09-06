import * as React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | "emerald" | "amber" | "cyan" | "purple";
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        {
          "border-transparent bg-emerald-500/10 text-emerald-400 border-emerald-500/20":
            variant === "default" || variant === "emerald",
          "border-transparent bg-zinc-800 text-zinc-300":
            variant === "secondary",
          "border-transparent bg-red-500/10 text-red-400 border-red-500/20":
            variant === "destructive",
          "border-transparent bg-amber-500/10 text-amber-400 border-amber-500/20":
            variant === "amber",
          "border-transparent bg-cyan-500/10 text-cyan-400 border-cyan-500/20":
            variant === "cyan",
          "border-transparent bg-purple-500/10 text-purple-400 border-purple-500/20":
            variant === "purple",
          "border-white/10 text-zinc-300": variant === "outline",
        },
        className
      )}
      {...props}
    />
  );
}

export { Badge };
