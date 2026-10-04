import React, {useRef, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {ThumbsUp, ThumbsDown} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Textarea} from './components/ui/textarea.jsx';
import {Field, FieldLabel} from './components/ui/field.jsx';
import {Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter} from './components/ui/dialog.jsx';

export function ChapterReview({scope,gameId,chapterId,onLoad,onSave}) {
  const client=useQueryClient(),key=['chapter-review',scope,gameId,chapterId];
  const query=useQuery({queryKey:key,queryFn:onLoad,staleTime:30000,retry:1});
  const [rejecting,setRejecting]=useState(false),[comment,setComment]=useState('');
  const pending=useRef(null);
  const mutation=useMutation({mutationFn:async status=>{
    pending.current||={gameId,chapterId,status,comment:status==='rejected'?comment.trim():'',expectedRevision:query.data?.review?.revision||null,operationId:crypto.randomUUID().replaceAll('-','')};
    return onSave(pending.current);
  },onSuccess:result=>{pending.current=null;client.setQueryData(key,result);setRejecting(false);},retry:false});
  const busy=query.isPending||query.isError||mutation.isPending,review=query.data?.review;
  return <div className="flex max-w-full flex-col gap-2 rounded-xl border bg-background/75 p-2 shadow-lg backdrop-blur-xl">
    <div className="flex items-center justify-end gap-2" aria-label="Chapter review actions">
      <Button variant="ghost" size="sm" disabled={busy} aria-pressed={review?.status==='approved'} onClick={()=>mutation.mutate('approved')}><ThumbsUp/>Approve</Button>
      <Button variant="ghost" size="sm" disabled={busy} aria-pressed={review?.status==='rejected'} onClick={()=>setRejecting(true)}><ThumbsDown/>Reject</Button>
    </div>
    {query.isError&&<Button variant="ghost" size="sm" onClick={()=>void query.refetch()}>Retry loading review</Button>}
    {!rejecting&&mutation.isError&&<p role="alert" className="max-w-64 px-2 text-sm text-destructive">{mutation.error.message}</p>}
    {review?.status&&<p role="status" className="max-w-64 break-words px-2 text-right text-xs text-muted-foreground">{review.status==='approved'?'Approved':['Rejected',review.comment].filter(Boolean).join(' · ')}</p>}
    <Dialog open={rejecting} onOpenChange={value=>{if(!mutation.isPending)setRejecting(value);}}><DialogContent><DialogHeader><DialogTitle>Reject chapter</DialogTitle></DialogHeader>
      <form className="flex min-h-0 flex-col gap-6" onSubmit={event=>{event.preventDefault();mutation.mutate('rejected');}}>
        <div data-slot="dialog-body"><Field><FieldLabel htmlFor="chapter-review-comment">Comment (optional)</FieldLabel><Textarea id="chapter-review-comment" maxLength={4000} value={comment} disabled={mutation.isPending} onChange={event=>setComment(event.target.value)}/></Field>{mutation.isError&&<p role="alert" className="text-sm text-destructive">{mutation.error.message}</p>}</div>
        <DialogFooter><Button type="button" variant="outline" disabled={mutation.isPending} onClick={()=>setRejecting(false)}>Cancel</Button><Button disabled={mutation.isPending} type="submit"><ThumbsDown/>{mutation.isPending?'Saving…':'Reject Chapter'}</Button></DialogFooter>
      </form>
    </DialogContent></Dialog>
  </div>;
}
