import { useMemo, useSyncExternalStore } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { RunStore } from "../lib/store";
import { DebateFeed } from "../components/feed";
import { Dossier, Rail } from "../components/panels";
import { ccy, fmtPrice } from "../lib/format";

/* Stores survive route changes & strict re-mounts; one per run id. */
const stores = new Map<string, RunStore>();

function getStore(runId: string, ticker: string): RunStore {
  let s = stores.get(runId);
  if (!s) {
    s = new RunStore(runId, ticker);
    s.connect();
    stores.set(runId, s);
  }
  return s;
}

export default function RunView() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  const ticker = params.get("t") ?? "";

  const store = useMemo(() => getStore(runId, ticker), [runId, ticker]);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot);

  return (
    <div className="run">
      <header className="topbar">
        <Link to="/" className="wordmark" style={{ fontSize: 13 }}>DELPHI</Link>
        <div className="tk-chip">
          <span className="tk">{state.ticker}</span>
          <span className="co">{state.company}</span>
          {state.snapshot && <span className="px">{fmtPrice(state.snapshot.last_price, ccy(state.snapshot.currency))}</span>}
        </div>
        <span className="spacer" />
        {state.mode && <span className="mode-badge" data-mode={state.mode}>{state.mode.toUpperCase()}</span>}
        {state.published && (
          <Link className="btn-ghost" to={`/run/${runId}/note`}>READ THE NOTE →</Link>
        )}
      </header>
      <div className="run-body">
        <Rail s={state} />
        <DebateFeed feed={state.feed} published={state.published} runId={runId} failed={state.failed} />
        <Dossier s={state} />
      </div>
    </div>
  );
}
