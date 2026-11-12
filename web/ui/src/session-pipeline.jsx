import React from 'react';
import {useQuery} from '@tanstack/react-query';
import {AudioLines, BookOpen, Camera, Captions, CircleAlert, Clapperboard, FileText, Film, Image, Library, List, Mic, Package, Palette, Pencil, ScrollText, Search, ShieldCheck, Users} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle} from './components/ui/dialog.jsx';
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from './components/ui/select.jsx';
import {cardText, cardTone, formatWhen, presentation, runIdentity, sessionHeadline, statusText, workerLabel} from './session-pipeline-model.js';

const icons = {mic: Mic, captions: Captions, users: Users, file: FileText, 'file-check': FileText, library: Library, pencil: Pencil, book: BookOpen, clapper: Clapperboard, list: List, search: Search, image: Image, package: Package, audio: AudioLines, palette: Palette, camera: Camera, scroll: ScrollText, shield: ShieldCheck, film: Film, circle: CircleAlert};

function columnsOf(nodes) {
  const columns = new Map();
  for (const node of nodes) {
    if (!columns.has(node.column)) columns.set(node.column, []);
    columns.get(node.column).push(node);
  }
  return [...columns.entries()].sort((a, b) => a[0] - b[0]).map(([index, items]) => ({index, nodes: items}));
}

