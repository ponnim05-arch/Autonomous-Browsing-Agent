import * as React from "react";
import { cn } from "@/lib/utils";

interface TabsContextValue {
  value: string;
  onValueChange: (value: string) => void;
}

const TabsContext = React.createContext<TabsContextValue | undefined>(undefined);

interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string;
  onValueChange: (value: string) => void;
}

const Tabs = ({ value, onValueChange, className, ...props }: TabsProps) => (
  <TabsContext.Provider value={{ value, onValueChange }}>
    <div className={cn("w-full", className)} {...props} />
  </TabsContext.Provider>
);

const TabsList = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "inline-flex h-11 items-center justify-center rounded-xl bg-zinc-900/80 p-1 text-zinc-400 border border-white/5",
      className
    )}
    {...props}
  />
));
TabsList.displayName = "TabsList";

interface TabsTriggerProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string;
}

const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ className, value, ...props }, ref) => {
    const context = React.useContext(TabsContext);
    if (!context) throw new Error("TabsTrigger must be used within Tabs");
    const isSelected = context.value === value;

    return (
      <button
        ref={ref}
        type="button"
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-all focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50",
          isSelected
            ? "bg-zinc-800 text-emerald-400 shadow-sm font-semibold"
            : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40",
          className
        )}
        onClick={() => context.onValueChange(value)}
        {...props}
      />
    );
  }
);
TabsTrigger.displayName = "TabsTrigger";

interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string;
}

const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ className, value, ...props }, ref) => {
    const context = React.useContext(TabsContext);
    if (!context) throw new Error("TabsContent must be used within Tabs");
    if (context.value !== value) return null;

    return (
      <div
        ref={ref}
        className={cn(
          "mt-4 ring-offset-background focus-visible:outline-none animate-in fade-in-50 duration-200",
          className
        )}
        {...props}
      />
    );
  }
);
TabsContent.displayName = "TabsContent";

export { Tabs, TabsList, TabsTrigger, TabsContent };
