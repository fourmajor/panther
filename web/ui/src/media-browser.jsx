import React, {useEffect, useMemo, useState} from 'react';
import { Button } from './components/ui/button.jsx';
import { Input } from './components/ui/input.jsx';
import { File, Folder, FolderUp } from 'lucide-react';
import {flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable} from '@tanstack/react-table';

export function MediaBrowser({prefix, gameName, gameId, folders=[], files=[], loading=false, error='', hasMore=false, onFolder, onFile, onMore}) {
  const [search,setSearch]=useState(''), [sorting,setSorting]=useState([]);
  useEffect(()=>{setSearch('');setSorting([]);},[prefix]);
  const data=useMemo(()=>[...folders.map(key=>({key,name:key.split('/').filter(Boolean).at(-1),folder:true})),...files.map(file=>({...file,folder:false}))],[folders,files]);
  const columns=useMemo(()=>[
    {accessorKey:'name',header:'Name',cell:({row})=><Button variant="ghost" type="button" className="media-item-link justify-start" onClick={()=>row.original.folder?onFolder(row.original.key):onFile(row.original)}>{row.original.folder?<Folder size={16} aria-hidden="true"/>:<File size={16} aria-hidden="true"/>}<span>{row.original.name}</span></Button>},
    {id:'type',header:'Type',accessorFn:r=>r.folder?'Folder':r.contentType?.split('/').at(-1)||r.name.split('.').at(-1)},
    {accessorKey:'size',header:'Size',cell:({getValue,row})=>row.original.folder?'—':new Intl.NumberFormat(undefined,{style:'unit',unit:'kilobyte',maximumFractionDigits:1}).format((getValue()||0)/1024)},
    {accessorKey:'lastModified',header:'Modified',cell:({getValue})=>getValue()?new Date(getValue()).toLocaleDateString():'—'},
  ],[onFolder,onFile]);
  const table=useReactTable({data,columns,state:{globalFilter:search,sorting},onGlobalFilterChange:setSearch,onSortingChange:setSorting,getCoreRowModel:getCoreRowModel(),getFilteredRowModel:getFilteredRowModel(),getSortedRowModel:getSortedRowModel()});
  const parts=prefix.split('/').filter(Boolean), crumbs=parts.slice(1).map((part,i)=>({name:i===0?gameName:part,key:parts.slice(0,i+2).join('/')+'/'}));
  return <div className="media-browser">
    <nav aria-label="Current folder" className="media-path">{crumbs.map((c,i)=><React.Fragment key={c.key}>{i>0&&<span aria-hidden="true">/</span>}<Button variant="ghost" type="button" onClick={()=>onFolder(c.key)} aria-current={i===crumbs.length-1?'location':undefined}>{c.name}</Button></React.Fragment>)}</nav>
    <div className="media-toolbar"><label><span className="sr-only">Search this folder</span><Input type="search" placeholder="Search this folder" value={search} onChange={e=>setSearch(e.target.value)}/></label><span role="status">{table.getRowModel().rows.length} items</span></div>
    {error&&<p role="alert">{error}</p>}
    <div className="media-table-scroll" aria-busy={loading}>
      <table><thead>{table.getHeaderGroups().map(group=><tr key={group.id}>{group.headers.map(h=><th key={h.id} scope="col" aria-sort={h.column.getIsSorted()==='asc'?'ascending':h.column.getIsSorted()==='desc'?'descending':'none'}><Button variant="ghost" type="button" onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header,h.getContext())}<span aria-hidden="true">{h.column.getIsSorted()==='asc'?' ↑':h.column.getIsSorted()==='desc'?' ↓':''}</span></Button></th>)}</tr>)}</thead>
      <tbody>{crumbs.length>1&&<tr className="media-parent-row"><td colSpan={columns.length}><Button variant="ghost" className="media-item-link justify-start" onClick={()=>onFolder(crumbs.at(-2).key)}><FolderUp size={16} aria-hidden="true"/><span>Parent folder</span></Button></td></tr>}{loading&&!data.length?Array.from({length:5},(_,i)=><tr key={i}>{columns.map((c,j)=><td key={j}><span className="ui-skeleton media-row-skeleton"/></td>)}</tr>):table.getRowModel().rows.map(row=><tr key={row.original.key}>{row.getVisibleCells().map(cell=><td key={cell.id}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>)}</tbody></table>
    </div>
    {!loading&&!data.length&&!error&&<p className="media-empty">This folder is empty.</p>}
    {!loading&&data.length>0&&!table.getRowModel().rows.length&&<p className="media-empty">No files match “{search}”.</p>}
    {hasMore&&<Button variant="ghost" type="button" className="quiet-button media-more" disabled={loading} onClick={onMore}>Load more</Button>}
  </div>;
}
