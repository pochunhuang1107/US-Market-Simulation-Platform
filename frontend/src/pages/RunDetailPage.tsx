import { useEffect, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';

import { RunCharts } from '../components/run-detail/RunCharts';
import { ParameterSweepResults } from '../components/run-detail/ParameterSweepResults';
import { getDraftConfig, RunHeader } from '../components/run-detail/RunHeader';
import { RunInsightBreakdown } from '../components/run-detail/RunInsightBreakdown';
import { RunInsightHero } from '../components/run-detail/RunInsightHero';
import { RunMetaPanel } from '../components/run-detail/RunMetaPanel';
import { RotationRebalanceInspector } from '../components/run-detail/RotationRebalanceInspector';
import { SaveStrategyModal } from '../components/run-detail/SaveStrategyModal';
import { TradeEventInspector } from '../components/run-detail/TradeEventInspector';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import {
  artifactUnavailableMessage,
  fetchRun,
  fetchRunDashboard,
  fetchRunProgress,
  isArtifactUnavailableError,
  saveDraftRunAsStrategy
} from '../lib/api';
import { suggestStrategyNameFromConfig } from '../lib/suggestStrategyName';
import type { RunDashboardResponse, RunResponse } from '../types/api';

const ACTIVE_RUN_STATUSES = new Set(['PENDING', 'QUEUED', 'RUNNING']);
const UNSUCCESSFUL_RUN_STATUSES = new Set(['FAILED', 'CANCELED', 'CANCELLED']);
const ACTIVE_RUN_INITIAL_POLL_INTERVAL_MS = 750;
const ACTIVE_RUN_STEADY_POLL_INTERVAL_MS = 1500;
const ACTIVE_RUN_LONG_POLL_INTERVAL_MS = 3000;
const HIDDEN_TAB_POLL_INTERVAL_MS = 5000;
const FINALIZING_DASHBOARD_POLL_INTERVAL_MS = 2000;

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

function isRotationResult(run: RunResponse): boolean {
  const summary = run.summary_json ?? {};
  const draftConfig = getDraftConfig(run);
  const rotationConfig = draftConfig?.rotation;

  return Boolean(
    summary.strategy_type === 'rotation' ||
      Array.isArray(summary.rotation_universe) ||
      (rotationConfig && typeof rotationConfig === 'object' && 'enabled' in rotationConfig && rotationConfig.enabled === true)
  );
}

export function RunDetailPage() {
  const { runId } = useParams();
  const location = useLocation();

  const [run, setRun] = useState<RunResponse | null>(null);
  const [data, setData] = useState<RunDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [artifactUnavailable, setArtifactUnavailable] = useState<string | null>(null);
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
    let activePollStartedAt = Date.now();

    function activeProgressPollIntervalMs() {
      if (document.hidden) {
        return HIDDEN_TAB_POLL_INTERVAL_MS;
      }

      const elapsedMs = Date.now() - activePollStartedAt;
      if (elapsedMs < 10_000) {
        return ACTIVE_RUN_INITIAL_POLL_INTERVAL_MS;
      }
      if (elapsedMs < 60_000) {
        return ACTIVE_RUN_STEADY_POLL_INTERVAL_MS;
      }
      return ACTIVE_RUN_LONG_POLL_INTERVAL_MS;
    }

    function scheduleActiveProgressPoll() {
      timeoutId = window.setTimeout(() => {
        void pollProgress();
      }, activeProgressPollIntervalMs());
    }

    async function pollProgress() {
      if (!runId) return;

      try {
        const progressResponse = await fetchRunProgress(runId);
        if (ignore) return;

        setRun((currentRun) => {
          if (!currentRun || currentRun.id !== progressResponse.run_id) {
            return currentRun;
          }
          return {
            ...currentRun,
            status: progressResponse.status,
            progress_pct: progressResponse.progress_pct,
            progress_message: progressResponse.progress_message,
            heartbeat_at: progressResponse.heartbeat_at,
            updated_at: progressResponse.updated_at,
            is_terminal: progressResponse.is_terminal
          };
        });

        if (progressResponse.is_terminal || !ACTIVE_RUN_STATUSES.has(progressResponse.status)) {
          void load();
          return;
        }

        scheduleActiveProgressPoll();
      } catch (error) {
        if (ignore) return;
        setData(null);
        setIsFinalizing(false);
        setArtifactUnavailable(null);
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load result progress');
        setLoading(false);
      }
    }

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
            setArtifactUnavailable(null);
            setErrorMessage(null);
            setLoading(false);
            return;
          } catch (error) {
            if (ignore) return;

            if (isArtifactUnavailableError(error)) {
              setData(null);
              setIsFinalizing(false);
              setArtifactUnavailable(artifactUnavailableMessage(error));
              setErrorMessage(null);
              setLoading(false);
              return;
            }

            setData(null);
            setIsFinalizing(true);
            setArtifactUnavailable(null);
            setErrorMessage(null);
            setLoading(false);

            timeoutId = window.setTimeout(() => {
              void load();
            }, FINALIZING_DASHBOARD_POLL_INTERVAL_MS);

            return;
          }
        }

        if (UNSUCCESSFUL_RUN_STATUSES.has(runResponse.status)) {
          setData(null);
          setIsFinalizing(false);
          setArtifactUnavailable(null);
          setErrorMessage(runResponse.error_message ?? `Run ${runResponse.status.toLowerCase()}.`);
          setLoading(false);
          return;
        }

        if (ACTIVE_RUN_STATUSES.has(runResponse.status)) {
          setData(null);
          setIsFinalizing(false);
          setArtifactUnavailable(null);
          setErrorMessage(null);
          setLoading(false);

          activePollStartedAt = Date.now();
          scheduleActiveProgressPoll();

          return;
        }

        setData(null);
        setIsFinalizing(false);
        setArtifactUnavailable(null);
        setErrorMessage(`Unsupported run status: ${runResponse.status}`);
        setLoading(false);
      } catch (error) {
        if (ignore) return;
        setData(null);
        setIsFinalizing(false);
        setArtifactUnavailable(null);
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load result');
        setLoading(false);
      }
    }

    setLoading(true);
    setErrorMessage(null);
    setRun(null);
    setData(null);
    setArtifactUnavailable(null);
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
  const isRotation = data ? isRotationResult(data.run) : false;
  const canSaveDraftStrategy = Boolean(
    data?.run.status === 'SUCCEEDED' && !data.run.strategy_id && getDraftConfig(data.run)
  );

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

  if (run && UNSUCCESSFUL_RUN_STATUSES.has(run.status)) {
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

  if (run && artifactUnavailable) {
    return (
      <div className="space-y-6">
        {notice ? <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} /> : null}
        <RunHeader run={run} />
        <StateCard
          title="Result artifacts are unavailable"
          description={artifactUnavailable}
          tone="error"
        />
        <RunInsightBreakdown run={run} />
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
          <RunHeader
            run={run}
            canSaveDraftStrategy={canSaveDraftStrategy}
            isSavingDraftStrategy={isSavingDraftStrategy}
            onSaveDraftStrategy={() => {
              setSaveStrategyError(null);
              setIsSaveStrategyModalOpen(true);
            }}
          />
        ) : null}

        {isParameterSweep ? (
          <ParameterSweepResults run={data.run} />
        ) : (
          <>
            <RunInsightHero run={data.run} chartData={data.chart_data} />

            <RunInsightBreakdown run={data.run} />

            <RunCharts chartData={data.chart_data} run={data.run} />

            {data.rotation_review?.is_rotation ? (
              <RotationRebalanceInspector review={data.rotation_review} />
            ) : isRotation ? (
              <SectionCard
                title="Rotation Rebalance Inspector"
                subtitle="Selection and allocation details from available rotation artifacts."
              >
                <div className="app-text-muted text-sm">
                  Rotation rebalance artifacts are not available for this result.
                </div>
              </SectionCard>
            ) : (
              <TradeEventInspector runId={data.run.id} />
            )}
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
