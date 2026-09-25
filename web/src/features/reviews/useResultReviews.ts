import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';

export function useResultReviews(source: 'screen' | 'sequoia', runId?: string) {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = useRef(runId);
  current.current = runId;
  useEffect(() => {
    let active = true;
    setSymbols([]); setError(''); setBusy(Boolean(runId));
    if (runId) api.resultReviews(source, runId).then(value => { if (active) setSymbols(value); })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [source, runId]);
  async function toggle(symbol: string) {
    if (!runId || busy) return;
    setBusy(true); setError('');
    try {
      const value = await api.saveResultReview(source, runId, symbol, !symbols.includes(symbol));
      if (current.current === runId) setSymbols(previous => value.failed ? [...new Set([...previous, symbol])] : previous.filter(s => s !== symbol));
      return true;
    } catch (e) { if (current.current === runId) setError((e as Error).message); return false; }
    finally { if (current.current === runId) setBusy(false); }
  }
  return { symbols, busy, error, toggle };
}
