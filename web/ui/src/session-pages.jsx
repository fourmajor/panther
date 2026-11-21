import React from 'react';
import {useQuery} from '@tanstack/react-query';
import {CircleAlert} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
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

function Recap({scope, gameId, sourceKey, text, onSummary, compact}) {
  const query = useQuery({
    queryKey: ['session-recap', scope, gameId, sourceKey || ''],
    enabled: !text && Boolean(sourceKey),
    queryFn: ({signal}) => onSummary({key: sourceKey, signal}),
    staleTime: 60000,
    retry: false,
    refetchInterval: current => ['QUEUED', 'GENERATING'].includes(current.state.data?.status) ? 5000 : false,
  });
  const loaded = text || query.data?.summary?.summary;
  if (!sourceKey && !text) return compact ? <p className="session-card-summary">No recap yet.</p> : <p className="session-empty">No recap has been written for this session yet.</p>;
  if (!loaded && query.isPending) return <div className="session-recap-loading" aria-label="Loading recap"/>;
  if (!loaded && query.error) {
    if (query.error.status === 400) return compact ? <p className="session-card-summary">No recap yet.</p> : <p className="session-empty">No recap has been written for this session yet.</p>;
    if (compact) return <p className="session-card-summary">Recap unavailable.</p>;
    return <p role="alert" className="session-error"><CircleAlert size={16}/>Recap unavailable. <Button variant="outline" size="sm" onClick={() => query.refetch()}>Retry recap</Button></p>;
  }
  if (!loaded || query.data?.status === 'MISSING') {
    return compact ? <p className="session-card-summary">No recap yet.</p> : <p className="session-empty">No recap has been written for this session yet.</p>;
  }
  const body = String(loaded);
  const short = body.length > 180 ? `${body.slice(0, 180).replace(/\s+\S*$/, '')}…` : body;
  return <p className={compact ? 'session-card-summary' : 'session-recap'}>{compact ? short : body}</p>;
}

function Thumb({scope, gameId, imageKey, onImage}) {
  const query = useQuery({
    queryKey: ['session-thumb', scope, gameId, imageKey || ''],
    enabled: Boolean(imageKey),
    queryFn: () => onImage(imageKey),
    staleTime: 240000,
    retry: false,
  });
  if (query.data) return <img src={query.data} alt="" />;
  return <span className="session-thumb-fallback">{imageKey && query.isPending ? '' : 'No thumbnail'}</span>;
}

function AssetList({title, assets, empty, scope, gameId, onImage, onPreview}) {
  return <section className="session-asset-group" aria-label={title}>
    <h3>{title}</h3>
    {assets.length === 0 && <p className="session-empty">{empty}</p>}
    {assets.length > 0 && <ul className="session-assets">{assets.map(asset => <li key={asset.key}>
      <article className="session-asset">
        <div className="session-asset-preview">{asset.preview === 'image' ? <Thumb scope={scope} gameId={gameId} imageKey={asset.thumbnailKey || asset.key} onImage={onImage}/> : <span className="session-thumb-fallback">{asset.kindLabel}</span>}</div>
        <div className="session-asset-copy">
          <strong>{asset.title || asset.name || asset.kindLabel}</strong>
          <p>{asset.kindLabel}</p>
          <p>{bytes(asset.size)} · {when(asset.createdAt) || 'Created time unknown'}</p>
          <Button variant="outline" size="sm" onClick={() => onPreview(asset.key)}>Open</Button>
        </div>
      </article>
    </li>)}</ul>}
  </section>;
}

function Player({recordingKey, onSign, onDownload}) {
  const query = useQuery({
    queryKey: ['session-recording', recordingKey || ''],
    enabled: Boolean(recordingKey),
    queryFn: () => onSign(recordingKey),
    staleTime: 240000,
    retry: false,
  });
  if (!recordingKey) return <p className="session-empty">No listening copy has been published for this session yet.</p>;
  if (query.isPending) return <div className="session-player-loading" aria-label="Loading recording"/>;
  if (query.error || !query.data?.url) return <div><p role="alert" className="session-error"><CircleAlert size={16}/>The recording could not be loaded.</p><Button variant="outline" onClick={() => query.refetch()}>Retry recording</Button></div>;
  return <div className="session-player">
    <audio controls preload="none" src={query.data.url} data-key={recordingKey} aria-label="Session recording"/>
    <SessionDownload onDownload={() => onDownload(recordingKey)}/>
  </div>;
}

