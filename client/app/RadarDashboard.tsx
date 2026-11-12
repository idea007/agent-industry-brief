"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import CustomSourcesDialog, {
  sourceTypeLabel,
  type CustomSource,
} from "./components/CustomSourcesDialog";
import IntelCard from "./components/IntelCard";
import IntelDetailDialog from "./components/IntelDetailDialog";
import OnboardingDialog, {
  type CustomFocusInput,
} from "./components/OnboardingDialog";
import RunInlineCard from "./components/RunInlineCard";
import RunTraceDrawer from "./components/RunTraceDrawer";
import ScanCoveragePanel from "./components/ScanCoveragePanel";
import { groupArticlesByRun, preferenceTargets } from "./feed-view.mjs";
import { initialData } from "./radar-initial";
import {
  expandNewsArticles,
  formatRelativeTime,
  researchFocusLabel,
  sourceProfileSearchCount,
  sortNewsArticlesNewestFirst,
  type CustomSourcePreview,
  type DashboardData,
  type StoryContextTimeline as StoryContextTimelineData,
  type IntelEvent,
  type IntelFeedback,
  type IntelFeedbackType,
  type NewsArticle,
  type ResearchFocus,
  type Run,
  type RunEvent,
  type SourceDocument,
  type SourceHealth,
  type SourceProfile,
  type SourceQueryMetric,
  type StoryDetail,
  type StoryWatch,
  type StoryWatchCadence,
} from "./radar-types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
const FOLLOWING_KEY = "signal-radar-following-v2";
const CUSTOM_SOURCES_KEY = "signal-radar-custom-sources-v1";

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

type BackendCustomSource = {
  id: string;
  subscription_id: string;
  name: string;
  url: string;
  source_type: CustomSource["type"];
  collection_mode: "feed" | "webpage";
  status: "active" | "error" | "disabled";
  created_at: string;
};

function customSourceFromApi(source: BackendCustomSource): CustomSource {
  return {
    id: source.id,
    subscriptionId: source.subscription_id,
    name: source.name,
    url: source.url,
    type: source.source_type,
    collectionMode: source.collection_mode,
    status: source.status,
    addedAt: source.created_at,
  };
}

const streamEventTypes = [
  "run.created",
  "run.queued",
  "run.started",
  "run.stage_changed",
  "model.started",
  "model.responded",
  "model.completed",
  "collection.discovery_completed",
  "collection.ranking_completed",
  "quality.relevance_scored",
  "clustering.completed",
  "extraction.completed",
  "source.health_changed",
  "model.failed",
  "model.degraded",
  "tool.requested",
  "tool.allowed",
  "tool.denied",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "approval.required",
  "approval.resolved",
  "eval.completed",
  "delivery.completed",
  "delivery.skipped",
  "run.no_results",
  "run.completed",
  "run.failed",
  "run.cancel_requested",
  "run.cancelled",
];

function isActiveRun(run: Run): boolean {
  return ["queued", "running"].includes(run.status);
}

