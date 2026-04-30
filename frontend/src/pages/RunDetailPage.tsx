import { useEffect, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';

import { RunCharts } from '../components/run-detail/RunCharts';
import { NextResearchStepsPanel } from '../components/run-detail/NextResearchStepsPanel';
import { ParameterSweepResults } from '../components/run-detail/ParameterSweepResults';
import { RunHeader } from '../components/run-detail/RunHeader';
import { RunInsightBreakdown } from '../components/run-detail/RunInsightBreakdown';
import { RunInsightHero } from '../components/run-detail/RunInsightHero';
import { RunMetaPanel } from '../components/run-detail/RunMetaPanel';
import { SaveStrategyModal } from '../components/run-detail/SaveStrategyModal';
import { StateCard } from '../components/shared/StateCard';
import { fetchRun, fetchRunDashboard, saveDraftRunAsStrategy } from '../lib/api';
import { suggestStrategyNameFromConfig } from '../lib/suggestStrategyName';
import type { RunDashboardResponse, RunResponse } from '../types/api';

const ACTIVE_RUN_STATUSES = new Set(['PENDING', 'QUEUED', 'RUNNING']);
const POLL_INTERVAL_MS = 2000;

type NoticeTone = 'info' | 'success' | 'error';

type PageNotice = {
  tone: NoticeTone;
  message: string;
};

function NoticeBanner({
  notice,
  onDismiss
}: {
  notice: PageNotice;
  onDismiss: () => void;
}) {
  const toneClass =
    notice.tone === 'success'
      ? 'app-alert-success'
      : notice.tone === 'error'
        ? 'app-alert-error'
        : 'app-note';

  return (
    <div className={`rounded-2xl border px-4 py-3 text-sm ${toneClass}`}>
      <div className="flex items-start justify-between gap-4">
        <p>{notice.message}</p>
        <button
          type="button"
          onClick={onDismiss}
          className="text-xs font-semibold uppercase tracking-[0.2em] opacity-80 transition hover:opacity-100"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

function formatSaveStrategyError(error: unknown): string {
  const message = error instanceof Error ? error.message : 'Failed to save strategy';

  if (message.includes('Saved strategy limit reached')) {
    return 'Saved strategy limit reached. Go to Strategy Library and archive an older strategy, then try saving again.';
  }

  return message;
}

export function RunDetailPage() {
  const { runId } = useParams();
  const location = useLocation();

  const [run, setRun] = useState<RunResponse | null>(null);
  const [data, setData] = useState<RunDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [isSavingDraftStrategy, setIsSavingDraftStrategy] = useState(false);
  const [isSaveStrategyModalOpen, setIsSaveStrategyModalOpen] = useState(false);
  const [saveStrategyError, setSaveStrategyError] = useState<string | null>(null);
  const [notice, setNotice] = useState<PageNotice | null>(
    (location.state as { notice?: PageNotice } | null)?.notice ?? null
  );

  useEffect(() => {
    const incomingNotice = (location.state as { notice?: PageNotice } | null)?.notice ?? null;
    if (incomingNotice) {
      setNotice(incomingNotice);
    }
  }, [location.state]);

  useEffect(() => {
    let ignore = false;
    let timeoutId: number | undefined;

    async function load() {
      if (!runId) {
        setErrorMessage('Missing run id');
        setLoading(false);
        return;
      }

      try {
        const runResponse = await fetchRun(runId);
        if (ignore) return;

        setRun(runResponse);

        if (runResponse.status === 'SUCCEEDED') {
          setIsFinalizing(true);
          setLoading(false);
          setErrorMessage(null);

          try {
            const dashboardResponse = await fetchRunDashboard(runId);
            if (ignore) return;

            setData(dashboardResponse);
            setIsFinalizing(false);
            setErrorMessage(null);
            setLoading(false);
            return;
          } catch {
            if (ignore) return;

            setData(null);
            setIsFinalizing(true);
            setErrorMessage(null);
            setLoading(false);

            timeoutId = window.setTimeout(() => {
              void load();
            }, POLL_INTERVAL_MS);

            return;
          }
        }

        if (runResponse.status === 'FAILED' || runResponse.status === 'CANCELLED') {
          setData(null);
          setIsFinalizing(false);
          setErrorMessage(runResponse.error_message ?? `Run ${runResponse.status.toLowerCase()}.`);
          setLoading(false);
          return;
        }

        if (ACTIVE_RUN_STATUSES.has(runResponse.status)) {
          setData(null);
          setIsFinalizing(false);
          setErrorMessage(null);
          setLoading(false);

          timeoutId = window.setTimeout(() => {
            void load();
          }, POLL_INTERVAL_MS);

          return;
        }

        setData(null);
        setIsFinalizing(false);
        setErrorMessage(`Unsupported run status: ${runResponse.status}`);
        setLoading(false);
      } catch (error) {
        if (ignore) return;
        setData(null);
        setIsFinalizing(false);
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load result');
        setLoading(false);
      }
    }

    setLoading(true);
    setErrorMessage(null);
    setRun(null);
    setData(null);
    setIsFinalizing(false);
    void load();

    return () => {
      ignore = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [runId]);

  const suggestedStrategyName = suggestStrategyNameFromConfig(run?.request_payload?.draft_config);
  const isParameterSweep = data?.run.run_type === 'PARAMETER_SWEEP';

  async function handleSaveDraftStrategy(payload: { name: string; description: string }) {
    if (!runId || !run) return;
    if (run.strategy_id) return;

    setSaveStrategyError(null);
    setIsSavingDraftStrategy(true);

    try {
      await saveDraftRunAsStrategy(runId, {
        name: payload.name,
        description: payload.description || `Saved from result ${runId}`,
        strategy_type: 'SINGLE_ASSET'
      });

      const refreshedRun = await fetchRun(runId);
      setRun(refreshedRun);
      setData((currentData) => currentData ? { ...currentData, run: refreshedRun } : currentData);
      setIsSaveStrategyModalOpen(false);
      setNotice({
        tone: 'success',
        message: 'Strategy saved successfully.'
      });
    } catch (error) {
      setSaveStrategyError(formatSaveStrategyError(error));
    } finally {
      setIsSavingDraftStrategy(false);
    }
  }

  if (loading) {
    return <StateCard title="Loading result" description="Fetching result status and dashboard data from the backend." />;
  }

  if (isFinalizing) {
    return (
      <div className="space-y-6">
        {notice ? <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} /> : null}
        <StateCard
          title="Preparing simulation results"
          description="Your result has finished. Final charts and metrics are loading."
        />
        {run ? <RunMetaPanel run={run} /> : null}
      </div>
    );
  }

  if (run && ACTIVE_RUN_STATUSES.has(run.status)) {
    return (
      <div className="space-y-6">
        {notice ? <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} /> : null}
        <StateCard
          title="Simulation in progress"
          description={
            run.progress_message
              ? `${run.progress_message} (${run.progress_pct}%)`
              : `Result status: ${run.status}. Waiting for completion...`
          }
        />
        <RunMetaPanel run={run} />
      </div>
    );
  }

  if (run && (run.status === 'FAILED' || run.status === 'CANCELLED')) {
    return (
      <div className="space-y-6">
        {notice ? <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} /> : null}
        <StateCard
          title={`Result ${run.status.toLowerCase()}`}
          description={run.error_message ?? 'This result did not complete successfully.'}
          tone="error"
        />
        <RunMetaPanel run={run} />
      </div>
    );
  }

  if (errorMessage || !data) {
    return (
      <div className="space-y-6">
        {notice ? <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} /> : null}
        <StateCard
          title="Unable to load result dashboard"
          description={errorMessage ?? 'Result dashboard was not available.'}
          tone="error"
        />
      </div>
    );
  }

  return (
    <>
      <div className="space-y-6">
        {notice ? <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} /> : null}

        {run ? (
          <RunHeader run={run} />
        ) : null}

        {isParameterSweep ? (
          <ParameterSweepResults run={data.run} />
        ) : (
          <>
            <RunInsightHero run={data.run} chartData={data.chart_data} />

            <NextResearchStepsPanel
              run={data.run}
              canSaveDraftStrategy={data.run.status === 'SUCCEEDED' && !data.run.strategy_id}
              isSavingDraftStrategy={isSavingDraftStrategy}
              onSaveDraftStrategy={() => {
                setSaveStrategyError(null);
                setIsSaveStrategyModalOpen(true);
              }}
            />

            <RunInsightBreakdown run={data.run} />

            <RunCharts chartData={data.chart_data} run={data.run} />
          </>
        )}

        <RunMetaPanel run={data.run} />
      </div>

      <SaveStrategyModal
        isOpen={isSaveStrategyModalOpen}
        initialName={suggestedStrategyName}
        isSaving={isSavingDraftStrategy}
        errorMessage={saveStrategyError}
        onClose={() => {
          if (isSavingDraftStrategy) return;
          setSaveStrategyError(null);
          setIsSaveStrategyModalOpen(false);
        }}
        onSubmit={(payload) => {
          void handleSaveDraftStrategy(payload);
        }}
      />
    </>
  );
}
