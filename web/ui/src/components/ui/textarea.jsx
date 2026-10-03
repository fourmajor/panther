import React from 'react';
import {cn} from '../../lib/utils.js';
export const Textarea=React.forwardRef(function Textarea({className,...props},ref){
  return <textarea ref={ref} className={cn('ui-input flex min-h-28 w-full rounded-md border px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50',className)} {...props}/>;
});
