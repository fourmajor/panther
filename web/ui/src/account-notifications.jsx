import React,{useState,useEffect} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {Bell,Settings,LogOut,AlertCircle} from 'lucide-react';
import {Popover,PopoverTrigger,PopoverContent} from './components/ui/popover.jsx';
import {Button} from './components/ui/button.jsx';

function Notice({notice,onOpen,busy}){
 return <button type="button" className="notification-row" disabled={busy} onClick={()=>onOpen(notice)}>
  <span className={`notification-marker ${notice.readAt?'is-read':''}`} aria-label={notice.readAt?'Read':'Unread'}/>
  <span><strong>{notice.title}</strong><span>{notice.description}</span><time dateTime={new Date(notice.createdAt*1000).toISOString()}>{new Date(notice.createdAt*1000).toLocaleString()}</time></span>
 </button>;
}

function safeAvatar(value){try{const url=new URL(value,location.origin);return url.origin===location.origin&&/^\/avatars\/[a-z-]+\.svg$/.test(url.pathname)?url.href:null;}catch{return null;}}

export function AccountControls({scope,profile,onLoad,onRead,onOpen,onSettings,onSignOut,onHistory}){
 const client=useQueryClient(),[bell,setBell]=useState(false),[account,setAccount]=useState(false),[busy,setBusy]=useState(null),[error,setError]=useState('');
 const inbox=useQuery({queryKey:['notifications',scope,'unread'],queryFn:()=>onLoad({view:'unread'}),refetchInterval:60_000,retry:1});
 const items=inbox.data?.notifications||[];
 const open=async notice=>{setError('');setBusy(notice.id);try{await onRead(notice.id);await client.invalidateQueries({queryKey:['notifications',scope]});setBell(false);onOpen(notice);}catch{setError('Could not mark this notification as read. Please try again.');}finally{setBusy(null);}};
 const [imageFailed,setImageFailed]=useState(false);
 const initials=(profile.name||profile.username||'P').split(/\s+/).slice(0,2).map(word=>word[0]).join('').toUpperCase();
 const picture=profile.picture?safeAvatar(profile.picture):null;
 useEffect(()=>setImageFailed(false),[picture]);
 return <div className="header-account-controls">
  <Popover open={bell} onOpenChange={setBell}><PopoverTrigger asChild><Button variant="ghost" size="icon" className="notification-bell" aria-label={items.length?'Notifications, unread notifications':'Notifications'}><Bell size={20}/>{items.length>0&&<span className="notification-dot" data-testid="notification-dot"/>}{inbox.isError&&<span className="notification-unknown" aria-label="Notification status unavailable">!</span>}</Button></PopoverTrigger>
   <PopoverContent align="end" className="notification-popover"><h2>Notifications</h2>
    <div className="notification-popover-list">{inbox.isPending?<p className="animate-pulse">Checking notifications…</p>:inbox.isError?<div role="alert"><p>Notifications could not be loaded.</p><Button variant="outline" onClick={()=>inbox.refetch()}>Retry</Button></div>:items.length?items.slice(0,10).map(notice=><Notice key={notice.id} notice={notice} onOpen={open} busy={busy===notice.id}/>):<p>No unread notifications.</p>}</div>
    {error&&<p role="alert">{error}</p>}<Button variant="ghost" className="notification-history-link" onClick={()=>{setBell(false);onHistory();}}>View all notifications →</Button>
   </PopoverContent></Popover>
  <Popover open={account} onOpenChange={setAccount}><PopoverTrigger asChild><Button variant="ghost" size="icon" className="account-avatar" aria-label="Account" title={profile.name||'Account'}>{picture&&!imageFailed?<img src={picture} alt="" onError={()=>setImageFailed(true)}/>:<span aria-hidden="true">{initials}</span>}</Button></PopoverTrigger>
   <PopoverContent align="end" className="account-menu"><strong>{profile.name||profile.username||'Your account'}</strong><Button variant="ghost" onClick={()=>{setAccount(false);onSettings();}}><Settings size={16}/>Account settings</Button><Button variant="ghost" onClick={()=>{setAccount(false);onSignOut();}}><LogOut size={16}/>Sign out</Button></PopoverContent>
  </Popover>
 </div>;
}

export function NotificationsPage({scope,onLoad,onRead,onOpen}){
 const client=useQueryClient(),[cursor,setCursor]=useState(null),[earlier,setEarlier]=useState([]),[busy,setBusy]=useState(null),[error,setError]=useState('');
 const page=useQuery({queryKey:['notifications',scope,'all',cursor],queryFn:()=>onLoad({view:'all',cursor}),retry:1});
 const items=[...earlier,...(page.data?.notifications||[])];
 const open=async notice=>{setBusy(notice.id);setError('');try{await onRead(notice.id);setEarlier(previous=>previous.map(item=>item.id===notice.id?{...item,readAt:item.readAt||Date.now()/1000}:item));await client.invalidateQueries({queryKey:['notifications',scope]});onOpen(notice);}catch{setError('Could not mark this notification as read. Please try again.');}finally{setBusy(null);}};
 return <section className="notifications-page"><div className="page-heading"><h1>Notifications</h1></div><p className="notification-history-note">Read notifications stay here.</p>
  {page.isPending&&<p className="animate-pulse" role="status">Loading notification history…</p>}
  {page.isError&&<div role="alert"><AlertCircle size={18}/><p>Notification history could not be loaded.</p><Button variant="outline" onClick={()=>page.refetch()}>Retry</Button></div>}
  {error&&<p role="alert">{error}</p>}{items.map(notice=><Notice key={notice.id} notice={notice} onOpen={open} busy={busy===notice.id}/>)}
  {page.isSuccess&&!items.length&&<p>No notifications yet.</p>}
  {page.data?.cursor&&<Button variant="outline" onClick={()=>{setEarlier(items);setCursor(page.data.cursor);}}>Older notifications</Button>}
 </section>;
}
