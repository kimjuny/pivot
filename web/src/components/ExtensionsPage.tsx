import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type MouseEvent,
} from 'react';
import { useLocation, useNavigate } from "react-router-dom";

import {
  CheckCircle2,
  Info,
  Loader2,
  MoreHorizontal,
  Search,
  Server,
  Trash2,
  Upload,
  X,
  XCircle,
} from "@/lib/lucide";
import { toast } from 'sonner';

import ConfirmationModal from './ConfirmationModal';
import { ExtensionLogoAvatar } from '@/components/ExtensionLogoAvatar';
import StaggeredFadeInList from '@/components/StaggeredFadeInList';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Card } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  getExtensionInstallationReferences,
  getExtensionPackages,
  createExtensionBundleImportJob,
  streamExtensionBundleImportJobEvents,
  importExtensionBundleWithJob,
  previewExtensionBundle,
  reconcileExtensionUpgrade,
  uninstallExtensionInstallation,
  updateExtensionInstallationStatus,
  type ExtensionContributionSummary,
  type ExtensionImportPreview,
  type ExtensionImportProgressEvent,
  type ExtensionInstallation,
  type ExtensionPackage,
  type ExtensionPendingUpgrade,
  type ExtensionReferenceSummary,
  type ExtensionUpgradeMode,
} from '@/utils/api';


const PAGE_SIZE = 10;

interface PendingUninstallState {
  installation: ExtensionInstallation;
  references: ExtensionReferenceSummary;
}

interface PendingImportState {
  files: File[];
  preview: ExtensionImportPreview;
}

type ContributorFilter =
  | 'all'
  | 'media'
  | 'surface'
  | 'web_search'
  | 'tool'
  | 'skill'
  | 'channel'
  | 'hook';

/**
 * Build a paginated page number list with ellipsis slots.
 */
function buildPageList(current: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }

  const pages: Array<number | 'ellipsis'> = [1];
  if (current > 3) {
    pages.push('ellipsis');
  }
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let index = start; index <= end; index += 1) {
    pages.push(index);
  }
  if (current < total - 2) {
    pages.push('ellipsis');
  }
  pages.push(total);
  return pages;
}

interface ContributionGroup {
  label: string;
  values: string[];
  tone: 'provider' | 'runtime' | 'lightweight';
}

interface ContributorCategory {
  key: Exclude<ContributorFilter, 'all'>;
  label: string;
  values: string[];
  tone: ContributionGroup['tone'];
}

const CONTRIBUTOR_FILTERS: Array<Pick<ContributorCategory, 'key' | 'label'>> = [
  { key: 'media', label: 'Media' },
  { key: 'surface', label: 'Surface' },
  { key: 'web_search', label: 'Web Search' },
  { key: 'tool', label: 'Tool' },
  { key: 'skill', label: 'Skill' },
  { key: 'channel', label: 'Channel' },
  { key: 'hook', label: 'Hook' },
];

/**
 * Build stable contribution groups for one installed extension version.
 *
 * Why: extensions can ship providers, runtime hooks, and optional helper
 * assets. Grouping them keeps import review readable without flattening every
 * contribution into one noisy badge list.
 */
function buildContributionGroups(
  summary: ExtensionContributionSummary,
): ContributionGroup[] {
  const groups: ContributionGroup[] = [
    {
      label: 'Channel Providers',
      values: summary.channel_providers,
      tone: 'provider',
    },
    {
      label: 'Media Providers',
      values: summary.media_providers ?? [],
      tone: 'provider',
    },
    {
      label: 'Web Search Providers',
      values: summary.web_search_providers,
      tone: 'provider',
    },
    {
      label: 'Chat Surfaces',
      values: summary.chat_surfaces ?? [],
      tone: 'runtime',
    },
    {
      label: 'Lifecycle Hooks',
      values: summary.hooks,
      tone: 'runtime',
    },
    {
      label: 'Tools (Optional)',
      values: summary.tools,
      tone: 'lightweight',
    },
    {
      label: 'Skills (Optional)',
      values: summary.skills,
      tone: 'lightweight',
    },
  ];
  return groups.filter((group) => group.values.length > 0);
}

