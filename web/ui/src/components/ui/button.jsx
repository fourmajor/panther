import React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils.js";

const buttonVariants = cva("inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50", {
  variants: {
    variant: { default: "ui-button-primary shadow-sm", secondary: "ui-button-secondary", ghost: "ui-button-ghost" },
    size: { default: "h-10 px-4 py-2", sm: "h-9 px-3", icon: "h-10 w-10" },
  }, defaultVariants: { variant: "default", size: "default" },
});
export const Button = React.forwardRef(function Button({className,variant,size,type="button",...props},ref) {
  return <button ref={ref} type={type} className={cn(buttonVariants({variant,size,className}))} {...props}/>;
});