function Detail({gameId, scope, session, listPath, onNavigate, onPreview, onSign, onDownload, onSummary, onImage}) {
  return <article className="session-detail">
    <Link href={listPath} onNavigate={onNavigate} className="session-back">Sessions</Link>
    <header className="session-detail-heading">
      <h1>{session.title}</h1>
      <span className="session-status" data-status={session.status}>{session.statusLabel}</span>
    </header>
    <section className="session-block" aria-label="Recording">
      <h2>Recording</h2>
      <Player recordingKey={session.recordingKey} onSign={onSign} onDownload={onDownload}/>
    </section>
    <section className="session-block" aria-label="Session info">
      <h2>Session info</h2>
      <dl className="session-facts">
        <dt>Date</dt><dd>{when(session.occurredAt) || 'Date unknown'}</dd>
        <dt>Players</dt><dd>{names(session.players, 'No players recorded')}</dd>
        <dt>Characters</dt><dd>{names(session.characters, 'No characters linked')}</dd>
      </dl>
      <h3>Recap</h3>
      <Recap scope={scope} gameId={gameId} sourceKey={session.summarySourceKey} text={session.summaryText} onSummary={onSummary}/>
    </section>
    <section className="session-block" aria-label="Assets">
      <h2>Assets</h2>
      <AssetList title="Final assets" assets={session.finalAssets || []} empty="No final assets yet." scope={scope} gameId={gameId} onImage={onImage} onPreview={onPreview}/>
      <AssetList title="Intermediary assets" assets={session.intermediaryAssets || []} empty="No intermediary assets for this session." scope={scope} gameId={gameId} onImage={onImage} onPreview={onPreview}/>
    </section>
    <section className="session-block" aria-label="Pipelines">
      <h2>Pipelines</h2>
      {(session.pipelines || []).length === 0 && <p className="session-empty">No pipeline runs are tied to this session.</p>}
      {(session.pipelines || []).length > 0 && <ul className="session-runs">{session.pipelines.map(run => <li key={run.id}>
        <article className="session-run">
          <header><strong>{run.type}</strong><span className="session-status" data-status={run.status}>{run.statusLabel}</span></header>
          {run.title && run.title !== run.type && <p>{run.title}</p>}
          <dl>
            <dt>Started</dt><dd>{when(run.startedAt) || 'Unknown'}</dd>
            <dt>Ended</dt><dd>{when(run.endedAt) || (run.status === 'running' || run.status === 'queued' ? 'In progress' : 'Unknown')}</dd>
            <dt>Duration</dt><dd>{duration(run.durationSeconds) || 'Unknown'}</dd>
          </dl>
          {run.message && <p className="session-run-log">{run.message}</p>}
          <div className="session-run-links">
            {run.detailPath && <Link href={run.detailPath} onNavigate={onNavigate}>Details</Link>}
            {run.pipelinePath && <Link href={run.pipelinePath} onNavigate={onNavigate}>Pipeline</Link>}
          </div>
        </article>
      </li>)}</ul>}
    </section>
  </article>;
}

export function SessionPages({gameId, scope, sessionId, onLoad, onNavigate, onPreview, onSign, onDownload, onSummary, onImage}) {
  const query = useQuery({
    queryKey: ['session-pages', scope, gameId, sessionId || ''],
    queryFn: ({signal}) => onLoad({sessionId: sessionId || null, signal}),
    retry: false,
    refetchInterval: 20000,
  });
  const listPath = `/games/${encodeURIComponent(gameId)}/sessions`;
  const data = query.data;
  return <div className="session-pages">
    {query.isPending && <div className="session-grid" aria-label="Loading sessions">{[0, 1, 2].map(item => <div className="session-tile session-tile-loading" key={item}><div className="session-thumb"/><div className="session-line"/><div className="session-line session-line-short"/></div>)}</div>}
    {query.error && <div><p role="alert" className="session-error"><CircleAlert size={16}/>{query.error.message || 'Sessions could not be loaded.'}</p><Button variant="outline" onClick={() => query.refetch()}>Retry sessions</Button></div>}
    {data && !data.complete && <p role="status" className="session-note">Some catalog pages were not read. This list may be missing assets. <Button variant="outline" size="sm" onClick={() => query.refetch()}>Retry sessions</Button></p>}
    {data && !sessionId && <section aria-label="Sessions">
      {data.sessions.length === 0 && <p className="session-empty">No sessions yet.</p>}
      {data.sessions.length > 0 && <ul className="session-grid">{data.sessions.map(item => <li key={item.id}>
        <Link href={item.href || `${listPath}/${encodeURIComponent(item.id)}`} onNavigate={onNavigate} className="session-tile" data-status={item.status} aria-label={`${item.title}, ${item.statusLabel}`}>
          <span className="session-thumb"><Thumb scope={scope} gameId={gameId} imageKey={item.thumbnailKey} onImage={onImage}/></span>
          <span className="session-tile-copy">
            <strong>{item.title}</strong>
            <span className="session-date">{when(item.occurredAt) || 'Date unknown'}</span>
            <Recap scope={scope} gameId={gameId} sourceKey={item.summarySourceKey} text={item.summaryText} onSummary={onSummary} compact/>
            <span className="session-status" data-status={item.status}>{item.statusLabel}</span>
          </span>
        </Link>
      </li>)}</ul>}
    </section>}
    {data && sessionId && data.session && <Detail gameId={gameId} scope={scope} session={data.session} listPath={listPath} onNavigate={onNavigate} onPreview={onPreview} onSign={onSign} onDownload={onDownload} onSummary={onSummary} onImage={onImage}/>}
    {data && sessionId && !data.session && <p className="session-empty">This session is not in the catalog.</p>}
  </div>;
}
