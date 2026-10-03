import React,{useState} from 'react';
import {Accordion,AccordionItem,AccordionTrigger,AccordionContent} from './components/ui/accordion.jsx';
import {Checkbox} from './components/ui/checkbox.jsx';

export function TranscriptSources({items,selected,onSelect}){
 const [expanded,setExpanded]=useState('');
 return <Accordion type="single" collapsible value={expanded} onValueChange={setExpanded} className="transcript-source-list">{items.map(item=><AccordionItem key={item.key} value={item.key} className="transcript-source-item">
  <div className="transcript-source-heading"><Checkbox aria-label={item.name} checked={selected.includes(item.key)} onCheckedChange={checked=>onSelect(item.key,checked===true)} value={item.key}/><AccordionTrigger aria-label={item.name} className="transcript-source-trigger"><span className="editorial-source-copy"><span className="transcript-source-name">{item.name}</span>{item.meta&&<span className="editorial-source-meta">{item.meta}</span>}</span></AccordionTrigger></div>
  <AccordionContent className="transcript-source-summary">{item.summary||'No summary yet.'}</AccordionContent>
 </AccordionItem>)}</Accordion>;
}
