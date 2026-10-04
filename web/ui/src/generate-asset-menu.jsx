import React from 'react';
import {Sparkles,ChevronDown} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {DropdownMenu,DropdownMenuTrigger,DropdownMenuContent,DropdownMenuItem} from './components/ui/dropdown-menu.jsx';
export const generationTypeName=type=>({image:'Image',map:'Map',blueprint:'Blueprint',location:'Location',portrait:'Portrait',video:'Video',narration:'Speech',text:'Text'}[type.id]||type.name||type.id);
export function GenerateAssetMenu({types=[],disabled=false,title,onSelect}){
 return <DropdownMenu><DropdownMenuTrigger asChild><Button data-action-role="generate" className="ui-action-button" disabled={disabled} title={title}><Sparkles size={16} aria-hidden="true"/>Generate<ChevronDown size={16} aria-hidden="true"/></Button></DropdownMenuTrigger><DropdownMenuContent align="end" aria-label="Generate asset type">{types.map(type=><DropdownMenuItem key={type.id} disabled={type.available===false} onSelect={()=>onSelect(type.id)}>{generationTypeName(type)}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>;
}
