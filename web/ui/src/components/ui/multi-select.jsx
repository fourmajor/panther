import React,{useId,useState} from 'react';
import {Check,ChevronsUpDown,X} from 'lucide-react';
import {Popover,PopoverContent,PopoverTrigger,PopoverAnchor} from './popover.jsx';
import {Command,CommandInput,CommandList,CommandEmpty,CommandGroup,CommandItem} from './command.jsx';
import {Badge} from './badge.jsx';
import {Button} from './button.jsx';
import {matchingOptions,addSelection} from './multi-select-options.js';

// Application composition of the official shadcn Combobox pattern. Radix owns
// focus/dismissal/placement; cmdk owns keyboard navigation and active selection.
export function MultiSelect({label,options=[],value=[],onChange,placeholder,disabled=false,onCreate,removable=true,modal=false}) {
  const id=useId(),[open,setOpen]=useState(false),[query,setQuery]=useState(''),[creating,setCreating]=useState(false),[error,setError]=useState('');
  const matches=matchingOptions(options,value,query),names=new Map(options.map(option=>[option.id,option.name??option.label??option.id]));
  const create=Boolean(onCreate&&query.trim()&&!options.some(option=>String(option.name??option.id).toLocaleLowerCase()===query.trim().toLocaleLowerCase()));
  const choose=async option=>{if(disabled||creating)return;setError('');
    if(option.create){setCreating(true);try{const tag=await onCreate(query.trim());onChange(addSelection(value,tag));setQuery('');setOpen(false);}catch{setError('Could not create the tag. Try again.');}finally{setCreating(false);}return;}
    onChange(addSelection(value,option.id));setQuery('');setOpen(false);
  };
  return <div className="panther-multi-select grid min-w-0 gap-2">
    <label id={`${id}-label`} className="text-sm font-medium">{label}</label>
    <Popover modal={modal} open={open} onOpenChange={next=>{setOpen(next);if(!next)setQuery('');}}>
      <PopoverAnchor asChild><div data-selected={value.length>0} className="panther-multi-select-control flex h-9 min-w-0 items-center rounded-md border border-input bg-background shadow-sm">
        {value.length>0&&<div className="panther-multi-select-values flex min-w-0 flex-1 items-center gap-1 overflow-x-auto px-1.5" aria-label={`Selected ${label.toLocaleLowerCase()}`}>{value.map(selected=><Badge key={selected} variant="secondary" className="shrink-0 gap-1 px-2 py-0.5"><span className="max-w-40 truncate">{names.get(selected)??selected}</span>{removable&&<Button variant="ghost" size="icon" className="h-5 w-5 shrink-0 p-0" aria-label={`Remove ${names.get(selected)??selected} from ${label.toLocaleLowerCase()}`} disabled={disabled} onClick={()=>onChange(value.filter(item=>item!==selected))}><X size={12} aria-hidden="true"/></Button>}</Badge>)}</div>}
        <PopoverTrigger asChild><Button variant="ghost" role="combobox" aria-labelledby={`${id}-label`} aria-expanded={open} disabled={disabled||creating} className={value.length?'h-9 w-9 shrink-0 rounded-l-none px-2':'h-9 w-full min-w-0 justify-between font-normal'}>{!value.length&&<span className="truncate">{creating?'Creating…':placeholder??`Add ${label.toLocaleLowerCase()}…`}</span>}<ChevronsUpDown size={16} aria-hidden="true" className="shrink-0 opacity-50"/></Button></PopoverTrigger>
      </div></PopoverAnchor>
      <PopoverContent align="start" className="panther-combobox-content w-[var(--radix-popover-trigger-width)] p-0">
        <Command shouldFilter={false}><CommandInput aria-label={`Search ${label.toLocaleLowerCase()}`} placeholder={`Search ${label.toLocaleLowerCase()}…`} value={query} onValueChange={setQuery}/><CommandList label={`${label} suggestions`}>
          {!matches.length&&!create&&<CommandEmpty>{query.trim()?'No matches':'No available options'}</CommandEmpty>}
          <CommandGroup>{matches.map(option=><CommandItem key={option.id} value={String(option.id)} onSelect={()=>void choose(option)}>{option.name??option.label??option.id}<Check size={16} aria-hidden="true" className="ml-auto opacity-0"/></CommandItem>)}
          {create&&<CommandItem value={`create-${query}`} onSelect={()=>void choose({create:true})}>Create “{query.trim()}”</CommandItem>}</CommandGroup>
        </CommandList></Command>
      </PopoverContent>
    </Popover>
    {error&&<p role="alert" className="text-sm">{error}</p>}

  </div>;
}
