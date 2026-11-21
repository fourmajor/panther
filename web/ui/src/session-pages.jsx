import React from 'react';
import {useQuery} from '@tanstack/react-query';
import {CircleAlert} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Input} from './components/ui/input.jsx';
import {SessionDownload} from './session-summary.jsx';
import {formatWhen} from './session-pipeline-model.js';

function when(value) {
  if (value == null || value === '') return null;
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return formatWhen(value);
  if (typeof value === 'string' && /^\d+(\.\d+)?$/.test(value)) return formatWhen(Number(value));
  const parsed = Date.parse(String(value));
  if (!Number.isFinite(parsed)) return null;
  return new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(parsed));
}

function duration(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total) || total < 0) return null;
  const rounded = Math.round(total);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function bytes(size) {
  const value = Number(size);
  if (!Number.isFinite(value) || value < 0) return 'Size unknown';
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function Link({href, onNavigate, className, children, ...props}) {
  return <a href={href} className={className} {...props} onClick={event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(href);
  }}>{children}</a>;
}

function names(people, empty) {
  if (!people?.length) return empty;
  return people.map(person => person.name || person.id).join(', ');
}

function excerptText(document) {
  if (!document || typeof document !== 'object') return null;
  const chapter = document.payload?.chapter || document.chapter || document.text || document.markdown;
  if (typeof chapter === 'string' && chapter.trim()) return chapter.trim();
  const segments = document.segments || document.payload?.transcript?.segments || document.transcript?.segments || document.payload?.segments;
  if (!Array.isArray(segments)) return null;
  const lines = segments.map(segment => (typeof segment?.text === 'string' && segment.text) || (typeof segment?.utterance === 'string' && segment.utterance) || '').map(line => line.trim()).filter(Boolean);
  return lines.length ? lines.slice(0, 4).join(' ') : null;
}

function Recap({scope, gameId, sourceKey, text, excerptKey, excerptLabel, onSummary, onExcerpt, compact}) {
  const query = useQuery({
    queryKey: ['session-recap', scope, gameId, sourceKey || ''],
    enabled: !text && Boolean(sourceKey),
    queryFn: ({signal}) => onSummary({key: sourceKey, signal}),
    staleTime: 60000,
    retry: false,
    refetchInterval: current => ['QUEUED', 'GENERATING'].includes(current.state.data?.status) ? 5000 : false,
  });
  const summaryMissing = !text && (!sourceKey || query.isError || query.data?.status === 'MISSING' || (query.isSuccess && !query.data?.summary?.summary));
  const excerpt = useQuery({
    queryKey: ['session-excerpt', scope, gameId, excerptKey || ''],
    enabled: summaryMissing && Boolean(excerptKey),
    queryFn: () => onExcerpt(excerptKey),
    staleTime: 300000,
    retry: false,
  });
  const loaded = text || query.data?.summary?.summary;
  const fallback = !loaded && summaryMissing ? excerptText(excerpt.data) : null;
  if (loaded) {
    const body = String(loaded);
    const short = body.length > 180 ? `${body.slice(0, 180).replace(/\s+\S*$/, '')}…` : body;
    return <p className={compact ? 'session-card-summary' : 'session-recap'}>{compact ? short : body}</p>;
  }
  if (sourceKey && query.isPending) return <div className="session-recap-loading" aria-label="Loading recap"/>;
  if (summaryMissing && excerptKey && excerpt.isPending) return <div className="session-recap-loading" aria-label="Loading recap"/>;
  if (fallback) {
    const short = fallback.length > 180 ? `${fallback.slice(0, 180).replace(/\s+\S*$/, '')}…` : fallback;
    return <p className={compact ? 'session-card-summary' : 'session-recap'}><span className="session-excerpt-label">{excerptLabel || 'Excerpt'}. </span>{compact ? short : fallback}</p>;
  }
  if (query.error && query.error.status !== 400 && !excerptKey) {
    if (compact) return <p className="session-card-summary">Recap unavailable.</p>;
    return <p role="alert" className="session-error"><CircleAlert size={16}/>Recap unavailable. <Button variant="outline" size="sm" onClick={() => query.refetch()}>Retry recap</Button></p>;
  }
  return compact ? <p className="session-card-summary">No recap yet.</p> : <p className="session-empty">No recap has been written for this session yet.</p>;
}

