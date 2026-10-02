import React from "react";
import { cn } from "../../lib/utils.js";
export const Input = React.forwardRef(function Input({className,type="text",...props},ref) {
  return <input ref={ref} type={type} className={cn("ui-input flex h-10 w-full rounded-md border px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50",className)} {...props}/>;
});
