import { QueryClient } from "@tanstack/react-query";

// Browser GETs only: prevent thumbnail bursts from exhausting a small account's
// concurrency and give an explicitly opened document priority over background reads.
export function createReadScheduler({limit=3,wait=ms=>new Promise(resolve=>setTimeout(resolve,ms))}={}) {
  let active=0;
  const pending=[];
  function drain(){
    while(active<limit&&pending.length){
      const task=pending.shift();active++;
      (async()=>{
        try{
          for(let attempt=0;;attempt++){
            try{return task.resolve(await task.fetcher());}
            catch(error){
              if(attempt>=2||![429,502,503,504].includes(error.status))throw error;
              await wait(350*2**attempt+Math.floor(Math.random()*150));
            }
          }
        }catch(error){task.reject(error);}
        finally{active--;drain();}
      })();
    }
  }
  return (fetcher,{priority=0}={})=>new Promise((resolve,reject)=>{
    pending.push({fetcher,priority,resolve,reject});pending.sort((a,b)=>b.priority-a.priority);drain();
  });
}
export const readRequest=createReadScheduler();

export const queryClient = new QueryClient({ defaultOptions: { queries: {
  staleTime: 60_000, gcTime: 15 * 60_000, retry: false, refetchOnWindowFocus: true,
} } });
export function query({ scope, path, parameters, fetcher, staleTime }) {
  return queryClient.fetchQuery({ queryKey: ["api", scope, path, parameters], queryFn: fetcher,
    ...(staleTime === undefined ? {} : { staleTime }) });
}
function inGame(parameters, gameId) {
  if (!gameId) return true;
  if (parameters.gameId) return parameters.gameId === gameId;
  const key = parameters.prefix || parameters.key;
  return !key || key.startsWith(`games/${gameId}/`);
}
export function invalidate(scope, paths, gameId) {
  return queryClient.invalidateQueries({ predicate: candidate => {
    const [kind, owner, path, parameters = {}] = candidate.queryKey;
    return kind === "api" && owner === scope && (!paths || paths.includes(path)) && inGame(parameters, gameId);
  } });
}
// The migration bridge has no React observer for legacy DOM views. Revalidate
// only the visible view's stale, non-polling reads, then let that view redraw
// from the already-warm cache. Fresh foreground visits make no requests.
export async function revalidate({scope, paths, gameId, filters = {}}) {
  const candidates = queryClient.getQueryCache().findAll({predicate: candidate => {
    const [kind, owner, path, parameters = {}] = candidate.queryKey;
    const freshness = candidate.options.staleTime ?? 60_000;
    return kind === "api" && owner === scope && paths.includes(path) && freshness > 0
      && inGame(parameters, gameId)
      && Object.entries(filters[path] || {}).every(([key, value]) => parameters[key] === value)
      && candidate.isStaleByTime(freshness);
  }}).slice(0, 12);
  const results = await Promise.allSettled(candidates.map(async candidate => {
    const previous = candidate.state.data;
    const data = await queryClient.fetchQuery({...candidate.options, retry:false});
    return data === previous ? null : {path:candidate.queryKey[2], parameters:candidate.queryKey[3], data};
  }));
  return results.filter(result => result.status === "fulfilled" && result.value).map(result => result.value);
}
export function clear() { queryClient.clear(); }