function Thumb({scope, gameId, imageKey, onImage}) {
  const query = useQuery({
    queryKey: ['session-thumb', scope, gameId, imageKey || ''],
    enabled: Boolean(imageKey),
    queryFn: () => onImage(imageKey),
    staleTime: 240000,
    retry: false,
  });
  if (query.data) return <img src={query.data} alt="" loading="lazy" decoding="async"/>;
  return <span className="session-thumb-fallback">{imageKey && query.isPending ? '' : 'No thumbnail'}</span>;
}

function createdStamp(asset) {
  if (typeof asset.createdAt === 'number') return asset.createdAt;
  const parsed = Date.parse(asset.createdAt || '');
  return Number.isFinite(parsed) ? parsed : 0;
}

function matchesAsset(asset, chip, query) {
  if (chip !== 'all' && asset.typeId !== chip) return false;
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [asset.name, asset.title, asset.kind, asset.kindLabel].some(value => String(value || '').toLowerCase().includes(needle));
}

function assetSummary(assets) {
  const files = assets.length === 1 ? '1 file' : `${assets.length} files`;
  const known = assets.map(asset => asset.size).filter(size => Number.isInteger(size) && size >= 0);
  if (!known.length) return files;
  const total = known.reduce((sum, size) => sum + size, 0);
  const label = bytes(total);
  return known.length === assets.length ? `${files}, ${label}` : `${files}, at least ${label}`;
}

function sortAssets(assets, newest) {
  return [...assets].sort((a, b) => (newest ? createdStamp(b) - createdStamp(a) : createdStamp(a) - createdStamp(b)) || String(a.key).localeCompare(String(b.key)));
}

function Disclosure({summary, forceOpen, children}) {
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => { setOpen(Boolean(forceOpen)); }, [forceOpen]);
  return <details className="session-disclosure" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{summary}</summary>
    {open ? <div className="session-disclosure-body">{children}</div> : null}
  </details>;
}

function AssetRow({asset, onPreview}) {
  return <div className="session-asset-row">
    <span><strong>{asset.title || asset.name || asset.kindLabel}</strong><small>{asset.kindLabel} · {bytes(asset.size)} · {when(asset.createdAt) || 'Created time unknown'}</small></span>
    <Button variant="outline" size="sm" onClick={() => onPreview(asset.key)}>Open</Button>
  </div>;
}

function AssetCards({assets, scope, gameId, onImage, onPreview, large=false}) {
  return <ul className={large ? 'session-final-grid' : 'session-image-grid'}>{assets.map(asset => <li key={asset.key}>
    <article className="session-final-card">
      <div className="session-thumb">{asset.preview === 'image' || asset.thumbnailKey ? <Thumb scope={scope} gameId={gameId} imageKey={asset.thumbnailKey || asset.key} onImage={onImage}/> : <span className="session-thumb-fallback">{asset.kindLabel}</span>}</div>
      <div className="session-asset-copy">
        <strong>{asset.title || asset.name || asset.kindLabel}</strong>
        <p>{asset.kindLabel} · {bytes(asset.size)}</p>
        <Button variant="outline" size="sm" onClick={() => onPreview(asset.key)}>Open</Button>
      </div>
    </article>
  </li>)}</ul>;
}

