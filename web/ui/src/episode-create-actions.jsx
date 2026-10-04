import React, {useState} from 'react';
import {useInfiniteQuery} from '@tanstack/react-query';
import {ChevronDown, CirclePlus} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {DropdownMenu,DropdownMenuTrigger,DropdownMenuContent,DropdownMenuItem} from './components/ui/dropdown-menu.jsx';
import {MultiSelect} from './components/ui/multi-select.jsx';
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogFooter} from './components/ui/dialog.jsx';

export function EpisodeCreateActions({scope,gameId,onCreate,onLoadChapters,onAdapt,onComplete}) {
  const [open,setOpen]=useState(false),[selected,setSelected]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const chapters=useInfiniteQuery({queryKey:['episode-source-chapters',scope,gameId],initialPageParam:null,queryFn:({pageParam})=>onLoadChapters(pageParam),getNextPageParam:page=>page.cursor||undefined,enabled:open,staleTime:60000});
  const options=(chapters.data?.pages||[]).flatMap(page=>page.chapters||[]).map(chapter=>({id:chapter.id,name:chapter.title}));
  const submit=async event=>{event.preventDefault();if(!selected.length||busy)return;setBusy(true);setError('');try{const result=await onAdapt(selected[0]);setOpen(false);onComplete(result);}catch(cause){setError(cause.message);}finally{setBusy(false);}};
  return <>
    <div className="inline-flex items-center overflow-hidden rounded-md bg-primary">
      <Button onClick={onCreate} className="rounded-none shadow-none"><CirclePlus/>Create Episode</Button>
      <DropdownMenu><DropdownMenuTrigger asChild><Button size="icon" className="rounded-none border-l border-primary-foreground/25 shadow-none" aria-label="Create Episode options"><ChevronDown/></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={()=>{setError('');setSelected([]);setOpen(true);}}>Create from Novel…</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
    </div>
    <Dialog open={open} onOpenChange={value=>{if(!busy)setOpen(value);}}><DialogContent><DialogHeader><DialogTitle>Create TV Episode</DialogTitle></DialogHeader><form className="flex min-h-0 flex-col gap-6" onSubmit={submit}><div data-slot="dialog-body" className="flex flex-col gap-4">
      <MultiSelect label="Novel chapter" placeholder="Choose a chapter…" options={options} value={selected} onChange={value=>setSelected(value.slice(-1))} disabled={busy} modal/>
      {chapters.isPending&&<p role="status" className="text-sm text-muted-foreground">Loading chapters…</p>}
      {chapters.hasNextPage&&<Button type="button" variant="outline" disabled={chapters.isFetchingNextPage} onClick={()=>void chapters.fetchNextPage()}>More chapters</Button>}
      {(error||chapters.isError)&&<p role="alert" className="text-sm text-destructive">{error||'Chapters could not be loaded.'}</p>}
    </div><DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={()=>setOpen(false)}>Cancel</Button><Button type="submit" disabled={busy||!selected.length}>{busy?'Creating…':'Create TV Episode'}</Button></DialogFooter></form></DialogContent></Dialog>
  </>;
}