export default function RadarDashboard() {
  const [data, setData] = useState<DashboardData>(initialData);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [industryLoading, setIndustryLoading] = useState(false);
  const [selectedArticleId, setSelectedArticleId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runEventsById, setRunEventsById] = useState<
    Record<string, RunEvent[]>
  >({});
  const [startingSubscriptionId, setStartingSubscriptionId] = useState<
    string | null
  >(null);
  const [publicPreview, setPublicPreview] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [firstVisit, setFirstVisit] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [followedSlugs, setFollowedSlugs] = useState(["ai-agent", "robot"]);
  const [scanTargetId, setScanTargetId] = useState<string | null>(null);
  const [customSources, setCustomSources] = useState<CustomSource[]>([]);
  const [sourceProfiles, setSourceProfiles] = useState<SourceProfile[]>([]);
  const [sourceHealth, setSourceHealth] = useState<SourceHealth[]>([]);
  const [sourceQueryMetrics, setSourceQueryMetrics] = useState<
    SourceQueryMetric[]
  >([]);
  const [runDocuments, setRunDocuments] = useState<SourceDocument[]>([]);
  const [runDocumentsRunId, setRunDocumentsRunId] = useState("");
  const [storyContextTimeline, setStoryContextTimeline] =
    useState<StoryContextTimelineData | null>(null);
  const [storyTimeline, setStoryTimeline] = useState<IntelEvent[]>([]);
  const [storyDetail, setStoryDetail] = useState<StoryDetail | null>(null);
  const [detailOnlyArticles, setDetailOnlyArticles] = useState<NewsArticle[]>(
    [],
  );
  const [intelFeedback, setIntelFeedback] = useState<IntelFeedback[]>([]);
  const [detailContextStatus, setDetailContextStatus] = useState<
    "loading" | "loaded" | "error"
  >("loading");
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [watchSaving, setWatchSaving] = useState(false);
  const [watchCheckingStoryId, setWatchCheckingStoryId] = useState<string | null>(null);
  const [deepDiveStarting, setDeepDiveStarting] = useState<{
    storyId: string;
    focus: ResearchFocus;
  } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const eventSourcesRef = useRef(new Map<string, EventSource>());
  const runTargetIdRef = useRef<string | undefined>(undefined);
  const industryRequestRef = useRef(0);
  const runDocumentsRequestRef = useRef(0);
  const detailRequestRef = useRef(0);

  const loadDashboard = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/dashboard"), {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("backend unavailable");
      const payload = (await response.json()) as DashboardData;
      setData(payload);
      setConnected(true);
      setSelectedRunId((current) => {
        const stillExists = payload.runs.some((run) => run.id === current);
        return stillExists ? current : (payload.runs[0]?.id ?? "");
      });
      setSelectedArticleId((current) => {
        const articles = expandNewsArticles(payload.intel_events);
        const stillExists = articles.some((article) => article.id === current);
        return stillExists ? current : (articles[0]?.id ?? "");
      });
      return payload;
    } catch {
      setConnected(false);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const loadIndustryIntel = useCallback(
    async (subscriptionId: string) => {
      const requestId = ++industryRequestRef.current;
      setIndustryLoading(true);
      try {
        const response = await fetch(
          apiUrl(
            `/api/intel-events?subscription_id=${encodeURIComponent(
              subscriptionId,
            )}&limit=100`,
          ),
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error("industry intel unavailable");
        const payload =
          (await response.json()) as DashboardData["intel_events"];
        if (requestId !== industryRequestRef.current) return false;
        setData((current) => ({ ...current, intel_events: payload }));
        const articles = expandNewsArticles(payload);
        setSelectedArticleId((current) =>
          articles.some((article) => article.id === current)
            ? current
            : (articles[0]?.id ?? ""),
        );
        return true;
      } catch {
        if (requestId === industryRequestRef.current) {
          setNotice("当前关注的公开动态加载失败，请稍后重试。");
        }
        return false;
      } finally {
        if (requestId === industryRequestRef.current) {
          setIndustryLoading(false);
        }
      }
    },
    [],
  );

  const loadRunHistory = useCallback(async (runId: string) => {
    if (!runId) return;
    try {
      const response = await fetch(
        apiUrl(`/api/runs/${runId}/events/history`),
        { cache: "no-store" },
      );
      if (!response.ok) return;
      const events = (await response.json()) as RunEvent[];
      setRunEventsById((current) => ({ ...current, [runId]: events }));
    } catch {
      // Preserve the last known trace while a local backend reconnects.
    }
  }, []);

  const loadCustomSources = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/custom-sources"), {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("custom source backend unavailable");
      const payload = (await response.json()) as BackendCustomSource[];
      const sources = payload.map(customSourceFromApi);
      setCustomSources(sources);
      window.localStorage.setItem(CUSTOM_SOURCES_KEY, JSON.stringify(sources));
      return true;
    } catch {
      return false;
    }
  }, []);

  const loadSourceProfiles = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/source-profiles"), {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("source profile backend unavailable");
      setSourceProfiles((await response.json()) as SourceProfile[]);
      return true;
    } catch {
      return false;
    }
  }, []);

  const loadSourceDiagnostics = useCallback(
    async (subscriptionId: string) => {
      try {
        const [healthResponse, metricsResponse] = await Promise.all([
          fetch(
            apiUrl(
              `/api/source-health?subscription_id=${encodeURIComponent(subscriptionId)}`,
            ),
            { cache: "no-store" },
          ),
          fetch(
            apiUrl(
              `/api/source-query-metrics?subscription_id=${encodeURIComponent(subscriptionId)}`,
            ),
            { cache: "no-store" },
          ),
        ]);
        if (!healthResponse.ok || !metricsResponse.ok) {
          throw new Error("source diagnostics unavailable");
        }
        setSourceHealth((await healthResponse.json()) as SourceHealth[]);
        setSourceQueryMetrics(
          (await metricsResponse.json()) as SourceQueryMetric[],
        );
        return true;
      } catch {
        setSourceHealth([]);
        setSourceQueryMetrics([]);
        return false;
      }
    },
    [],
  );

  const loadRunDocuments = useCallback(async (runId: string) => {
    const requestId = ++runDocumentsRequestRef.current;
    if (!runId) {
      setRunDocuments([]);
      setRunDocumentsRunId("");
      return;
    }
    try {
      const response = await fetch(
        apiUrl(`/api/runs/${encodeURIComponent(runId)}/source-documents`),
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("run documents unavailable");
      const payload = (await response.json()) as SourceDocument[];
      if (requestId === runDocumentsRequestRef.current) {
        setRunDocuments(payload);
        setRunDocumentsRunId(runId);
      }
    } catch {
      if (requestId === runDocumentsRequestRef.current) {
        setRunDocuments([]);
        setRunDocumentsRunId(runId);
      }
    }
  }, []);

  const loadDetailContext = useCallback(
    async (storyId: string, intelEventId: string) => {
      const requestId = ++detailRequestRef.current;
      setDetailContextStatus("loading");
      try {
        const [
          timelineResponse,
          feedbackResponse,
          storyResponse,
          storyContextTimelineResponse,
        ] = await Promise.all([
            fetch(
              apiUrl(
                `/api/stories/${encodeURIComponent(storyId)}/timeline`,
              ),
              { cache: "no-store" },
            ),
            fetch(
              apiUrl(
                `/api/intel-events/${encodeURIComponent(intelEventId)}/feedback`,
              ),
              { cache: "no-store" },
            ),
            fetch(apiUrl(`/api/stories/${encodeURIComponent(storyId)}`), {
              cache: "no-store",
            }),
            fetch(
              apiUrl(
                `/api/stories/${encodeURIComponent(storyId)}/context-timeline?days=30`,
              ),
              { cache: "no-store" },
            ),
          ]);
        if (!timelineResponse.ok || !feedbackResponse.ok || !storyResponse.ok) {
          throw new Error("detail context unavailable");
        }
        const [timeline, feedback, detail, storyContextTimelinePayload] = await Promise.all([
          timelineResponse.json() as Promise<IntelEvent[]>,
          feedbackResponse.json() as Promise<IntelFeedback[]>,
          storyResponse.json() as Promise<StoryDetail>,
          storyContextTimelineResponse.ok
            ? (storyContextTimelineResponse.json() as Promise<StoryContextTimelineData>)
            : Promise.resolve(null),
        ]);
        if (requestId !== detailRequestRef.current) return;
        setStoryTimeline(timeline);
        setIntelFeedback(feedback);
        setStoryDetail(detail);
        setStoryContextTimeline(storyContextTimelinePayload);
        setDetailContextStatus("loaded");
      } catch {
        if (requestId !== detailRequestRef.current) return;
        setStoryTimeline([]);
        setIntelFeedback([]);
        setStoryDetail(null);
        setStoryContextTimeline(null);
        setDetailContextStatus("error");
      }
    },
    [],
  );

  const attachStream = useCallback(
    (runId: string, subscriptionId: string) => {
      if (!runId || eventSourcesRef.current.has(runId)) return;
      const source = new EventSource(apiUrl(`/api/runs/${runId}/events`));
      eventSourcesRef.current.set(runId, source);

      const receive = (message: MessageEvent) => {
        const event = JSON.parse(message.data) as RunEvent;
        setRunEventsById((current) => {
          const events = current[runId] ?? [];
          if (events.some((item) => item.seq === event.seq)) return current;
          return {
            ...current,
            [runId]: [...events, event].sort((a, b) => a.seq - b.seq),
          };
        });
        const statusByEvent: Partial<Record<string, Run["status"]>> = {
          "run.queued": "queued",
          "run.started": "running",
          "approval.required": "waiting_approval",
          "run.completed": "completed",
          "run.failed": "failed",
          "run.cancelled": "cancelled",
        };
        const nextStatus = statusByEvent[event.type];
        const nextStage =
          event.type === "run.stage_changed" &&
          typeof event.payload.stage === "string"
            ? event.payload.stage
            : undefined;
        if (nextStatus || nextStage) {
          setData((current) => ({
            ...current,
            runs: current.runs.map((run) =>
              run.id === runId
                ? {
                    ...run,
                    ...(nextStatus ? { status: nextStatus } : {}),
                    ...(nextStage ? { stage: nextStage } : {}),
                  }
                : run,
            ),
          }));
        }
        if (
          ["run.completed", "run.failed", "run.cancelled"].includes(event.type)
        ) {
          source.close();
          eventSourcesRef.current.delete(runId);
          void loadDashboard().then(() => {
            if (runTargetIdRef.current === subscriptionId) {
              setIndustryLoading(true);
              void loadIndustryIntel(subscriptionId);
            }
          });
        }
        if (event.type === "approval.required") {
          source.close();
          eventSourcesRef.current.delete(runId);
          void loadDashboard().then(() => {
            if (runTargetIdRef.current === subscriptionId) {
              setIndustryLoading(true);
              void loadIndustryIntel(subscriptionId);
            }
          });
        }
      };

      streamEventTypes.forEach((type) =>
        source.addEventListener(type, receive as EventListener),
      );
      source.onerror = () => {
        source.close();
        eventSourcesRef.current.delete(runId);
        void loadDashboard().then(() => {
          if (runTargetIdRef.current === subscriptionId) {
            setIndustryLoading(true);
            void loadIndustryIntel(subscriptionId);
          }
        });
      };
    },
    [loadDashboard, loadIndustryIntel],
  );

  useEffect(() => {
    const eventSources = eventSourcesRef.current;
    // Synchronize the client with the intelligence service after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDashboard().then((payload) => {
      if (payload) void Promise.all([loadCustomSources(), loadSourceProfiles()]);
    });

    const storedFollowing = window.localStorage.getItem(FOLLOWING_KEY);
    if (storedFollowing) {
      try {
        const parsed = JSON.parse(storedFollowing);
        if (
          Array.isArray(parsed) &&
          parsed.every((item) => typeof item === "string")
        ) {
          setFollowedSlugs(parsed);
        }
      } catch {
        window.localStorage.removeItem(FOLLOWING_KEY);
      }
    } else {
      setFirstVisit(true);
      setOnboardingOpen(true);
    }

    const storedSources = window.localStorage.getItem(CUSTOM_SOURCES_KEY);
    if (storedSources) {
      try {
        const parsed = JSON.parse(storedSources);
        if (Array.isArray(parsed)) setCustomSources(parsed as CustomSource[]);
      } catch {
        window.localStorage.removeItem(CUSTOM_SOURCES_KEY);
      }
    }

    return () => {
      eventSources.forEach((source) => source.close());
      eventSources.clear();
    };
  }, [loadCustomSources, loadDashboard, loadSourceProfiles]);

  useEffect(() => {
    // Run history is persisted outside React and follows the selected Run.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadRunHistory(selectedRunId);
  }, [loadRunHistory, selectedRunId]);

  useEffect(() => {
    data.runs.filter(isActiveRun).forEach((run) => {
      attachStream(run.id, run.subscription_id);
    });
  }, [attachStream, data.runs]);

  const subscriptions = useMemo(
    () => data.subscriptions.filter((item) => item.enabled),
    [data.subscriptions],
  );

  const followedSubscriptions = useMemo(() => {
    const followed = subscriptions.filter((item) =>
      followedSlugs.includes(item.slug),
    );
    return followed.length ? followed : subscriptions;
  }, [followedSlugs, subscriptions]);

  const runTarget =
    followedSubscriptions.find((item) => item.id === scanTargetId) ??
    followedSubscriptions[0];
  const runTargetId = runTarget?.id;
  useEffect(() => {
    runTargetIdRef.current = runTargetId;
  }, [runTargetId]);
  const latestIndustryRun = useMemo(
    () =>
      data.runs.find(
        (run) =>
          run.subscription_id === runTargetId &&
          run.research_mode === "monitor",
      ),
    [data.runs, runTargetId],
  );
  const latestCompletedIndustryRun = useMemo(
    () =>
      data.runs.find(
        (run) =>
          run.subscription_id === runTargetId &&
          run.research_mode === "monitor" &&
          run.status === "completed",
      ),
    [data.runs, runTargetId],
  );
  const activeRuns = useMemo(
    () => data.runs.filter(isActiveRun),
    [data.runs],
  );
  const activeRunBySubscription = useMemo(() => {
    const activeBySubscription = new Map<string, Run>();
    activeRuns.forEach((run) => {
      if (!activeBySubscription.has(run.subscription_id)) {
        activeBySubscription.set(run.subscription_id, run);
      }
    });
    return activeBySubscription;
  }, [activeRuns]);
  const targetActiveRun = runTargetId
    ? activeRunBySubscription.get(runTargetId)
    : undefined;
  const targetStarting = startingSubscriptionId === runTargetId;
  const targetBusy = Boolean(targetActiveRun) || targetStarting;
  const runningRunCount = activeRuns.filter(
    (run) => run.status === "running",
  ).length;
  const queuedRunCount = activeRuns.filter(
    (run) => run.status === "queued",
  ).length;
  const maxConcurrentRuns =
    data.system?.runtime?.max_concurrent_runs ?? 2;
  const nextRunWillQueue = runningRunCount >= maxConcurrentRuns;
  useEffect(() => {
    if (!connected || !runTargetId) return;
    // Industry intelligence is authoritative server state loaded per selection.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadIndustryIntel(runTargetId);
  }, [connected, loadIndustryIntel, runTargetId]);

  useEffect(() => {
    if (!connected || !latestIndustryRun?.id) return;
    // Scan funnel data is persisted outside React and follows the latest industry Run.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadRunDocuments(latestIndustryRun.id);
  }, [connected, latestIndustryRun?.id, loadRunDocuments]);

  useEffect(() => {
    if (!connected || !runTargetId) return;
    // Source diagnostics explain the scan funnel and also feed the source panel.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSourceDiagnostics(runTargetId);
  }, [connected, loadSourceDiagnostics, runTargetId]);

  const subscriptionById = useMemo(
    () =>
      new Map(
        data.subscriptions.map((subscription) => [
          subscription.id,
          subscription,
        ]),
      ),
    [data.subscriptions],
  );

  const allArticles = useMemo(
    () => expandNewsArticles(data.intel_events),
    [data.intel_events],
  );
  const detailArticlePool = useMemo(() => {
    const articlesById = new Map(
      allArticles.map((article) => [article.id, article]),
    );
    for (const article of detailOnlyArticles) {
      if (!articlesById.has(article.id)) {
        articlesById.set(article.id, article);
      }
    }
    return [...articlesById.values()];
  }, [allArticles, detailOnlyArticles]);

  const baseArticles = useMemo(() => {
    if (!runTarget) return [];
    return sortNewsArticlesNewestFirst(
      allArticles.filter(
        (article) => article.event.subscription_id === runTarget.id,
      ),
    );
  }, [allArticles, runTarget]);
  const feedChangeTypeByArticleId = useMemo(() => {
    const snapshot = groupArticlesByRun(
      baseArticles,
      latestCompletedIndustryRun,
    );
    return new Map(
      snapshot.changes.map(({ article, kind }) => [article.id, kind]),
    );
  }, [baseArticles, latestCompletedIndustryRun]);

  const selectedArticle =
    detailArticlePool.find((article) => article.id === selectedArticleId) ??
    baseArticles[0];
  const selectedStoryDeepDiveRun = selectedArticle
    ? activeRuns.find(
        (run) =>
          run.research_mode === "deep_dive" &&
          run.story_id === selectedArticle.event.story_id,
      )
    : undefined;
  const relatedArticles = selectedArticle
    ? detailArticlePool
        .filter(
          (article) =>
            article.id !== selectedArticle.id &&
            (article.event.subscription_id ===
              selectedArticle.event.subscription_id ||
              article.event.tags.some((tag) =>
                selectedArticle.event.tags.includes(tag),
              )),
        )
        .slice(0, 5)
    : [];
  const enabledStoryWatchIds = useMemo(
    () => new Set((data.story_watches ?? []).filter((watch) => watch.enabled).map((watch) => watch.story_id)),
    [data.story_watches],
  );
  useEffect(() => {
    if (!detailOpen || !selectedArticle) return;
    // Timeline and feedback are authoritative server state for the open story.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDetailContext(
      selectedArticle.event.story_id,
      selectedArticle.event.id,
    );
  }, [
    detailOpen,
    loadDetailContext,
    selectedArticle,
  ]);
  const selectedRun =
    data.runs.find((item) => item.id === selectedRunId) ?? data.runs[0];
  const selectedRunEvents = selectedRun
    ? (runEventsById[selectedRun.id] ?? [])
    : [];
  const selectedApproval = data.approvals.find(
    (approval) =>
      approval.run_id === selectedRun?.id && approval.status === "pending",
  );
  const latestIndustryApproval = data.approvals.find(
    (approval) =>
      approval.run_id === latestIndustryRun?.id && approval.status === "pending",
  );
  const latestIndustryRunEvents = latestIndustryRun
    ? (runEventsById[latestIndustryRun.id] ?? [])
    : [];
  const activeSourceProfile = sourceProfiles.find(
    (profile) => profile.slug === runTarget?.slug,
  );
  const targetCustomSources = customSources.filter(
    (source) =>
      !source.subscriptionId || source.subscriptionId === runTarget?.id,
  );
  const scanFunnel = useMemo(() => {
    if (
      !connected ||
      !latestIndustryRun ||
      runDocumentsRunId !== latestIndustryRun.id ||
      !runDocuments.length
    ) {
      return null;
    }
    const selected = runDocuments.filter(
      (document) => document.last_outcome === "selected",
    ).length;
    const blocked = runDocuments.filter(
      (document) => document.last_outcome === "blocked",
    ).length;
    const reviewed = runDocuments.filter(
      (document) => document.last_outcome === "reviewed",
    ).length;
    const deferred = runDocuments.filter(
      (document) => document.last_outcome === "deferred",
    ).length;
    return {
      candidates: runDocuments.length,
      evidence: selected + reviewed,
      selected,
      notSelected: deferred + reviewed + blocked,
      generated: latestIndustryRun.result?.item_count ?? 0,
      status: latestIndustryRun.status,
    };
  }, [connected, latestIndustryRun, runDocuments, runDocumentsRunId]);
  const showRunCard =
    !!latestIndustryApproval ||
    (!!latestIndustryRun &&
      (["queued", "running", "failed"].includes(latestIndustryRun.status) ||
        (latestIndustryRun.status === "completed" &&
          !!latestIndustryRun.result?.empty_result)));
  const lastRun = data.runs[0];
  const demoMode = connected && data.system?.sources.mode === "fixture";
  const scanStatusText = targetStarting
    ? `正在启动 ${runTarget?.name ?? "扫描"}…`
    : targetActiveRun?.status === "queued"
      ? `${runTarget?.name ?? "当前关注"}排队中 · ${runningRunCount} 个扫描执行中`
      : targetActiveRun?.status === "running"
        ? `正在扫描 ${runTarget?.name ?? "最新情报"} · 共 ${activeRuns.length} 个任务`
        : activeRuns.length
          ? `${runningRunCount} 个扫描执行中${queuedRunCount ? ` · ${queuedRunCount} 个排队` : ""}`
          : loading
            ? "正在连接情报服务…"
            : lastRun
              ? `上次更新 ${formatRelativeTime(lastRun.updated_at)}`
              : "尚未运行";
  const scanButtonLabel = targetStarting
    ? "启动中"
    : targetActiveRun?.status === "queued"
      ? "排队中"
      : targetActiveRun?.status === "running"
        ? "扫描中"
        : nextRunWillQueue
          ? "加入队列"
          : "立即扫描";

  function renderIntelCard(
    article: (typeof baseArticles)[number],
    changeType?: "new" | "progress",
  ) {
    return (
      <IntelCard
        key={article.id}
        item={article.event}
        source={article.source}
        storyEvents={article.story_events}
        watched={enabledStoryWatchIds.has(article.event.story_id)}
        subscription={subscriptionById.get(article.event.subscription_id)}
        changeType={changeType}
        onOpen={() => openIntel(article.id)}
      />
    );
  }

  function resetDetailContext() {
    setStoryTimeline([]);
    setStoryDetail(null);
    setStoryContextTimeline(null);
    setIntelFeedback([]);
    setDetailContextStatus("loading");
  }

  function openIntel(articleId: string) {
    resetDetailContext();
    setSelectedArticleId(articleId);
    setDetailOpen(true);
  }

  async function openStoryInDetail(storyId: string) {
    resetDetailContext();
    const existing = detailArticlePool.find(
      (article) => article.id === storyId,
    );
    if (existing) {
      setSelectedArticleId(storyId);
      return;
    }
    try {
      const response = await fetch(
        apiUrl(`/api/stories/${encodeURIComponent(storyId)}/timeline`),
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("story timeline unavailable");
      const events = (await response.json()) as IntelEvent[];
      const article = expandNewsArticles(events).find(
        (candidate) => candidate.id === storyId,
      );
      if (!article) throw new Error("story timeline is empty");
      setDetailOnlyArticles((current) => [
        article,
        ...current.filter((candidate) => candidate.id !== storyId),
      ]);
      setSelectedArticleId(storyId);
    } catch {
      setNotice("这条历史前情暂时无法打开，请稍后重试。");
      if (selectedArticle) {
        void loadDetailContext(
          selectedArticle.event.story_id,
          selectedArticle.event.id,
        );
      }
    }
  }

  async function startStoryDeepDive(
    researchFocus: ResearchFocus = "comprehensive",
  ) {
    if (!selectedArticle || !connected) {
      setNotice("情报服务未连接，暂时无法深挖当前故事。");
      return;
    }
    const storyId = selectedArticle.event.story_id;
    const subscriptionId = selectedArticle.event.subscription_id;
    if (activeRunBySubscription.has(subscriptionId)) {
      setNotice("该关注已有扫描正在运行或排队，请完成后再深挖故事。");
      return;
    }
    if (deepDiveStarting?.storyId === storyId) return;
    setDeepDiveStarting({ storyId, focus: researchFocus });
    setNotice(null);
    try {
      const response = await fetch(apiUrl("/api/runs"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subscription_id: subscriptionId,
          research_mode: "deep_dive",
          story_id: storyId,
          research_focus: researchFocus,
          delivery_mode: "web_inbox",
          idempotency_key: `deep-dive-${storyId}-${researchFocus}-${Date.now()}`,
        }),
      });
      if (!response.ok) throw new Error("deep dive unavailable");
      const run = (await response.json()) as Run;
      setSelectedRunId(run.id);
      setRunEventsById((current) => ({ ...current, [run.id]: [] }));
      setData((current) => ({ ...current, runs: [run, ...current.runs] }));
      attachStream(run.id, run.subscription_id);
      setNotice(
        `已开始「${researchFocusLabel(researchFocus)}」：${selectedArticle.event.title}`,
      );
    } catch {
      setNotice("深挖没有启动，请检查情报服务后重试。");
    } finally {
      setDeepDiveStarting((current) =>
        current?.storyId === storyId ? null : current,
      );
    }
  }

  async function saveStoryWatch(payload: {
    research_focus: ResearchFocus;
    question: string;
    cadence: StoryWatchCadence;
    enabled: boolean;
  }) {
    if (!selectedArticle || !connected || watchSaving) return;
    const storyId = selectedArticle.event.story_id;
    setWatchSaving(true);
    setNotice(null);
    try {
      const response = await fetch(
        apiUrl(`/api/stories/${encodeURIComponent(storyId)}/watch`),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) throw new Error("story watch unavailable");
      const watch = (await response.json()) as StoryWatch;
      setStoryDetail((current) =>
        current?.story.id === storyId ? { ...current, watch } : current,
      );
      setData((current) => ({
        ...current,
        story_watches: [
          watch,
          ...(current.story_watches ?? []).filter(
            (item) => item.story_id !== storyId,
          ),
        ],
      }));
      setNotice(
        watch.enabled
          ? "持续追踪已保存；你可以立即检查，自动频率仅在计划扫描开启时生效。"
          : "已停止追踪这个故事，历史检查记录仍然保留。",
      );
    } catch {
      setNotice("追踪设置没有保存，请稍后重试。");
    } finally {
      setWatchSaving(false);
    }
  }

  async function checkStoryWatch() {
    if (!selectedArticle || !connected || watchCheckingStoryId) return;
    const storyId = selectedArticle.event.story_id;
    setWatchCheckingStoryId(storyId);
    setNotice(null);
    try {
      const response = await fetch(
        apiUrl(`/api/stories/${encodeURIComponent(storyId)}/watch/check`),
        { method: "POST" },
      );
      if (!response.ok) throw new Error("story watch check unavailable");
      const run = (await response.json()) as Run;
      setSelectedRunId(run.id);
      setRunEventsById((current) => ({ ...current, [run.id]: [] }));
      setData((current) => ({ ...current, runs: [run, ...current.runs] }));
      attachStream(run.id, run.subscription_id);
      await loadDetailContext(
        storyId,
        selectedArticle.event.id,
      );
      setNotice(`已开始检查更新：${selectedArticle.event.title}`);
    } catch {
      setNotice("检查更新没有启动；如果当前故事正在深挖，请完成后再试。");
    } finally {
      setWatchCheckingStoryId((current) => current === storyId ? null : current);
    }
  }

  async function toggleIntelFeedback(
    feedbackType: IntelFeedbackType,
    target?: string,
  ) {
    if (!selectedArticle || feedbackSaving) return;
    const intelEventId = selectedArticle.event.id;
    const existing = intelFeedback.find(
      (feedback) =>
        feedback.feedback_type === feedbackType &&
        (feedback.target ?? undefined) === target,
    );
    const isPreferenceFeedback =
      !target &&
      (feedbackType === "valuable" || feedbackType === "not_relevant");
    const oppositeType =
      feedbackType === "valuable" ? "not_relevant" : "valuable";
    const opposite = isPreferenceFeedback
      ? intelFeedback.find(
          (feedback) =>
            feedback.feedback_type === oppositeType && !feedback.target,
        )
      : undefined;
    setFeedbackSaving(true);
    try {
      const endpoint = `/api/intel-events/${encodeURIComponent(
        intelEventId,
      )}/feedback`;
      if (existing) {
        const response = await fetch(
            apiUrl(
              `${endpoint}/${encodeURIComponent(feedbackType)}${
                target
                  ? `?target=${encodeURIComponent(target)}`
                  : ""
              }`,
            ),
            { method: "DELETE" },
          );
        if (!response.ok) throw new Error("feedback unavailable");
      } else {
        if (opposite) {
          const deleteResponse = await fetch(
            apiUrl(`${endpoint}/${encodeURIComponent(oppositeType)}`),
            { method: "DELETE" },
          );
          if (!deleteResponse.ok && deleteResponse.status !== 404) {
            throw new Error("opposite feedback unavailable");
          }
        }
        const response = await fetch(apiUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              feedback_type: feedbackType,
              target,
            }),
          });
        if (!response.ok) throw new Error("feedback unavailable");
      }
      await loadDetailContext(
        selectedArticle.event.story_id,
        intelEventId,
      );
      if (existing) {
        setNotice("反馈已撤销。");
      } else if (isPreferenceFeedback) {
        const targets = preferenceTargets(selectedArticle.event.tags);
        setNotice(
          `${feedbackType === "valuable" ? "会多关注" : "会减少"}类似动态${
            targets.length ? `：${targets.join("、")}` : ""
          }。`,
        );
      } else {
        setNotice("反馈已保存。");
      }
    } catch {
      setNotice("反馈保存失败，请稍后重试。");
    } finally {
      setFeedbackSaving(false);
    }
  }

  function selectIndustry(subscriptionId: string) {
    if (runTarget?.id === subscriptionId) return;
    window.scrollTo({ top: 0, behavior: "instant" });
    industryRequestRef.current += 1;
    runDocumentsRequestRef.current += 1;
    setRunDocuments([]);
    setRunDocumentsRunId("");
    setScanTargetId(subscriptionId);
    setStoryContextTimeline(null);
    setDetailOnlyArticles([]);
    setSelectedArticleId("");
    setDetailOpen(false);
    setIndustryLoading(true);
    setData((current) => ({ ...current, intel_events: [] }));
    const latestRun = data.runs.find(
      (run) => run.subscription_id === subscriptionId,
    );
    setSelectedRunId(latestRun?.id ?? "");
  }

  function saveFollowing(slugs: string[]) {
    setFollowedSlugs(slugs);
    window.localStorage.setItem(FOLLOWING_KEY, JSON.stringify(slugs));
    const firstSubscription = subscriptions.find((item) =>
      slugs.includes(item.slug),
    );
    setScanTargetId(firstSubscription?.id ?? null);
    setFirstVisit(false);
    setOnboardingOpen(false);
  }

  async function createCustomFocus(
    input: CustomFocusInput,
  ): Promise<DashboardData["subscriptions"][number] | null> {
    if (!connected) {
      setNotice("创建自定义主题需要先连接情报服务。");
      return null;
    }
    try {
      const response = await fetch(apiUrl("/api/subscriptions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: input.name,
          slug: `custom-${Date.now().toString(36)}`,
          topic: input.topic,
          include_keywords: input.keywords,
          exclude_keywords: [],
          languages: ["zh-CN", "en"],
          lookback_hours: 72,
          max_items: 12,
          minimum_importance: 6,
          schedule_label: "每天 09:00",
          accent: "#6366f1",
          focus_type: input.focusType,
        }),
      });
      if (!response.ok) throw new Error("custom industry create failed");
      const created =
        (await response.json()) as DashboardData["subscriptions"][number];
      setData((current) => ({
        ...current,
        subscriptions: [...current.subscriptions, created],
      }));
      setScanTargetId(created.id);
      window.setTimeout(() => void loadSourceProfiles(), 0);
      return created;
    } catch {
      setNotice("自定义主题创建失败，请稍后重试。");
      return null;
    }
  }

  function persistCustomSources(next: CustomSource[]) {
    setCustomSources(next);
    window.localStorage.setItem(CUSTOM_SOURCES_KEY, JSON.stringify(next));
  }

  async function previewCustomSource(
    source: CustomSource,
  ): Promise<CustomSourcePreview | null> {
    if (!connected || !runTarget) {
      setNotice("来源试用需要先连接情报服务。");
      return null;
    }
    try {
      const response = await fetch(apiUrl("/api/custom-sources/preview"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subscription_id: runTarget.id,
          name: source.name,
          url: source.url,
          source_type: source.type,
        }),
      });
      if (!response.ok) throw new Error("source preview failed");
      return (await response.json()) as CustomSourcePreview;
    } catch {
      setNotice(
        "来源试用失败；请确认链接可公开访问，并且没有跳转到内网或登录页。",
      );
      return null;
    }
  }

  async function addCustomSource(source: CustomSource): Promise<boolean> {
    if (!connected || !runTarget) {
      persistCustomSources([
        ...customSources,
        { ...source, subscriptionId: runTarget?.id },
      ]);
      setNotice(
        "来源已保存在当前设备；连接情报服务后重新添加即可参与扫描。",
      );
      return true;
    }
    try {
      const response = await fetch(apiUrl("/api/custom-sources"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subscription_id: runTarget.id,
          name: source.name,
          url: source.url,
          source_type: source.type,
        }),
      });
      if (!response.ok) throw new Error("source create failed");
      const created = customSourceFromApi(
        (await response.json()) as BackendCustomSource,
      );
      persistCustomSources([...customSources, created]);
      setNotice(
        `已将「${created.name}」加入 ${runTarget.name}，下次扫描会自动采集。`,
      );
      return true;
    } catch {
      setNotice("来源识别失败，请确认链接可公开访问并提供 RSS 或文章列表。");
      return false;
    }
  }

  async function removeCustomSource(sourceId: string): Promise<void> {
    const source = customSources.find((item) => item.id === sourceId);
    if (!source) return;
    if (connected && source.id.startsWith("source_")) {
      try {
        const response = await fetch(
          apiUrl(`/api/custom-sources/${source.id}`),
          { method: "DELETE" },
        );
        if (!response.ok && response.status !== 404) {
          throw new Error("source delete failed");
        }
      } catch {
        setNotice("来源暂时无法移除，请检查情报服务后重试。");
        return;
      }
    }
    persistCustomSources(
      customSources.filter((item) => item.id !== sourceId),
    );
  }

  async function adoptFocusRelation(
    name: string,
    tier: "related" | "context",
  ): Promise<void> {
    if (!connected || !runTarget) {
      setNotice("确认对象关系需要先连接情报服务。");
      return;
    }
    try {
      const preferencesResponse = await fetch(
        apiUrl(`/api/subscriptions/${runTarget.id}/preferences`),
        { cache: "no-store" },
      );
      if (!preferencesResponse.ok) {
        throw new Error("preferences unavailable");
      }
      const preferences = (await preferencesResponse.json()) as {
        followed_entities?: string[];
        context_entities?: string[];
      };
      const relationField =
        tier === "related" ? "followed_entities" : "context_entities";
      const relationValues = Array.from(
        new Set([...(preferences[relationField] ?? []), name]),
      );
      const response = await fetch(
        apiUrl(`/api/subscriptions/${runTarget.id}/preferences`),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [relationField]: relationValues }),
        },
      );
      if (!response.ok) throw new Error("relation adoption failed");
      await loadSourceProfiles();
      setNotice(
        `已确认「${name}」为${
          tier === "related" ? "一级关系" : "二级背景"
        }，下次扫描会纳入${
          tier === "related" ? "相关" : "周边"
        }检索。`,
      );
    } catch {
      setNotice("关系暂时无法确认，请检查情报服务后重试。");
    }
  }

  function openTraceForRun(runId: string) {
    setSelectedRunId(runId);
    setDetailOpen(false);
    setTraceOpen(true);
  }

  async function triggerRun() {
    const targetSubscription = runTarget?.id;
    if (!targetSubscription || targetActiveRun || targetStarting) return;
    setNotice(null);

    if (!connected) {
      setNotice("情报服务未连接，暂时无法扫描真实新闻。请确认服务已启动后重试。");
      return;
    }

    setStartingSubscriptionId(targetSubscription);
    try {
      const response = await fetch(apiUrl("/api/runs"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subscription_id: targetSubscription,
          delivery_mode: publicPreview ? "public_preview" : "web_inbox",
          idempotency_key: `web-${targetSubscription}-${Date.now()}`,
        }),
      });
      if (!response.ok) throw new Error("run create failed");
      const run = (await response.json()) as Run;
      setSelectedRunId(run.id);
      setRunEventsById((current) => ({ ...current, [run.id]: [] }));
      setData((current) => ({ ...current, runs: [run, ...current.runs] }));
      attachStream(run.id, run.subscription_id);
    } catch {
      setNotice("扫描启动失败，请检查情报服务后重试。");
    } finally {
      setStartingSubscriptionId((current) =>
        current === targetSubscription ? null : current,
      );
    }
  }

  async function cancelRun() {
    if (!selectedRun) return;
    try {
      await fetch(apiUrl(`/api/runs/${selectedRun.id}/cancel`), {
        method: "POST",
      });
      await loadDashboard();
      if (runTarget) await loadIndustryIntel(runTarget.id);
    } catch {
      setNotice("取消请求没有成功，请稍后重试。");
    }
  }

  async function retryRun(runToRetry?: Run) {
    const retryTarget = runToRetry ?? selectedRun;
    if (!retryTarget) return;
    if (activeRunBySubscription.has(retryTarget.subscription_id)) {
      setNotice("该关注已有扫描正在运行或排队，请等待完成后再重试。");
      return;
    }
    setStartingSubscriptionId(retryTarget.subscription_id);
    setNotice(null);
    try {
      const response = await fetch(
        apiUrl(`/api/runs/${retryTarget.id}/retry`),
        { method: "POST" },
      );
      if (!response.ok) throw new Error("retry failed");
      const run = (await response.json()) as Run;
      setSelectedRunId(run.id);
      setRunEventsById((current) => ({ ...current, [run.id]: [] }));
      setData((current) => ({ ...current, runs: [run, ...current.runs] }));
      attachStream(run.id, run.subscription_id);
    } catch {
      setNotice("重试没有启动，请检查情报服务状态。");
    } finally {
      setStartingSubscriptionId((current) =>
        current === retryTarget.subscription_id ? null : current,
      );
    }
  }

  async function decideApproval(
    decision: "approve" | "reject",
    approvalToDecide = selectedApproval,
  ) {
    if (!approvalToDecide) return;
    try {
      const response = await fetch(
        apiUrl(`/api/approvals/${approvalToDecide.id}/decisions`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            reason:
              decision === "approve"
                ? "按当前预览允许一次"
                : "只保留情报草稿",
          }),
        },
      );
      if (!response.ok) throw new Error("approval failed");
      await loadDashboard();
      if (runTarget) await loadIndustryIntel(runTarget.id);
      await loadRunHistory(approvalToDecide.run_id);
    } catch {
      setNotice("审批提交失败，请确认情报服务仍然在线。");
    }
  }

  async function reconnectDashboard() {
    setLoading(true);
    setNotice(null);
    const payload = await loadDashboard();
    if (payload) {
      await Promise.all([
        loadCustomSources(),
        loadSourceProfiles(),
        runTarget ? loadIndustryIntel(runTarget.id) : Promise.resolve(false),
      ]);
      return;
    }
    setNotice("仍未连接到情报服务，请确认电脑端服务正在运行。");
  }

  return (
    <div className="radar-app">
      <aside className="radar-sidebar" aria-label="简报导航">
        <a className="brand-lockup" href="#top" aria-label="新闻简报首页">
          <span className="radar-mark" aria-hidden="true">
            <i />
          </span>
          <span>
            <strong>新闻简报</strong>
            <small>INDUSTRY BRIEF</small>
          </span>
        </a>

        <div className="sidebar-scan">
          <button
            type="button"
            className="primary-button scan-button"
            data-testid="run-radar"
            title={
              targetBusy
                ? `${runTarget?.name ?? "当前关注"}已有扫描${targetActiveRun?.status === "queued" ? "排队中" : "运行中"}`
                : `${nextRunWillQueue ? "加入队列" : "立即扫描"}：${runTarget?.name ?? "未选择"}`
            }
            onClick={() => void triggerRun()}
            disabled={targetBusy || !runTarget}
          >
            {(targetStarting || targetActiveRun?.status === "running") && (
              <span className="scan-spinner" aria-hidden="true" />
            )}
            {scanButtonLabel}
          </button>
          <span className="scan-status" role="status">
            <i
              className={activeRuns.length || targetStarting ? "running" : connected ? "online" : ""}
              aria-hidden="true"
            />
            {scanStatusText}
          </span>
        </div>

        <nav className="industry-nav" aria-label="关注领域">
          <div className="industry-nav-heading">
            <h2>关注</h2>
            <button
              type="button"
              className="manage-following"
              onClick={() => setOnboardingOpen(true)}
              aria-label="管理关注"
            >
              更换关注
            </button>
          </div>
          <div className="industry-list">
            {followedSubscriptions.map((subscription) => {
              const activeRun = activeRunBySubscription.get(subscription.id);
              return (
                <button
                  type="button"
                  className={`industry-option${activeRun ? " has-active-run" : ""}`}
                  aria-pressed={runTarget?.id === subscription.id}
                  onClick={() => selectIndustry(subscription.id)}
                  key={subscription.id}
                  style={{ "--industry-accent": subscription.accent } as CSSProperties}
                  title={`查看 ${subscription.name} 动态并设为扫描目标${
                    activeRun
                      ? `，当前${activeRun.status === "queued" ? "排队中" : "扫描中"}`
                      : ""
                  }`}
                >
                  <i aria-hidden="true" />
                  <span className="industry-name">{subscription.name}</span>
                  {activeRun && (
                    <span className={`industry-run-state ${activeRun.status}`}>
                      {activeRun.status === "queued" ? "排队" : "扫描中"}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </nav>

        <div className="sidebar-actions">
          <button
            type="button"
            className="ghost-button source-strategy-button"
            onClick={() => setSourcesOpen(true)}
          >
            <span>来源策略</span>
            {(activeSourceProfile || targetCustomSources.length > 0) && (
              <small>
                {activeSourceProfile &&
                  `${activeSourceProfile.sources.length} 个定向源 · ${sourceProfileSearchCount(activeSourceProfile)} 组检索`}
                {targetCustomSources.length > 0 &&
                  `${activeSourceProfile ? " · " : ""}${targetCustomSources.length} 个自定义来源`}
              </small>
            )}
          </button>
          <button
            type="button"
            className="ghost-button agent-entry"
            onClick={() => setTraceOpen(true)}
          >
            运行信息
            {data.stats.pending_approval_count > 0 && (
              <i aria-label={`${data.stats.pending_approval_count} 个待审批`} />
            )}
          </button>
        </div>
      </aside>

      <main className="radar-content" id="top">
        <header className="result-summary">
          <h1>{runTarget?.name ?? "当前关注"}</h1>
          <span role="status" aria-busy={loading || industryLoading}>
            {loading || industryLoading
              ? "正在更新内容"
              : `${baseArticles.length} 条结果`}
          </span>
        </header>

        {scanFunnel && (
          <div className="scan-overview">
            <div
              className={`scan-funnel ${scanFunnel.status}`}
              role="status"
              data-run-status={scanFunnel.status}
            >
              <span>最近扫描</span>
              <strong>{scanFunnel.candidates} 条候选</strong>
              <i aria-hidden="true">→</i>
              <strong>{scanFunnel.evidence} 条证据来源</strong>
              {scanFunnel.status === "failed" ? (
                <>
                  <i aria-hidden="true">→</i>
                  <strong>
                    {scanFunnel.generated > 0 ? "投递未完成" : "整理未完成"}
                  </strong>
                  <small>
                    {scanFunnel.generated > 0
                      ? `${scanFunnel.generated} 条情报已保留`
                      : "本次未生成新情报"}
                  </small>
                </>
              ) : scanFunnel.status === "cancelled" ? (
                <>
                  <i aria-hidden="true">→</i>
                  <strong>扫描已取消</strong>
                  <small>本次未生成新情报</small>
                </>
              ) : ["queued", "running"].includes(scanFunnel.status) ? (
                <>
                  <i aria-hidden="true">→</i>
                  <strong>正在整理</strong>
                </>
              ) : (
                <>
                  <i aria-hidden="true">→</i>
                  <strong>{scanFunnel.selected} 条来源入选</strong>
                  <i aria-hidden="true">→</i>
                  <strong>{scanFunnel.generated} 条情报</strong>
                  <small>{scanFunnel.notSelected} 条来源未采用</small>
                </>
              )}
            </div>
            <ScanCoveragePanel
              documents={runDocuments}
              sourceHealth={sourceHealth}
              queryMetrics={sourceQueryMetrics}
            />
          </div>
        )}

        {notice && (
          <div className="notice-banner" role="alert">
            <span>{notice}</span>
            <button
              type="button"
              aria-label="关闭提示"
              onClick={() => setNotice(null)}
            >
              ×
            </button>
          </div>
        )}

        {demoMode && (
          <div className="notice-banner demo-mode-banner" role="status">
            <span>
              当前为演示模式，内容来自测试资料，不代表实时公开动态。
            </span>
          </div>
        )}

        {showRunCard && (
          <RunInlineCard
            run={latestIndustryRun}
            events={latestIndustryRunEvents}
            subscription={runTarget}
            approval={latestIndustryApproval}
            connected={connected}
            onOpenTrace={() => {
              if (latestIndustryRun) setSelectedRunId(latestIndustryRun.id);
              setTraceOpen(true);
            }}
            onDecision={(decision) =>
              void decideApproval(decision, latestIndustryApproval)
            }
            onRetry={() => void retryRun(latestIndustryRun)}
          />
        )}

        {baseArticles.length ? (
          <div className="intel-grid">
            {baseArticles.map((article) =>
              renderIntelCard(
                article,
                feedChangeTypeByArticleId.get(article.id),
              ),
            )}
          </div>
        ) : (
          <div className="empty-state">
            <span className="empty-icon" aria-hidden="true">
              ✦
            </span>
            <h2>
              {loading
                ? "正在连接情报服务"
                : industryLoading
                  ? `正在加载${runTarget?.name ?? "当前关注"}动态`
                : !connected
                  ? "情报服务未连接"
                  : `还没有${runTarget?.name ?? "当前关注"}动态`}
            </h2>
            <p>
              {loading
                ? "连接成功后将加载真实动态和扫描记录。"
                : industryLoading
                  ? `正在从数据库读取「${
                      runTarget?.name ?? "当前关注"
                    }」的历史动态。`
                : !connected
                  ? "连接恢复前不会展示或生成模拟内容。"
                  : `点击「立即扫描」，从「${
                      runTarget?.name ?? "当前关注"
                    }」来源获取最新信息。`}
            </p>
            {!loading && !industryLoading && (
              <button
                type="button"
                className="primary-button empty-state-action"
                onClick={() =>
                  void (connected ? triggerRun() : reconnectDashboard())
                }
                disabled={targetBusy || (connected && !runTarget)}
              >
                {connected ? scanButtonLabel : "重新连接"}
              </button>
            )}
          </div>
        )}

        {targetCustomSources.length ? (
          <section className="custom-sources-section">
            <header>
              <div>
                <span>自定义来源</span>
                <b>{targetCustomSources.length}</b>
              </div>
              <i aria-hidden="true" />
              <button type="button" onClick={() => setSourcesOpen(true)}>
                ＋ 管理来源
              </button>
            </header>
            <div className="custom-source-grid">
              {targetCustomSources.map((source) => (
                <article className="custom-source-card" key={source.id}>
                  <div>
                    <span className={`source-icon ${source.type}`}>
                      {sourceTypeLabel(source.type).slice(0, 1)}
                    </span>
                    <div>
                      <strong>{source.name}</strong>
                      <small>{sourceTypeLabel(source.type)}</small>
                    </div>
                  </div>
                  <p>{source.url}</p>
                  <footer>
                    <span>
                      {source.collectionMode === "feed"
                        ? "RSS / Atom 自动采集"
                        : source.collectionMode === "webpage"
                          ? "站内文章自动发现"
                          : "等待来源识别"}
                    </span>
                    <a href={source.url} target="_blank" rel="noreferrer">
                      打开来源 ↗
                    </a>
                  </footer>
                </article>
              ))}
            </div>
          </section>
        ) : (
          <button
            type="button"
            className="custom-source-cta"
            onClick={() => setSourcesOpen(true)}
          >
            <span aria-hidden="true">＋</span>
            补充当前关注的来源 — 追踪你在意的博主、频道、网站
          </button>
        )}
      </main>

      {detailOpen && selectedArticle && (
        <IntelDetailDialog
          key={`${selectedArticle.event.story_id}-${storyDetail?.watch?.updated_at ?? "loading"}`}
          article={selectedArticle}
          subscription={subscriptionById.get(
            selectedArticle.event.subscription_id,
          )}
          relatedArticles={relatedArticles}
          timeline={storyTimeline}
          storyContextTimeline={storyContextTimeline}
          storyDetail={storyDetail}
          detailContextStatus={detailContextStatus}
          feedback={intelFeedback}
          feedbackSaving={feedbackSaving}
          deepDiveStartingFocus={
            deepDiveStarting?.storyId === selectedArticle.event.story_id
              ? deepDiveStarting.focus
              : null
          }
          deepDiveActiveFocus={
            selectedStoryDeepDiveRun?.research_focus ??
            (selectedStoryDeepDiveRun ? "comprehensive" : null)
          }
          watch={storyDetail?.watch ?? null}
          watchSaving={watchSaving}
          watchChecking={watchCheckingStoryId === selectedArticle.event.story_id}
          schedulerEnabled={Boolean(data.system?.scheduler.enabled)}
          onClose={() => setDetailOpen(false)}
          onOpenRelated={(storyId) => void openStoryInDetail(storyId)}
          onOpenTrace={openTraceForRun}
          onDeepDive={(researchFocus) =>
            void startStoryDeepDive(researchFocus)
          }
          onSaveWatch={(payload) => void saveStoryWatch(payload)}
          onCheckWatch={() => void checkStoryWatch()}
          onToggleFeedback={(feedbackType, target) =>
            void toggleIntelFeedback(feedbackType, target)
          }
        />
      )}

      {traceOpen && (
        <RunTraceDrawer
          runs={data.runs}
          selectedRun={selectedRun}
          runEvents={selectedRunEvents}
          approval={selectedApproval}
          subscriptions={followedSubscriptions}
          connected={connected}
          targetBusy={targetBusy}
          nextRunWillQueue={nextRunWillQueue}
          activeRunCount={runningRunCount}
          queuedRunCount={queuedRunCount}
          maxConcurrentRuns={maxConcurrentRuns}
          publicPreview={publicPreview}
          onPublicPreviewChange={setPublicPreview}
          onSelectRun={setSelectedRunId}
          onRun={() => void triggerRun()}
          onCancel={() => void cancelRun()}
          onRetry={() => void retryRun()}
          onDecision={(decision) => void decideApproval(decision)}
          onClose={() => setTraceOpen(false)}
        />
      )}

      {onboardingOpen && (
        <OnboardingDialog
          subscriptions={subscriptions}
          initialSlugs={followedSlugs}
          required={firstVisit}
          onConfirm={saveFollowing}
          onCreateCustom={createCustomFocus}
          onClose={() => setOnboardingOpen(false)}
        />
      )}

      {sourcesOpen && (
        <CustomSourcesDialog
          sources={targetCustomSources}
          targetName={runTarget?.name}
          profile={activeSourceProfile}
          sourceHealth={sourceHealth}
          queryMetrics={sourceQueryMetrics}
          onPreview={previewCustomSource}
          onAdd={addCustomSource}
          onRemove={removeCustomSource}
          onAdoptRelation={adoptFocusRelation}
          onClose={() => setSourcesOpen(false)}
        />
      )}
    </div>
  );
}