function Library({library, scope, gameId, onImage, onPreview, onShowRun}) {
  const [chip, setChip] = React.useState('all');
  const [query, setQuery] = React.useState('');
  const [newest, setNewest] = React.useState(true);
  const filtering = chip !== 'all' || query.trim() !== '';
  const finals = sortAssets((library?.finals || []).filter(asset => matchesAsset(asset, chip, query)), newest);
  const stages = (library?.stages || []).map(stage => ({
    ...stage,
    runs: stage.runs.map(run => ({
      ...run,
      types: run.types.map(group => ({...group, assets: sortAssets(group.assets.filter(asset => matchesAsset(asset, chip, query)), newest)})).filter(group => group.assets.length),
    })).filter(run => run.types.length),
  })).filter(stage => stage.runs.length);
  return <div className="session-library">
    <div className="session-asset-tools">
      <Input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search filename or type" aria-label="Search assets"/>
      <Button variant="outline" aria-pressed={newest} onClick={() => setNewest(value => !value)}>{newest ? 'Newest first' : 'Oldest first'}</Button>
    </div>
    <div className="session-chips" role="toolbar" aria-label="Asset types">
      <button type="button" className="session-chip" aria-pressed={chip === 'all'} onClick={() => setChip('all')}>All</button>
      {(library?.types || []).map(type => <button key={type.id} type="button" className="session-chip" aria-pressed={chip === type.id} onClick={() => setChip(type.id)}>{type.label}</button>)}
    </div>
    <section aria-label="Final assets">
      <h3>Final assets</h3>
      {finals.length ? <AssetCards assets={finals} scope={scope} gameId={gameId} onImage={onImage} onPreview={onPreview} large/> : <p className="session-empty">No final assets yet.</p>}
      {(library?.sceneClips || []).length > 0 && <Disclosure summary={<span className="session-disclosure-label"><strong>Scene clips</strong><span>{assetSummary(library.sceneClips)}</span></span>}>
        <AssetCards assets={library.sceneClips} scope={scope} gameId={gameId} onImage={onImage} onPreview={onPreview}/>
      </Disclosure>}
    </section>
    <section aria-label="Intermediary assets">
      <h3>Intermediary assets</h3>
      {stages.length === 0 && <p className="session-empty">No intermediary assets for this session.</p>}
      {stages.map(stage => {
        const stageAssets = stage.runs.flatMap(run => run.types.flatMap(group => group.assets));
        return <Disclosure key={stage.id} forceOpen={filtering} summary={<span className="session-disclosure-label"><strong>{stage.title}</strong><span>{assetSummary(stageAssets)}</span></span>}>
        {stage.runs.map(run => <div key={run.id || 'untied'} className="session-run-group">
          <p className="session-run-heading">{run.anchor ? <a href={`#${run.anchor}`} onClick={event => { event.preventDefault(); onShowRun(run.anchor); }}>{run.title}</a> : run.title}</p>
          {run.types.map(group => <Disclosure key={group.id} forceOpen={filtering} summary={<span className="session-disclosure-label"><strong>{group.title}</strong><span>{assetSummary(group.assets)}</span></span>}>
            {group.layout === 'images' ? <AssetCards assets={group.assets} scope={scope} gameId={gameId} onImage={onImage} onPreview={onPreview}/> : <div className="session-asset-rows">{group.assets.map(asset => <AssetRow key={asset.key} asset={asset} onPreview={onPreview}/>)}</div>}
          </Disclosure>)}
        </div>)}
      </Disclosure>;
      })}
    </section>
  </div>;
}

function Player({media, onSign, onDownload}) {
  const key = media?.key || null;
  const video = media?.media === 'video';
  const query = useQuery({
    queryKey: ['session-recording', key || ''],
    enabled: Boolean(key),
    queryFn: () => onSign(key),
    staleTime: 240000,
    retry: false,
  });
  if (!key) return <p className="session-empty">No listening copy has been published for this session yet.</p>;
  if (query.isPending) return <div className="session-player-loading" aria-label="Loading recording"/>;
  if (query.error || !query.data?.url) return <div><p role="alert" className="session-error"><CircleAlert size={16}/>The recording could not be loaded.</p><Button variant="outline" onClick={() => query.refetch()}>Retry recording</Button></div>;
  return <div className="session-player">
    {video
      ? <video controls playsInline preload="metadata" src={query.data.url} data-key={key} aria-label="Session video"/>
      : <audio controls preload="metadata" src={query.data.url} data-key={key} aria-label="Session recording"/>}
    <SessionDownload onDownload={() => onDownload(key)}/>
  </div>;
}