function Graph({nodes, edges, onOpen, label='Session pipeline'}) {
  const canvas = React.useRef(null);
  const refs = React.useRef(new Map());
  const [lines, setLines] = React.useState([]);
  const measure = React.useCallback(() => {
    const root = canvas.current;
    if (!root) return;
    const box = root.getBoundingClientRect();
    const placed = {};
    for (const node of nodes) {
      const element = refs.current.get(node.id);
      if (!element) continue;
      const rect = element.getBoundingClientRect();
      placed[node.id] = {x: rect.left - box.left, y: rect.top - box.top, w: rect.width, h: rect.height};
    }
    setLines(edges.flatMap(edge => {
      const from = placed[edge.from], to = placed[edge.to];
      if (!from || !to) return [];
      const x1 = from.x + from.w, y1 = from.y + from.h / 2, x2 = to.x, y2 = to.y + to.h / 2;
      const mid = x1 + Math.max(18, (x2 - x1) / 2);
      const sameRow = Math.abs(y1 - y2) < 2;
      const d = sameRow ? `M ${x1} ${y1} L ${x2} ${y2}` : `M ${x1} ${y1} L ${mid} ${y1} L ${mid} ${y2} L ${x2} ${y2}`;
      return [{id: `${edge.from}-${edge.to}`, d, status: presentation(edge.status, edge.from)}];
    }));
  }, [nodes, edges]);
  React.useLayoutEffect(() => {
    measure();
    const root = canvas.current;
    if (!root) return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    window.addEventListener('resize', measure);
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, [measure]);
  return <div className="pipeline-scroll" tabIndex={0} aria-label={label}>
    <div className="pipeline-canvas" ref={canvas}>
      <svg className="pipeline-edges" aria-hidden="true">
        <defs><marker id="pipeline-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0 0 L7 3 L0 6" fill="none" stroke="context-stroke" strokeWidth="1.4"/></marker></defs>
        {lines.map(line => <path key={line.id} d={line.d} data-status={line.status} markerEnd="url(#pipeline-arrow)"/>)}
      </svg>
      <div className="pipeline-columns">{columnsOf(nodes).map(column => <div className="pipeline-column" key={column.index}>{column.nodes.map(node => {
        const Icon = icons[node.icon] || CircleAlert;
        const shown = presentation(node.status, node.id);
        return <button key={node.id} type="button" className="pipeline-node" data-status={shown} data-final={node.final ? 'true' : 'false'} style={{gridRow: node.row + 1}} ref={element => { if (element) refs.current.set(node.id, element); else refs.current.delete(node.id); }} aria-label={`${node.title}, ${statusText(node.status, node.id)}`} onClick={() => onOpen(node)}>
          <span className="pipeline-icon" aria-hidden="true">{shown === 'failed' ? <span className="pipeline-x">×</span> : <Icon size={18} strokeWidth={1.7}/>}</span>
          <span className="pipeline-copy"><span className="pipeline-type">{node.type}</span><strong>{node.title}</strong><span className="pipeline-state">{statusText(node.status, node.id)}</span></span>
        </button>;
      })}</div>)}</div>
    </div>
  </div>;
}

function Detail({node, onPreview, onClose}) {
  return <Dialog open={Boolean(node)} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="pipeline-detail">
      {node && <><DialogHeader><DialogTitle>{node.title}</DialogTitle><DialogDescription>{node.type} · {statusText(node.status, node.id)}</DialogDescription></DialogHeader>
        {node.status === 'failed' && <p role="alert" className="pipeline-failure">{node.message || 'This step failed without a recorded message.'}</p>}
        {presentation(node.status, node.id) === 'gate' && <p className="pipeline-gate">{node.message || 'Paid video stays blocked until this storyboard revision is approved.'}</p>}
        {node.message && node.status !== 'failed' && presentation(node.status, node.id) !== 'gate' && <p className="pipeline-log">{node.message}</p>}
        {node.logs?.length > 0 && <pre className="pipeline-log">{node.logs.join('\n')}</pre>}
        {node.artifacts?.length > 0 && <ul className="pipeline-artifacts">{node.artifacts.map(artifact => <li key={artifact.key}><Button variant="outline" onClick={() => onPreview(artifact.key)}>{artifact.label || 'Open artifact'}</Button></li>)}</ul>}
        {!node.message && !node.logs?.length && !node.artifacts?.length && node.status !== 'failed' && presentation(node.status, node.id) !== 'gate' && <p className="pipeline-log">No artifact or log has been recorded for this step.</p>}
      </>}
    </DialogContent>
  </Dialog>;
}

function Finals({finals}) {
  if (!finals?.length) return null;
  return <div className="pipeline-finals" role="list" aria-label="Final artifacts">{finals.map(final => <span key={final.id} role="listitem" className="pipeline-chip" data-status={cardTone(final.status)}>{final.title}</span>)}</div>;
}

export function SessionPipeline({gameId, scope, sessionId, onLoad, onNavigate, onPreview, embedded=false}) {
  const [open, setOpen] = React.useState(null);
  const [picked, setPicked] = React.useState(null);
  const back = React.useRef(null);
  const query = useQuery({
    queryKey: ['session-pipeline', scope, gameId, sessionId || ''],
    queryFn: ({signal}) => onLoad({sessionId: sessionId || null, signal}),
    refetchInterval: current => (current.state.data?.manifest?.nodes || []).some(node => node.status === 'running' || node.status === 'queued') ? 5000 : 15000,
    retry: false,
  });
  const data = query.data;
  const sessions = data?.sessions || [];
  const workers = data?.workers || [];
  const runs = data?.runs || [];
  const opened = Boolean(sessionId);
  const session = sessions.find(item => item.id === sessionId) || null;
  const headline = opened ? sessionHeadline(session?.title || data?.manifest?.title, sessionId) : 'Sessions';
  const [tracked, setTracked] = React.useState(sessionId || '');
  if (tracked !== (sessionId || '')) {
    setTracked(sessionId || '');
    setPicked(null);
    setOpen(null);
  }
  const active = runs.find(item => item.id === picked) || runs[0] || null;
  const nodes = active?.nodes || data?.manifest?.nodes || [];
  const edges = active?.edges || data?.manifest?.edges || [];
  const needed = new Set(active?.workers || data?.workersNeeded || []);
  React.useEffect(() => { if (opened) back.current?.focus(); }, [opened, sessionId]);
  const Heading = embedded ? 'h2' : 'h1';
  const listPath = `/games/${encodeURIComponent(gameId)}/pipeline`;
  return <section className={`pipeline-page${embedded ? ' pipeline-embedded' : ''}`} aria-label={opened ? 'Session' : 'Sessions'}>
    <header className="page-heading pipeline-heading">
      <div>
        {opened && headline !== 'Session' && <p className="pipeline-kicker">Session</p>}
        <Heading>{headline}</Heading>
        {opened && <Finals finals={session?.finals}/>}
      </div>
      <div className="pipeline-tools">
        {workers.length > 0 && <ul className="pipeline-workers" aria-label="Workers">{workers.map(worker => {
          const online = worker.status === 'ready';
          const label = `${workerLabel(worker.id)} ${online ? 'online' : 'offline'}`;
          return <li key={worker.id} className="pipeline-worker" data-status={online ? 'online' : 'offline'} title={worker.message || label}>{label}</li>;
        })}</ul>}
        {opened && runs.length > 1 && <Select value={`run:${active?.id || runs[0].id}`} onValueChange={value => setPicked(value.slice(4))}>
          <SelectTrigger aria-label="Run"><SelectValue/></SelectTrigger>
          <SelectContent>{runs.map(run => <SelectItem key={run.id} value={`run:${run.id}`}>{runIdentity(run)?.slice(0, 8) || 'Run'}{formatWhen(run.startedAt) ? ` · ${formatWhen(run.startedAt)}` : ''}</SelectItem>)}</SelectContent>
        </Select>}
      </div>
    </header>
    {opened && workers.filter(worker => needed.has(worker.id) && worker.status && worker.status !== 'ready').map(worker => <p role="alert" className="pipeline-error" key={`${worker.id}-alert`}><CircleAlert size={16}/>{worker.message}</p>)}
    {query.isPending && <div className="pipeline-loading" aria-label="Loading sessions"><div/><div/><div/></div>}
    {query.error && <div><p role="alert" className="pipeline-error"><CircleAlert size={16}/>{query.error.message || 'The sessions could not be loaded.'}</p><Button variant="outline" onClick={() => query.refetch()}>Retry sessions</Button></div>}
    {data && !opened && sessions.length > 0 && <ul className="pipeline-cards" aria-label="Sessions">{sessions.map(item => {
      const tone = cardTone(item.status);
      return <li key={item.id}><button type="button" className="pipeline-card" data-status={tone} aria-label={`${sessionHeadline(item.title, item.id)}, ${cardText(item)}`} onClick={() => onNavigate(`${listPath}/${encodeURIComponent(item.id)}`)}>
        <span className="pipeline-mark" aria-hidden="true">{tone === 'failed' ? '×' : ''}</span>
        <span className="pipeline-card-copy">
          <strong className="pipeline-card-name">{sessionHeadline(item.title, item.id)}</strong>
          <span className="pipeline-card-stage">{cardText(item)}</span>
          <Finals finals={item.finals}/>
        </span>
      </button></li>;
    })}</ul>}
    {data && !opened && sessions.length === 0 && <p className="pipeline-card-stage">No sessions yet.</p>}
    {opened && data && <div className="pipeline-run">
      <Button ref={back} variant="outline" className="pipeline-back" onClick={() => { setOpen(null); onNavigate(listPath); }}>Sessions</Button>
      <Graph nodes={nodes} edges={edges} onOpen={setOpen} label="Session pipeline"/>
      <Detail node={open} onPreview={onPreview} onClose={() => setOpen(null)}/>
    </div>}
  </section>;
}