function uniqueValues(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

/**
 * Collapse all installed versions into contribution-type tags for one package.
 */
function getPackageContributorCategories(pkg: ExtensionPackage): ContributorCategory[] {
  const summaries = pkg.versions.map((version) => version.contribution_summary);
  const categories: ContributorCategory[] = [
    {
      key: 'media',
      label: 'Media',
      values: uniqueValues(summaries.flatMap((summary) => summary.media_providers ?? [])),
      tone: 'provider',
    },
    {
      key: 'surface',
      label: 'Surface',
      values: uniqueValues(summaries.flatMap((summary) => summary.chat_surfaces ?? [])),
      tone: 'runtime',
    },
    {
      key: 'web_search',
      label: 'Web Search',
      values: uniqueValues(summaries.flatMap((summary) => summary.web_search_providers)),
      tone: 'provider',
    },
    {
      key: 'tool',
      label: 'Tool',
      values: uniqueValues(summaries.flatMap((summary) => summary.tools)),
      tone: 'lightweight',
    },
    {
      key: 'skill',
      label: 'Skill',
      values: uniqueValues(summaries.flatMap((summary) => summary.skills)),
      tone: 'lightweight',
    },
    {
      key: 'channel',
      label: 'Channel',
      values: uniqueValues(summaries.flatMap((summary) => summary.channel_providers)),
      tone: 'provider',
    },
    {
      key: 'hook',
      label: 'Hook',
      values: uniqueValues(summaries.flatMap((summary) => summary.hooks)),
      tone: 'runtime',
    },
  ];
  return categories.filter((category) => category.values.length > 0);
}

/**
 * Keep contribution badges visually consistent across import review states.
 */
function getContributionBadgeVariant(
  tone: ContributionGroup['tone'],
): 'default' | 'secondary' | 'outline' {
  if (tone === 'provider') {
    return 'default';
  }
  if (tone === 'runtime') {
    return 'secondary';
  }
  return 'outline';
}

/**
 * Convert one trust status into a short human-readable badge label.
 */
function formatTrustStatusLabel(trustStatus: string): string {
  switch (trustStatus) {
    case 'trusted_local':
      return 'Trusted Local';
    case 'verified':
      return 'Verified';
    case 'unverified':
      return 'Unverified';
    default:
      return trustStatus;
  }
}

function isUpgradePreview(preview: ExtensionImportPreview | null): boolean {
  return preview?.import_mode === 'upgrade';
}

/**
 * Format elapsed time since one ISO timestamp for draining progress display.
 */
function formatElapsed(isoTimestamp: string | null | undefined, nowMs: number): string {
  if (!isoTimestamp) return '';
  const startMs = Date.parse(isoTimestamp);
  if (Number.isNaN(startMs)) return '';
  const totalSeconds = Math.max(0, Math.floor((nowMs - startMs) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

type ImportDialogPhase = 'review' | 'installing' | 'draining';

function getImportActionLabel(preview: ExtensionImportPreview | null, isImporting: boolean): string {
  if (isImporting) {
    return 'Installing…';
  }
  if (!preview) {
    return 'Trust and Install';
  }
  if (preview.import_mode === 'upgrade') {
    return 'Trust and Upgrade';
  }
  if (preview.requires_overwrite_confirmation) {
    return 'Trust and Overwrite';
  }
  if (preview.identical_to_installed) {
    return 'Trust and Reuse Existing';
  }
  return 'Trust and Install';
}

function getImportSuccessMessage(
  preview: ExtensionImportPreview,
  upgradeMode: ExtensionUpgradeMode | null,
): string {
  if (preview.import_mode === 'upgrade') {
    if (upgradeMode === 'safe') {
      return 'Extension upgraded safely. Affected agents now require republish.';
    }
    return 'Extension force-upgraded. Affected agents now require republish.';
  }
  if (preview.requires_overwrite_confirmation) {
    return 'Extension version overwritten';
  }
  if (preview.identical_to_installed) {
    return 'Existing extension version reused';
  }
  return 'Extension imported';
}

/**
 * Pick the most recently installed version for one package.
 *
 * Why: the compact list card only shows one timestamp and one action menu, so
 * both should map to the newest installation the operator most recently added.
 */
function getMostRecentInstallation(
  pkg: ExtensionPackage,
): ExtensionInstallation | null {
  if (pkg.versions.length === 0) {
    return null;
  }

  return pkg.versions.reduce((latest, installation) => (
    installation.created_at > latest.created_at ? installation : latest
  ));
}

/**
 * Global Extensions inventory page.
 * Why: package installation and lifecycle operations belong at the workspace
 * level, while agent sidebars only handle per-agent bindings.
 */
function ExtensionsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [packages, setPackages] = useState<ExtensionPackage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [contributorFilter, setContributorFilter] = useState<ContributorFilter>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [isImporting, setIsImporting] = useState(false);
  const [isPreviewingImport, setIsPreviewingImport] = useState(false);
  const [importingUpgradeMode, setImportingUpgradeMode] = useState<ExtensionUpgradeMode | null>(null);
  const [importDialogPhase, setImportDialogPhase] = useState<ImportDialogPhase>('review');
  const [drainingUpgrade, setDrainingUpgrade] = useState<ExtensionPendingUpgrade | null>(null);
  const [drainingElapsedTick, setDrainingElapsedTick] = useState(() => Date.now());
  const [importProgress, setImportProgress] = useState<ExtensionImportProgressEvent | null>(null);
  const importStreamAbortRef = useRef<AbortController | null>(null);
  const [pendingImport, setPendingImport] = useState<PendingImportState | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<PendingUninstallState | null>(null);
  const [isUninstalling, setIsUninstalling] = useState(false);
  const [statusUpdatingIds, setStatusUpdatingIds] = useState<number[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const detailBasePath = location.pathname.startsWith("/studio/")
    ? "/studio/assets/extensions"
    : "/extensions";

  // Tick once per second for the draining elapsed timer
  useEffect(() => {
    if (importDialogPhase !== 'draining') return;
    const handle = window.setInterval(() => setDrainingElapsedTick(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, [importDialogPhase]);

  useEffect(() => {
    fileInputRef.current?.setAttribute('webkitdirectory', '');
    fileInputRef.current?.setAttribute('directory', '');
  }, []);

  const loadPackages = useCallback(async () => {
    setIsLoading(true);
    try {
      const nextPackages = await getExtensionPackages();
      setPackages(nextPackages);
    } catch (error) {
      console.error('Failed to load extensions:', error);
      toast.error('Failed to load extensions');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPackages();
  }, [loadPackages]);

  const contributorFilterItems = useMemo(() => {
    const items = CONTRIBUTOR_FILTERS.map((filter) => ({
      ...filter,
      count: packages.filter((pkg) => (
        getPackageContributorCategories(pkg).some((category) => category.key === filter.key)
      )).length,
    })).filter((filter) => filter.count > 0);

    return [
      { key: 'all' as const, label: 'All', count: packages.length },
      ...items,
    ];
  }, [packages]);

  const filteredPackages = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    return packages.filter((pkg) => {
      const contributorCategories = getPackageContributorCategories(pkg);
      const matchesContributor = (
        contributorFilter === 'all'
        || contributorCategories.some((category) => category.key === contributorFilter)
      );
      if (!matchesContributor) {
        return false;
      }
      if (!query) {
        return true;
      }

      const versionText = pkg.versions.map((version) => version.version).join(' ');
      const contributionText = pkg.versions
        .flatMap((version) => [
          ...version.contribution_summary.channel_providers,
          ...(version.contribution_summary.chat_surfaces ?? []),
          ...(version.contribution_summary.media_providers ?? []),
          ...version.contribution_summary.web_search_providers,
          ...version.contribution_summary.hooks,
          ...version.contribution_summary.tools,
          ...version.contribution_summary.skills,
        ])
        .join(' ');
      return (
        pkg.display_name.toLowerCase().includes(query)
        || pkg.package_id.toLowerCase().includes(query)
        || pkg.description.toLowerCase().includes(query)
        || versionText.toLowerCase().includes(query)
        || contributorCategories
          .map((category) => category.label)
          .join(' ')
          .toLowerCase()
          .includes(query)
        || contributionText.toLowerCase().includes(query)
      );
    });
  }, [packages, searchQuery, contributorFilter]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, contributorFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredPackages.length / PAGE_SIZE));
  const pagedPackages = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredPackages.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredPackages]);

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleImportChange = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (files.length === 0) {
      return;
    }

    setIsPreviewingImport(true);
    try {
      const preview = await previewExtensionBundle(files);
      setPendingImport({ files, preview });
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to inspect extension',
      );
    } finally {
      setIsPreviewingImport(false);
    }
  };

  const handleConfirmImport = async (upgradeMode?: ExtensionUpgradeMode) => {
    if (!pendingImport) {
      return;
    }

    setIsImporting(true);
    setImportingUpgradeMode(upgradeMode ?? null);
    setImportDialogPhase('installing');
    setImportProgress(null);

    const streamAbortController = new AbortController();
    importStreamAbortRef.current = streamAbortController;

    const MIN_STEP_MS = 500;
    let lastStepTime = 0;
    const pendingQueue: ExtensionImportProgressEvent[] = [];
    let flushTimer: ReturnType<typeof setTimeout> | null = null;

    const throttledProgressHandler = (event: ExtensionImportProgressEvent) => {
      const now = Date.now();
      const elapsed = now - lastStepTime;

      if (event.status === 'complete' || event.status === 'failed') {
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        if (pendingQueue.length > 0) {
          setImportProgress(pendingQueue[pendingQueue.length - 1]);
          pendingQueue.length = 0;
        }
        setImportProgress(event);
        lastStepTime = Date.now();
        return;
      }

      if (lastStepTime === 0 || elapsed >= MIN_STEP_MS) {
        if (pendingQueue.length > 0) {
          setImportProgress(pendingQueue[pendingQueue.length - 1]);
          pendingQueue.length = 0;
        }
        setImportProgress(event);
        lastStepTime = Date.now();
      } else {
        pendingQueue.push(event);
        if (!flushTimer) {
          flushTimer = setTimeout(() => {
            flushTimer = null;
            if (pendingQueue.length > 0) {
              setImportProgress(pendingQueue[pendingQueue.length - 1]);
              pendingQueue.length = 0;
            }
            lastStepTime = Date.now();
          }, MIN_STEP_MS - elapsed);
        }
      }
    };

    try {
      const job = await createExtensionBundleImportJob();
      const streamPromise = streamExtensionBundleImportJobEvents(
        job.job_id,
        throttledProgressHandler,
        streamAbortController.signal,
      ).catch((error) => {
        if (error instanceof Error && error.name === 'AbortError') {
          return;
        }
        console.error('Extension import progress stream failed:', error);
      });

      await importExtensionBundleWithJob({
        jobId: job.job_id,
        files: pendingImport.files,
        trustConfirmed: true,
        overwriteConfirmed: pendingImport.preview.requires_overwrite_confirmation,
        upgradeMode: upgradeMode ?? 'force',
      });

      await streamPromise;

      // Safe upgrade with running tasks: transition to draining phase
      if (
        upgradeMode === 'safe'
        && (pendingImport.preview.upgrade_impact?.running_task_count ?? 0) > 0
      ) {
        const refreshedPackages = await getExtensionPackages();
        const targetPkg = refreshedPackages.find(
          (pkg) => pkg.scope === pendingImport.preview.scope && pkg.name === pendingImport.preview.name,
        );
        if (targetPkg?.pending_upgrade) {
          setDrainingUpgrade(targetPkg.pending_upgrade);
          setImportDialogPhase('draining');
          setDrainingElapsedTick(Date.now());
          await loadPackages();
          setIsImporting(false);
          setImportingUpgradeMode(null);
          return;
        }
      }

      toast.success(getImportSuccessMessage(pendingImport.preview, upgradeMode ?? null));
      setPendingImport(null);
      setImportDialogPhase('review');
      setImportProgress(null);
      await loadPackages();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to import extension';
      setImportProgress((current) => ({
        event_id: current?.event_id ?? 0,
        job_id: current?.job_id ?? '',
        stage: 'failed',
        label: 'Import failed',
        percent: 100,
        status: 'failed',
        detail: message,
        metadata: null,
        timestamp: new Date().toISOString(),
      }));
      toast.error(message);
      setImportDialogPhase('review');
    } finally {
      if (flushTimer) {
        clearTimeout(flushTimer);
      }
      streamAbortController.abort();
      if (importStreamAbortRef.current === streamAbortController) {
        importStreamAbortRef.current = null;
      }
      setIsImporting(false);
      setImportingUpgradeMode(null);
    }
  };

  // Poll draining safe upgrade until tasks reach zero
  useEffect(() => {
    if (importDialogPhase !== 'draining' || !drainingUpgrade) return;
    const intervalId = window.setInterval(() => {
      void (async () => {
        try {
          const result = await reconcileExtensionUpgrade(drainingUpgrade.id);
          if (result.completed) {
            const agentsPath = location.pathname.startsWith('/studio/')
              ? '/studio/agents'
              : '/agents';
            toast.success('Safe upgrade finished. Affected agents now require republish.', {
              action: {
                label: 'Go',
                onClick: () => navigate(agentsPath),
              },
            });
            setPendingImport(null);
            setDrainingUpgrade(null);
            setImportDialogPhase('review');
            await loadPackages();
          } else if (result.upgrade) {
            setDrainingUpgrade(result.upgrade);
          }
        } catch (error) {
          console.error('Failed to reconcile pending extension upgrade:', error);
        }
      })();
    }, 3000);
    return () => window.clearInterval(intervalId);
  }, [importDialogPhase, drainingUpgrade, loadPackages, location.pathname, navigate]);

  const handleStatusToggle = async (
    installation: ExtensionInstallation,
  ) => {
    const nextStatus = installation.status === 'active' ? 'disabled' : 'active';
    setStatusUpdatingIds((current) => [...new Set([...current, installation.id])]);
    try {
      await updateExtensionInstallationStatus(installation.id, nextStatus);
      toast.success(
        nextStatus === 'active'
          ? `Enabled ${installation.package_id}@${installation.version}`
          : `Disabled ${installation.package_id}@${installation.version}`,
      );
      await loadPackages();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to update extension status',
      );
    } finally {
      setStatusUpdatingIds((current) => current.filter((item) => item !== installation.id));
    }
  };

  const handlePromptUninstall = async (
    installation: ExtensionInstallation,
  ) => {
    try {
      const references = await getExtensionInstallationReferences(installation.id);
      setPendingUninstall({ installation, references });
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to inspect uninstall impact',
      );
    }
  };

  const handleConfirmUninstall = async () => {
    if (!pendingUninstall) {
      return;
    }

    setIsUninstalling(true);
    try {
      const result = await uninstallExtensionInstallation(
        pendingUninstall.installation.id,
      );
      toast.success(
        result.mode === 'physical'
          ? `${pendingUninstall.installation.display_name} uninstalled`
          : `${pendingUninstall.installation.display_name} disabled (still referenced)`,
      );
      setPendingUninstall(null);
      await loadPackages();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to uninstall extension',
      );
    } finally {
      setIsUninstalling(false);
    }
  };

  const pendingUpgradeRunningTasks = pendingImport?.preview.upgrade_impact?.running_task_count ?? 0;

  return (
    <>
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-foreground">Extensions</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Import, inspect, and operate extension packages before binding them to agents.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(event) => void handleImportChange(event)}
            />
            <Button
              type="button"
              onClick={handleImportClick}
              disabled={isImporting || isPreviewingImport}
              size="sm"
              variant="outline"
              className="flex items-center gap-1.5"
            >
              {isImporting || isPreviewingImport ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              {isPreviewingImport ? 'Inspecting…' : isImporting ? 'Installing…' : 'Import'}
            </Button>
          </div>
        </div>

        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-1.5">
            {contributorFilterItems.map(({ key, label, count }) => (
              <button
                key={key}
                onClick={() => setContributorFilter(key)}
                className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Badge
                  variant={contributorFilter === key ? 'default' : 'outline'}
                  className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                    contributorFilter === key ? 'list-filter-badge-active' : ''
                  }`}
                >
                  {label}
                  <span className={contributorFilter === key ? 'opacity-70' : 'text-muted-foreground'}>
                    {count}
                  </span>
                </Badge>
              </button>
            ))}
            {contributorFilter !== 'all' ? (
              <button
                onClick={() => setContributorFilter('all')}
                className="text-muted-foreground transition-colors hover:text-foreground"
                aria-label="Clear extension filter"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
          <ButtonGroup className="list-search-group">
            <Input
              placeholder="Search by package, description, or contribution…"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              aria-label="Search extensions"
              autoComplete="off"
            />
            <Button variant="outline" size="sm" aria-label="Search extensions" tabIndex={-1}>
              <Search className="w-4 h-4" />
              Search
            </Button>
          </ButtonGroup>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center min-h-[50vh]">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filteredPackages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
            <p className="text-sm">
              {packages.length === 0
                ? 'No extensions installed yet.'
                : searchQuery || contributorFilter !== 'all'
                  ? 'No extensions match your current filters.'
                  : 'No extensions match your search.'}
            </p>
          </div>
        ) : (
          <>
            <StaggeredFadeInList
              items={pagedPackages}
              getItemKey={(pkg) => pkg.package_id}
              className="grid gap-4 md:grid-cols-2"
              itemClassName="h-full"
              renderItem={(pkg) => (
                <ExtensionPackageCard
                  pkg={pkg}
                  detailBasePath={detailBasePath}
                  onStatusToggle={handleStatusToggle}
                  onPromptUninstall={handlePromptUninstall}
                  isStatusUpdating={statusUpdatingIds.includes(
                    getMostRecentInstallation(pkg)?.id ?? -1,
                  )}
                />
              )}
            />

            {totalPages > 1 && (
              <div className="mt-4 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  {filteredPackages.length} package{filteredPackages.length !== 1 ? 's' : ''}
                  {searchQuery ? ' found' : ' total'}
                </span>
                <Pagination className="w-auto mx-0 justify-end">
                  <PaginationContent>
                    <PaginationItem>
                      <PaginationPrevious
                        href="#"
                        onClick={(event) => {
                          event.preventDefault();
                          if (currentPage > 1) {
                            setCurrentPage((page) => page - 1);
                          }
                        }}
                        className={currentPage === 1 ? 'pointer-events-none opacity-50' : ''}
                      />
                    </PaginationItem>

                    {buildPageList(currentPage, totalPages).map((page, index) => (
                      page === 'ellipsis' ? (
                        <PaginationItem key={`ellipsis-${index}`}>
                          <PaginationEllipsis />
                        </PaginationItem>
                      ) : (
                        <PaginationItem key={page}>
                          <PaginationLink
                            href="#"
                            isActive={page === currentPage}
                            onClick={(event) => {
                              event.preventDefault();
                              setCurrentPage(page);
                            }}
                          >
                            {page}
                          </PaginationLink>
                        </PaginationItem>
                      )
                    ))}

                    <PaginationItem>
                      <PaginationNext
                        href="#"
                        onClick={(event) => {
                          event.preventDefault();
                          if (currentPage < totalPages) {
                            setCurrentPage((page) => page + 1);
                          }
                        }}
                        className={currentPage === totalPages ? 'pointer-events-none opacity-50' : ''}
                      />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
              </div>
            )}
          </>
        )}
      </div>

      <ConfirmationModal
        isOpen={pendingUninstall !== null}
        title="Uninstall Extension Version"
        message={
          pendingUninstall
            ? [
                `${pendingUninstall.installation.display_name} ${pendingUninstall.installation.version}`,
                `Extension bindings: ${pendingUninstall.references.extension_binding_count}`,
                `Channel bindings: ${pendingUninstall.references.channel_binding_count}`,
                `Media bindings: ${pendingUninstall.references.media_provider_binding_count ?? 0}`,
                `Web-search bindings: ${pendingUninstall.references.web_search_binding_count}`,
                `Total bindings: ${pendingUninstall.references.binding_count}`,
                `Releases: ${pendingUninstall.references.release_count}`,
                `Test snapshots: ${pendingUninstall.references.test_snapshot_count}`,
                `Saved drafts: ${pendingUninstall.references.saved_draft_count}`,
                'If references still exist, Pivot will disable this version instead of deleting it physically.',
              ].join(' ')
            : ''
        }
        confirmText={isUninstalling ? 'Uninstalling…' : 'Uninstall'}
        onConfirm={() => void handleConfirmUninstall()}
        onCancel={() => {
          if (!isUninstalling) {
            setPendingUninstall(null);
          }
        }}
      />

      <Dialog
        open={pendingImport !== null}
        onOpenChange={(open) => {
          if (!open && !isImporting && importDialogPhase !== 'draining') {
            setPendingImport(null);
            setImportDialogPhase('review');
            setDrainingUpgrade(null);
            setImportProgress(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          {/* Draining phase: show progress card instead of review content */}
          {importDialogPhase === 'draining' && drainingUpgrade ? (
            <>
              <DialogHeader>
                <DialogTitle>Safe Upgrading</DialogTitle>
                <DialogDescription>
                  Pivot is waiting for running tasks to finish before applying the upgrade.
                  Affected agents are not accepting new client tasks.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-foreground">
                      Draining running tasks
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {formatElapsed(drainingUpgrade.created_at, drainingElapsedTick)}
                    </span>
                  </div>
                  <Progress value={100 - drainingUpgrade.running_task_count * 20} />
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">Affected agents {drainingUpgrade.affected_agent_count}</Badge>
                    <Badge variant={drainingUpgrade.running_task_count > 0 ? 'default' : 'outline'}>
                      Running tasks {drainingUpgrade.running_task_count}
                    </Badge>
                    {drainingUpgrade.affected_agent_names.length > 0 ? (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                            >
                              <Info className="h-3 w-3" />
                              {drainingUpgrade.affected_agent_names.length} agent names
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="bottom" className="max-w-xs">
                            <div className="flex flex-wrap gap-1">
                              {drainingUpgrade.affected_agent_names.map((name) => (
                                <Badge key={name} variant="secondary">{name}</Badge>
                              ))}
                            </div>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    ) : null}
                  </div>
                  {(drainingUpgrade.added_capabilities?.length ?? 0) > 0 ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="text-xs text-emerald-700 dark:text-emerald-300 cursor-default">
                            +{drainingUpgrade.added_capabilities?.length} added
                          </span>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" className="max-w-xs">
                          <p className="text-xs font-medium mb-1">Added capabilities</p>
                          <ul className="list-disc pl-3 text-xs">
                            {drainingUpgrade.added_capabilities?.map((item) => (
                              <li key={`added-${item.type}-${item.name}`}>
                                <code>{item.type}</code> · {item.name}
                              </li>
                            ))}
                          </ul>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : null}
                  {(drainingUpgrade.removed_capabilities?.length ?? 0) > 0 ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="text-xs text-rose-700 dark:text-rose-300 cursor-default ml-2">
                            -{drainingUpgrade.removed_capabilities?.length} removed
                          </span>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" className="max-w-xs">
                          <p className="text-xs font-medium mb-1">Removed capabilities</p>
                          <ul className="list-disc pl-3 text-xs">
                            {drainingUpgrade.removed_capabilities?.map((item) => (
                              <li key={`removed-${item.type}-${item.name}`}>
                                <code>{item.type}</code> · {item.name}
                              </li>
                            ))}
                          </ul>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">From {drainingUpgrade.source_version}</Badge>
                  <span>→</span>
                  <Badge variant="outline">To {drainingUpgrade.target_version}</Badge>
                </div>
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled
                >
                  Waiting for tasks to drain…
                </Button>
              </DialogFooter>
            </>
          ) : pendingImport ? (
            /* Review / Installing phase */
            <>
              <DialogHeader>
                <DialogTitle>
                  {importDialogPhase === 'installing'
                    ? (importingUpgradeMode === 'force' ? 'Force Upgrading…' : importingUpgradeMode === 'safe' ? 'Safe Upgrading…' : 'Installing…')
                    : isUpgradePreview(pendingImport.preview)
                      ? 'Upgrade Extension'
                      : 'Trust Extension'}
                </DialogTitle>
                <DialogDescription>
                  {importDialogPhase === 'installing'
                    ? 'Processing the extension package. Please wait.'
                    : isUpgradePreview(pendingImport.preview)
                      ? 'Review the upgrade impact before proceeding.'
                      : 'Review the extension package before installing.'}
                </DialogDescription>
              </DialogHeader>

              {importDialogPhase === 'installing' ? (
                <div className="space-y-2 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-foreground">
                      {importProgress?.status === 'failed' ? 'Import failed' : importProgress?.label ?? 'Preparing…'}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {importProgress ? `${Math.round(importProgress.percent)}%` : '0%'}
                    </span>
                  </div>
                  <Progress value={importProgress?.percent ?? 0} />
                  {importProgress?.detail && importProgress.status === 'failed' && (
                    <p className="text-sm text-destructive">{importProgress.detail}</p>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Package identity — concise */}
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-foreground">
                        {pendingImport.preview.display_name}
                      </span>
                      {isUpgradePreview(pendingImport.preview) ? (
                        <>
                          <Badge variant="outline">v{pendingImport.preview.upgrade_from_version}</Badge>
                          <span className="text-xs text-muted-foreground">→</span>
                          <Badge variant="default">v{pendingImport.preview.version}</Badge>
                        </>
                      ) : (
                        <Badge variant="outline">v{pendingImport.preview.version}</Badge>
                      )}
                      <Badge variant="outline">
                        {formatTrustStatusLabel(pendingImport.preview.trust_status)}
                      </Badge>
                      <TooltipProvider delayDuration={300}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button type="button" tabIndex={-1} className="text-muted-foreground hover:text-foreground">
                              <Info className="h-3.5 w-3.5" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="bottom" className="max-w-xs text-xs space-y-1">
                            <div>Package: <code>{pendingImport.preview.package_id}</code></div>
                            <div>Scope: <code>{pendingImport.preview.scope}</code></div>
                            <div>Source: <code>{pendingImport.preview.source}</code></div>
                            <div>Manifest: <code>{pendingImport.preview.manifest_hash}</code></div>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                    <p className="mt-1.5 text-sm text-muted-foreground">
                      {pendingImport.preview.description || 'No description provided.'}
                    </p>
                  </div>

                  {/* Upgrade impact — concise badges + tooltip for details */}
                  {isUpgradePreview(pendingImport.preview) ? (
                    <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="border-blue-500/30 text-blue-700 dark:text-blue-300">
                          Affected agents {pendingImport.preview.upgrade_impact?.affected_agent_count ?? 0}
                        </Badge>
                        <Badge variant="outline" className="border-blue-500/30 text-blue-700 dark:text-blue-300">
                          Running tasks {pendingImport.preview.upgrade_impact?.running_task_count ?? 0}
                        </Badge>
                        {pendingImport.preview.upgrade_impact?.manifest_hash_changed ? (
                          <Badge variant="outline" className="border-amber-500/40 text-amber-700 dark:text-amber-300">
                            Bindings need reconfiguration
                          </Badge>
                        ) : null}
                        {(pendingImport.preview.upgrade_impact?.affected_agent_names?.length ?? 0) > 0
                        || (pendingImport.preview.upgrade_impact?.added_capabilities?.length ?? 0) > 0
                        || (pendingImport.preview.upgrade_impact?.removed_capabilities?.length ?? 0) > 0 ? (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <button
                                  type="button"
                                  className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                                >
                                  <Info className="h-3 w-3" />
                                  Show details
                                </button>
                              </TooltipTrigger>
                              <TooltipContent side="bottom" className="max-w-sm space-y-2">
                                {pendingImport.preview.upgrade_impact?.affected_agent_names?.length ? (
                                  <div>
                                    <p className="font-medium">Affected agents</p>
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {pendingImport.preview.upgrade_impact.affected_agent_names.map((name) => (
                                        <Badge key={name} variant="secondary">{name}</Badge>
                                      ))}
                                    </div>
                                  </div>
                                ) : null}
                                {(pendingImport.preview.upgrade_impact?.added_capabilities?.length ?? 0) > 0 ? (
                                  <div>
                                    <p className="font-medium text-emerald-600">Added</p>
                                    <ul className="mt-0.5 list-disc pl-3">
                                      {pendingImport.preview.upgrade_impact?.added_capabilities?.map((item) => (
                                        <li key={`added-${item.type}-${item.name}`}>
                                          <code>{item.type}</code> · {item.name}
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                ) : null}
                                {(pendingImport.preview.upgrade_impact?.removed_capabilities?.length ?? 0) > 0 ? (
                                  <div>
                                    <p className="font-medium text-rose-600">Removed</p>
                                    <ul className="mt-0.5 list-disc pl-3">
                                      {pendingImport.preview.upgrade_impact?.removed_capabilities?.map((item) => (
                                        <li key={`removed-${item.type}-${item.name}`}>
                                          <code>{item.type}</code> · {item.name}
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                ) : null}
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        ) : null}
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {pendingUpgradeRunningTasks > 0
                          ? 'Safe upgrade will pause affected agents and drain running tasks before applying. Force upgrade applies immediately.'
                          : 'Upgraded bindings and affected agents will require republish before serving clients.'}
                      </p>
                    </div>
                  ) : null}

                  {pendingImport.preview.identical_to_installed ? (
                    <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
                      This exact version is already installed. Confirming will reuse the existing installation.
                    </div>
                  ) : null}

                  {pendingImport.preview.requires_overwrite_confirmation ? (
                    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-foreground">
                      A different payload is installed at{' '}
                      <code>{pendingImport.preview.package_id}@{pendingImport.preview.version}</code>.
                      Confirming will replace it.
                    </div>
                  ) : null}

                  {pendingImport.preview.overwrite_blocked_reason ? (
                    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-foreground">
                      <p>{pendingImport.preview.overwrite_blocked_reason}</p>
                      {pendingImport.preview.existing_reference_summary ? (
                        <p className="mt-2 text-xs text-muted-foreground">
                          Bindings {pendingImport.preview.existing_reference_summary.binding_count}
                          {' · '}
                          Releases {pendingImport.preview.existing_reference_summary.release_count}
                          {' · '}
                          Test snapshots {pendingImport.preview.existing_reference_summary.test_snapshot_count}
                          {' · '}
                          Saved drafts {pendingImport.preview.existing_reference_summary.saved_draft_count}
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Contributions + Permissions */}
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-lg border border-border p-3">
                      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Contributions
                      </div>
                      <div className="mt-3 space-y-3">
                        {buildContributionGroups(pendingImport.preview.contribution_summary).length > 0 ? (
                          buildContributionGroups(pendingImport.preview.contribution_summary).map((group) => (
                            <div key={group.label}>
                              <div className="text-sm font-medium text-foreground">{group.label}</div>
                              <div className="mt-1 flex flex-wrap gap-1.5">
                                {group.values.map((value) => (
                                  <Badge
                                    key={`${group.label}-${value}`}
                                    variant={getContributionBadgeVariant(group.tone)}
                                  >
                                    {value}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          ))
                        ) : (
                          <p className="text-sm text-muted-foreground">
                            No contributions declared.
                          </p>
                        )}
                      </div>
                    </div>

                    <div className="rounded-lg border border-border p-3">
                      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Permissions
                      </div>
                      <div className="mt-3">
                        {Object.keys(pendingImport.preview.permissions).length > 0 ? (
                          <pre className="max-h-52 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
                            {JSON.stringify(pendingImport.preview.permissions, null, 2)}
                          </pre>
                        ) : (
                          <p className="text-sm text-muted-foreground">
                            No explicit permissions declared.
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => { setPendingImport(null); setImportDialogPhase('review'); }}
                  disabled={isImporting}
                >
                  Cancel
                </Button>
                {importDialogPhase === 'review' && isUpgradePreview(pendingImport.preview) ? (
                  <>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void handleConfirmImport('safe')}
                      disabled={isImporting || pendingImport.preview.overwrite_blocked_reason !== ''}
                    >
                      {isImporting && importingUpgradeMode === 'safe'
                        ? 'Safe upgrading…'
                        : 'Safe upgrade'}
                    </Button>
                    <Button
                      type="button"
                      onClick={() => void handleConfirmImport('force')}
                      disabled={isImporting || pendingImport.preview.overwrite_blocked_reason !== ''}
                    >
                      {isImporting && importingUpgradeMode === 'force'
                        ? 'Force upgrading…'
                        : 'Force upgrade'}
                    </Button>
                  </>
                ) : importDialogPhase === 'review' ? (
                  <Button
                    type="button"
                    onClick={() => void handleConfirmImport()}
                    disabled={isImporting || pendingImport.preview.overwrite_blocked_reason !== ''}
                  >
                    {getImportActionLabel(pendingImport.preview, isImporting)}
                  </Button>
                ) : null}
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

    </>
  );
}

interface ExtensionPackageCardProps {
  pkg: ExtensionPackage;
  detailBasePath: string;
  onStatusToggle: (installation: ExtensionInstallation) => void | Promise<void>;
  onPromptUninstall: (installation: ExtensionInstallation) => void | Promise<void>;
  isStatusUpdating: boolean;
}

/**
 * Render one compact extension package card for the list page.
 */
function ExtensionPackageCard({
  pkg,
  detailBasePath,
  onStatusToggle,
  onPromptUninstall,
  isStatusUpdating,
}: ExtensionPackageCardProps) {
  const navigate = useNavigate();
  const detailPath = `${detailBasePath}/${pkg.scope}/${pkg.name}`;
  const primaryInstallation = getMostRecentInstallation(pkg);
  const latestInstallation = (
    pkg.versions.find((installation) => installation.version === pkg.latest_version)
    ?? pkg.versions[0]
    ?? primaryInstallation
  );
  const latestIsDisabled = latestInstallation?.status === 'disabled';
  const contributorCategories = getPackageContributorCategories(pkg);

  const handleCardClick = () => {
    navigate(detailPath);
  };

  const handleCardKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleCardClick();
    }
  };

  const handleMenuClick = (event: MouseEvent) => {
    event.stopPropagation();
  };

  return (
    <Card
      className="group h-full cursor-pointer border-border/80 p-3 transition-colors duration-150 hover:border-primary/30 hover:bg-accent/30"
      role="button"
      tabIndex={0}
      aria-label={`Open extension ${pkg.display_name}`}
      onClick={handleCardClick}
      onKeyDown={handleCardKeyDown}
    >
      <div className="flex items-start gap-3">
        <ExtensionLogoAvatar
          name={pkg.display_name}
          logoUrl={pkg.logo_url ?? primaryInstallation?.logo_url ?? null}
          fallback={<Server className="h-4.5 w-4.5" aria-hidden="true" />}
          containerClassName="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"
          imageClassName="size-full rounded-lg object-cover"
        />

        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex h-10 flex-col justify-between">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      latestIsDisabled
                        ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.75)]'
                        : 'bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.75)]'
                    }`}
                    aria-label={latestIsDisabled ? 'Latest version disabled' : 'Latest version active'}
                  />
                  <span className="truncate text-sm font-medium leading-[1.1rem] text-foreground">
                    {pkg.display_name}
                  </span>
                  <span className="shrink-0 text-[11px] leading-[1.1rem] text-muted-foreground">
                    by {pkg.scope}
                  </span>
                </div>
                <p className="line-clamp-1 text-[11px] leading-[1.1rem] text-muted-foreground">
                  {pkg.description || 'No description provided.'}
                </p>
              </div>
            </div>

            {primaryInstallation ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                    onClick={handleMenuClick}
                    aria-label={`Extension options for ${pkg.display_name}`}
                  >
                    <MoreHorizontal className="h-3 w-3" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  size="medium"
                  onClick={(event) => event.stopPropagation()}
                >
                  <DropdownMenuItem
                    onClick={(event) => {
                      handleMenuClick(event as unknown as MouseEvent);
                      void onStatusToggle(primaryInstallation);
                    }}
                    disabled={isStatusUpdating}
                  >
                    {isStatusUpdating ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : primaryInstallation.status === 'active' ? (
                      <XCircle className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                    )}
                    {primaryInstallation.status === 'active' ? 'Disable' : 'Enable'}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={(event) => {
                      handleMenuClick(event as unknown as MouseEvent);
                      void onPromptUninstall(primaryInstallation);
                    }}
                    className="text-destructive focus:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                    Uninstall
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {pkg.pending_upgrade ? (
              <Badge variant="outline" className="h-4 px-1.5 py-0 text-[10px] border-blue-500/30 text-blue-700 dark:text-blue-300">
                Upgrade draining
              </Badge>
            ) : null}
            {contributorCategories.length > 0 ? (
              contributorCategories.map((category) => (
                <Badge
                  key={category.key}
                  variant="secondary"
                  className="h-4 px-1.5 py-0 text-[10px]"
                >
                  {category.label}
                </Badge>
              ))
            ) : (
              <Badge variant="outline" className="h-4 px-1.5 py-0 text-[10px] text-muted-foreground">
                No contributors
              </Badge>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default ExtensionsPage;
