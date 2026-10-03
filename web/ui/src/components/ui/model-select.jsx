import React,{useId,useState} from 'react';
import {Check,ChevronsUpDown} from 'lucide-react';
import {Popover,PopoverTrigger,PopoverContent} from './popover.jsx';
import {Command,CommandInput,CommandList,CommandEmpty,CommandGroup,CommandItem} from './command.jsx';
import {Button} from './button.jsx';

export function modelPrice(model){
  const price=model?.priceEstimate;
  if(!price||price.status!=='estimated')return '';
  if(price.currency==='USD'&&Number.isFinite(Number(price.amount)))return `~$${Number(price.amount).toLocaleString('en-US',{maximumFractionDigits:6})}${price.unit?` / ${price.unit}`:''}`;
  if(Number.isFinite(Number(price.credits)))return `~${price.credits.toLocaleString()} credits${price.quantity?` / ${price.quantity.toLocaleString()} characters`:''}`;
  return '';
}
// Official shadcn Combobox composition: Radix owns focus/placement and cmdk selection.
export function ModelSelect({models,value,onChange,disabled=false}){
  const id=useId(),[open,setOpen]=useState(false),selected=models.find(model=>model.id===value);
  return <div className="grid min-w-0 gap-2"><label id={`${id}-label`}>Model</label><Popover modal open={open} onOpenChange={setOpen}><PopoverTrigger asChild><Button variant="outline" role="combobox" aria-labelledby={`${id}-label`} aria-expanded={open} disabled={disabled} className="h-9 w-full min-w-0 justify-between font-normal"><span className="truncate">{selected?.name||'Choose model'}</span><ChevronsUpDown size={16} aria-hidden="true" className="shrink-0 opacity-50"/></Button></PopoverTrigger><PopoverContent align="start" className="panther-combobox-content w-[var(--radix-popover-trigger-width)] p-0"><Command><CommandInput aria-label="Search models" placeholder="Search models…"/><CommandList><CommandEmpty>No matching models</CommandEmpty><CommandGroup>{models.map(model=><CommandItem key={model.id} value={`${model.id} ${model.name} ${model.provider||''}`} onSelect={()=>{onChange(model.id);setOpen(false);}} className="items-start"><div className="min-w-0 flex-1"><div className="break-words">{model.name}</div><div className="text-xs text-muted-foreground">{[model.provider,modelPrice(model)].filter(Boolean).join(' · ')}</div></div><Check size={16} aria-hidden="true" className={`ml-2 shrink-0 ${value===model.id?'opacity-100':'opacity-0'}`}/></CommandItem>)}</CommandGroup></CommandList></Command></PopoverContent></Popover></div>;
}