function pipelineGroups(runs) {
  const groups = [];
  for (const run of runs || []) {
    let group = groups.find(item => item.kind === run.kind);
    if (!group) {
      group = {kind: run.kind, type: run.type, runs: []};
      groups.push(group);
    }
    group.runs.push(run);
  }
  return groups.map(group => {
    const latest = group.runs[0];
    const measured = group.runs.filter(run => !run.stale && Number.isFinite(run.durationSeconds));
    const stale = group.runs.filter(run => run.stale).length;
    return {
      ...group,
      status: latest?.status,
      statusLabel: latest?.statusLabel,
      lastRun: latest?.startedAt,
      totalDuration: measured.length ? measured.reduce((sum, run) => sum + run.durationSeconds, 0) : null,
      stale,
    };
  });
}

function Detail({gameId, scope, session, listPath, onNavigate, onPreview, onSign, onDownload, onSummary, onExcerpt, onImage, libraryPending}) {
  const [currentRun, setCurrentRun] = React.useState(null);
  function showRun(anchor) {
    setCurrentRun(anchor);
    requestAnimationFrame(() => requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({block: 'nearest'})));
  }
  const groups = pipelineGroups(session.pipelines);
  return <article className="session-detail">
    <Link href={listPath} onNavigate={onNavigate} className="session-back">Sessions</Link>
    <header className="session-detail-heading">
      <h1>{session.title}</h1>
      <span className="session-status" data-status={session.status}>{session.statusLabel}</span>
    </header>
    <section className="session-block" aria-label="Recording">
      <h2>Recording</h2>
      <Player media={session.player || (session.recordingKey ? {key: session.recordingKey, media: 'audio'} : null)} onSign={onSign} onDownload={onDownload}/>
    </section>
    <section className="session-block" aria-label="Session info">
      <h2>Session info</h2>
      <dl className="session-facts">
        <dt>Date</dt><dd>{when(session.occurredAt) || 'Date unknown'}</dd>
        <dt>Players</dt><dd>{names(session.players, 'No players recorded')}</dd>
        <dt>Characters</dt><dd>{names(session.characters, 'No characters linked')}</dd>
      </dl>
      <h3>Recap</h3>
      <Recap scope={scope} gameId={gameId} sourceKey={session.summarySourceKey} text={session.summaryText} excerptKey={session.excerptKey} excerptLabel={session.excerptLabel} onSummary={onSummary} onExcerpt={onExcerpt}/>
    </section>
    <section className="session-block" aria-label="Assets">
      <h2>Assets</h2>
      {libraryPending && <p role="status" className="session-note">Loading the rest of this session&apos;s assets.</p>}
      <Library library={session.library} scope={scope} gameId={gameId} onImage={onImage} onPreview={onPreview} onShowRun={showRun}/>
    </section>
    <section className="session-block" aria-label="Pipelines">
      <h2>Pipelines</h2>
      {(session.pipelines || []).length === 0 && <p className="session-empty">No pipeline runs are tied to this session.</p>}
      {groups.map(group => {
        const last = when(group.lastRun);
        const total = duration(group.totalDuration);
        const summary = [
          group.runs.length === 1 ? '1 run' : `${group.runs.length} runs`,
          group.statusLabel,
          last,
          total,
          group.stale ? `${group.stale} stale` : null,
        ].filter(Boolean).join(' · ');
        return <Disclosure key={group.kind} forceOpen={group.runs.some(run => run.anchor && run.anchor === currentRun)} summary={<span className="session-disclosure-label"><strong>{group.type}</strong><span>{summary}</span></span>}>
          <ul className="session-runs">{group.runs.map(run => <li key={run.id}>
            <article className="session-run" id={run.anchor || undefined} data-current={currentRun === run.anchor ? 'true' : 'false'} data-stale={run.stale ? 'true' : 'false'}>
              <header><strong>{run.type}</strong><span className="session-status" data-status={run.stale ? 'paused' : run.status}>{run.stale ? 'Stale' : run.statusLabel}</span></header>
              {run.title && run.title !== run.type && <p>{run.title}</p>}
              <dl>
                <dt>Started</dt><dd>{when(run.startedAt) || 'Unknown'}</dd>
                <dt>Ended</dt><dd>{run.stale ? 'Abandoned' : when(run.endedAt) || (run.status === 'running' || run.status === 'queued' ? 'In progress' : 'Unknown')}</dd>
                <dt>Duration</dt><dd>{run.stale ? 'Stale' : duration(run.durationSeconds) || 'Unknown'}</dd>
              </dl>
              {run.message && <p className="session-run-log">{run.message}</p>}
              <div className="session-run-links">
                {run.detailPath && <Link href={run.detailPath} onNavigate={onNavigate}>Details</Link>}
                {run.pipelinePath && <Link href={run.pipelinePath} onNavigate={onNavigate}>Pipeline</Link>}
              </div>
            </article>
          </li>)}</ul>
        </Disclosure>;
      })}
    </section>
  </article>;
}

