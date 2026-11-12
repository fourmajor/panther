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

function listedPipelines(data) {
  if (Array.isArray(data?.pipelines)) return data.pipelines;
  const manifest = data?.manifest;
  if (!manifest?.nodes) return [];
  return [{id: 'story', name: 'Transcript → story & screen planning', workers: ['editorial'], status: 'pending', stage: null, updatedAt: manifest.updatedAt || 0, run: null, nodes: manifest.nodes, edges: manifest.edges || []}];
}

export function SessionPipeline({gameId, scope, sessionId, onLoad, onNavigate, onPreview, embedded=false}) {
  const [open, setOpen] = React.useState(null);
  const [pipelineId, setPipelineId] = React.useState(null);
  const back = React.useRef(null);
  const query = useQuery({
    queryKey: ['session-pipeline', scope, gameId, sessionId || ''],
    queryFn: ({signal}) => onLoad({sessionId: sessionId || null, signal}),
    refetchInterval: current => listedPipelines(current.state.data).flatMap(item => item.nodes || []).some(node => node.status === 'running' || node.status === 'queued') ? 5000 : 15000,
    retry: false,
  });
  const manifest = query.data?.manifest;
  const sessions = query.data?.sessions || [];
  const workers = query.data?.workers || [];
  const pipelines = listedPipelines(query.data);
  const selected = sessionId || manifest?.sessionId || '';
  const headline = sessionHeadline(manifest?.title, selected);
  const pipeline = pipelines.find(item => item.id === pipelineId) || null;
  const needed = new Set(pipeline?.workers || []);
  const [trackedSession, setTrackedSession] = React.useState(selected);
  if (trackedSession !== selected) {
    setTrackedSession(selected);
    setPipelineId(null);
    setOpen(null);
  }
  React.useEffect(() => { if (pipelineId) back.current?.focus(); }, [pipelineId]);
  const Heading = embedded ? 'h2' : 'h1';
  const updated = pipeline ? formatWhen(pipeline.updatedAt) : null;
  return <section className={`pipeline-page${embedded ? ' pipeline-embedded' : ''}`} aria-label="Session">
    <header className="page-heading pipeline-heading">
      <div>
        {headline !== 'Session' && <p className="pipeline-kicker">Session</p>}
        <Heading>{headline}</Heading>
      </div>
      <div className="pipeline-tools">
        {workers.length > 0 && <ul className="pipeline-workers" aria-label="Workers">{workers.map(worker => {
          const online = worker.status === 'ready';
          const label = `${workerLabel(worker.id)} ${online ? 'online' : 'offline'}`;
          return <li key={worker.id} className="pipeline-worker" data-status={online ? 'online' : 'offline'} title={worker.message || label}>{label}</li>;
        })}</ul>}
        {sessions.length > 0 && <Select value={selected ? `option:${selected}` : undefined} onValueChange={value => onNavigate(`/games/${encodeURIComponent(gameId)}/pipeline/${encodeURIComponent(value.slice(7))}`)}>
          <SelectTrigger aria-label="Session"><SelectValue placeholder="Session"/></SelectTrigger>
          <SelectContent>{sessions.map(session => <SelectItem key={session.id} value={`option:${session.id}`}>{sessionHeadline(session.title, session.id)}</SelectItem>)}</SelectContent>
        </Select>}
      </div>
    </header>
    {pipeline && workers.filter(worker => needed.has(worker.id) && worker.status && worker.status !== 'ready').map(worker => <p role="alert" className="pipeline-error" key={`${worker.id}-alert`}><CircleAlert size={16}/>{worker.message}</p>)}
    {query.isPending && <div className="pipeline-loading" aria-label="Loading session"><div/><div/><div/><div/></div>}
    {query.error && <div><p role="alert" className="pipeline-error"><CircleAlert size={16}/>{query.error.message || 'The session could not be loaded.'}</p><Button variant="outline" onClick={() => query.refetch()}>Retry session</Button></div>}
    {query.data && !pipeline && <div>
      <h2 id="pipeline-list-title" className="pipeline-section">Pipelines</h2>
      <ul className="pipeline-cards" aria-labelledby="pipeline-list-title">{pipelines.map(item => {
        const tone = cardTone(item.status);
        const when = formatWhen(item.updatedAt);
        return <li key={item.id}><button type="button" className="pipeline-card" data-status={tone} aria-label={`${item.name}, ${cardText(item)}`} onClick={() => setPipelineId(item.id)}>
          <span className="pipeline-mark" aria-hidden="true">{tone === 'failed' ? '×' : ''}</span>
          <span className="pipeline-card-copy">
            <strong className="pipeline-card-name">{item.name}</strong>
            <span className="pipeline-card-stage">{cardText(item)}</span>
            {when && <span className="pipeline-card-time">Updated {when}</span>}
          </span>
        </button></li>;
      })}</ul>
    </div>}
    {pipeline && <div className="pipeline-run">
      <Button ref={back} variant="outline" className="pipeline-back" onClick={() => { setPipelineId(null); setOpen(null); }}>Pipelines</Button>
      <p className="pipeline-kicker">Pipeline</p>
      <h2>{pipeline.name}</h2>
      <dl className="pipeline-facts">
        <div><dt>Run</dt><dd className="pipeline-run-id">{runIdentity(pipeline.run) || 'No run yet'}</dd></div>
        <div><dt>Started</dt><dd>{formatWhen(pipeline.run?.startedAt) || 'Not started'}</dd></div>
        <div><dt>Status</dt><dd data-status={cardTone(pipeline.status)}>{cardText(pipeline)}</dd></div>
      </dl>
      {updated && <p className="pipeline-card-time">Updated {updated}</p>}
      <Graph nodes={pipeline.nodes || []} edges={pipeline.edges || []} onOpen={setOpen} label={`${pipeline.name} stages`}/>
      <Detail node={open} onPreview={onPreview} onClose={() => setOpen(null)}/>
    </div>}
  </section>;
}
