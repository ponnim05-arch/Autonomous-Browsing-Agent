import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | "emerald";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return (
      <button
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]",
          {
            "bg-emerald-500 text-zinc-950 shadow hover:bg-emerald-400 font-semibold":
              variant === "default" || variant === "emerald",
            "bg-red-500/90 text-white shadow-sm hover:bg-red-500":
              variant === "destructive",
            "border border-white/10 bg-zinc-900/50 hover:bg-zinc-800 hover:text-white":
              variant === "outline",
            "bg-zinc-800 text-zinc-100 shadow-sm hover:bg-zinc-700":
              variant === "secondary",
            "hover:bg-zinc-800 hover:text-zinc-50": variant === "ghost",
            "text-emerald-400 underline-offset-4 hover:underline":
              variant === "link",
          },
          {
            "h-10 px-4 py-2": size === "default",
            "h-8 rounded-lg px-3 text-xs": size === "sm",
            "h-12 rounded-xl px-8 text-base": size === "lg",
            "h-9 w-9 p-0": size === "icon",
          },
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
