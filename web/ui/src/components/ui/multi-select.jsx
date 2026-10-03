import React,{useId,useState} from 'react';
import {Check,ChevronsUpDown,X} from 'lucide-react';
import {Popover,PopoverContent,PopoverTrigger} from './popover.jsx';
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
      <PopoverTrigger asChild><Button variant="outline" role="combobox" aria-labelledby={`${id}-label`} aria-expanded={open} disabled={disabled||creating} className="w-full justify-between font-normal"><span className="truncate">{creating?'Creating…':placeholder??`Add ${label.toLocaleLowerCase()}…`}</span><ChevronsUpDown size={16} aria-hidden="true" className="shrink-0 opacity-50"/></Button></PopoverTrigger>
      <PopoverContent align="start" className="panther-combobox-content w-[var(--radix-popover-trigger-width)] p-0">
        <Command shouldFilter={false}><CommandInput aria-label={`Search ${label.toLocaleLowerCase()}`} placeholder={`Search ${label.toLocaleLowerCase()}…`} value={query} onValueChange={setQuery}/><CommandList label={`${label} suggestions`}>
          {!matches.length&&!create&&<CommandEmpty>{query.trim()?'No matches':'No available options'}</CommandEmpty>}
          <CommandGroup>{matches.map(option=><CommandItem key={option.id} value={String(option.id)} onSelect={()=>void choose(option)}>{option.name??option.label??option.id}<Check size={16} aria-hidden="true" className="ml-auto opacity-0"/></CommandItem>)}
          {create&&<CommandItem value={`create-${query}`} onSelect={()=>void choose({create:true})}>Create “{query.trim()}”</CommandItem>}</CommandGroup>
        </CommandList></Command>
      </PopoverContent>
    </Popover>
    {error&&<p role="alert" className="text-sm">{error}</p>}
    {value.length>0&&<div className="flex flex-wrap gap-1.5" aria-label={`Selected ${label.toLocaleLowerCase()}`}>{value.map(selected=><Badge key={selected} variant="secondary" className="max-w-full gap-1 px-2.5 py-1"><span className="min-w-0 truncate">{names.get(selected)??selected}</span>{removable&&<Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 p-0" aria-label={`Remove ${names.get(selected)??selected} from ${label.toLocaleLowerCase()}`} disabled={disabled} onClick={()=>onChange(value.filter(item=>item!==selected))}><X size={12} aria-hidden="true"/></Button>}</Badge>)}</div>}
  </div>;
}