export function SessionPages({gameId, scope, sessionId, onLoad, onNavigate, onPreview, onSign, onDownload, onSummary, onExcerpt, onImage}) {
  const shell = useQuery({
    queryKey: ['session-pages', scope, gameId, sessionId || '', 'shell'],
    queryFn: ({signal}) => onLoad({sessionId: sessionId || null, part: 'shell', signal}),
    retry: false,
    staleTime: 60000,
  });
  const full = useQuery({
    queryKey: ['session-pages', scope, gameId, sessionId || '', 'full'],
    enabled: shell.isSuccess,
    queryFn: ({signal}) => onLoad({sessionId: sessionId || null, part: 'full', signal}),
    retry: false,
    staleTime: 60000,
  });
  const listPath = `/games/${encodeURIComponent(gameId)}/sessions`;
  const data = (sessionId && full.data) || shell.data;
  const libraryPending = Boolean(sessionId) && shell.data?.scope === 'shell' && !full.data;
  return <div className="session-pages">
    {shell.isPending && <div className="session-grid" aria-label="Loading sessions">{[0, 1, 2].map(item => <div className="session-tile session-tile-loading" key={item}><div className="session-thumb"/><div className="session-line"/><div className="session-line session-line-short"/></div>)}</div>}
    {shell.error && !data && <div><p role="alert" className="session-error"><CircleAlert size={16}/>{shell.error.message || 'Sessions could not be loaded.'}</p><Button variant="outline" onClick={() => shell.refetch()}>Retry sessions</Button></div>}
    {data && !data.complete && <p role="status" className="session-note">Some catalog pages were not read. This list may be missing assets. <Button variant="outline" size="sm" onClick={() => query.refetch()}>Retry sessions</Button></p>}
    {data && !sessionId && <section aria-label="Sessions">
      {data.sessions.length === 0 && <p className="session-empty">No sessions yet.</p>}
      {data.sessions.length > 0 && <ul className="session-grid">{data.sessions.map(item => <li key={item.id}>
        <Link href={item.href || `${listPath}/${encodeURIComponent(item.id)}`} onNavigate={onNavigate} className="session-tile" data-status={item.status} aria-label={`${item.title}, ${item.statusLabel}`}>
          <span className="session-thumb"><Thumb scope={scope} gameId={gameId} imageKey={item.thumbnailKey} onImage={onImage}/></span>
          <span className="session-tile-copy">
            <strong>{item.title}</strong>
            <span className="session-date">{when(item.occurredAt) || 'Date unknown'}</span>
            <Recap scope={scope} gameId={gameId} sourceKey={item.summarySourceKey} text={item.summaryText} excerptKey={item.excerptKey} excerptLabel={item.excerptLabel} onSummary={onSummary} onExcerpt={onExcerpt} compact/>
            <span className="session-status" data-status={item.status}>{item.statusLabel}</span>
          </span>
        </Link>
      </li>)}</ul>}
    </section>}
    {data && sessionId && data.session && <Detail gameId={gameId} scope={scope} session={data.session} listPath={listPath} onNavigate={onNavigate} onPreview={onPreview} onSign={onSign} onDownload={onDownload} onSummary={onSummary} onExcerpt={onExcerpt} onImage={onImage} libraryPending={libraryPending}/>}
    {sessionId && full.error && <p role="status" className="session-note">The rest of this session&apos;s assets did not load. <Button variant="outline" size="sm" onClick={() => full.refetch()}>Retry assets</Button></p>}
    {data && sessionId && !data.session && <p className="session-empty">This session is not in the catalog.</p>}
  </div>;
}
