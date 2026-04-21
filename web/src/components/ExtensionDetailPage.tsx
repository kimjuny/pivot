import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import {
  ArrowLeft,
  Brain,
  CheckCircle2,
  Globe2,
  Loader2,
  Radio,
  Server,
  Trash2,
  Wrench,
  XCircle,
  Zap,
  type LucideIcon,
} from "@/lib/lucide";
import { toast } from "sonner";

import ConfirmationModal from "@/components/ConfirmationModal";
import { ExtensionLogoAvatar } from "@/components/ExtensionLogoAvatar";
import ExtensionHookReplayPanel from "@/components/ExtensionHookReplayPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  getExtensionInstallationConfiguration,
  getExtensionPackages,
  uninstallExtensionInstallation,
  updateExtensionInstallationConfiguration,
  updateExtensionInstallationStatus,
  type ExtensionConfigurationField,
  type ExtensionContributionItem,
  type ExtensionContributionSummary,
  type ExtensionInstallation,
  type ExtensionInstallationConfigurationState,
  type ExtensionUninstallResult,
  type ExtensionPackage,
} from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";
import { MarkdownRenderer } from "@/pages/chat/components/MarkdownRenderer";

interface ContributionGroup {
  /** Human-readable group title shown in Overview and Versions. */
  label: string;
  /** Contribution names or provider keys displayed as badges. */
  values: string[];
  /** Visual emphasis for providers, runtime hooks, and optional assets. */
  tone: "provider" | "runtime" | "lightweight";
}

interface ContributionItemPresentation {
  /** Stable item key used while rendering aggregated rows. */
  id: string;
  /** Human-readable badge label shown next to the name. */
  badgeLabel: string;
  /** One contributed capability. */
  item: ExtensionContributionItem;
  /** Icon shown in the neutral circular marker. */
  icon: LucideIcon;
}

interface PackageStatusBadge {
  /** Operator-facing summary label. */
  label: string;
  /** Visual tone that distinguishes live usage from neutral state. */
  tone: "provider" | "runtime";
}

interface ReferenceBadge {
  /** Human-readable summary label for one reference type. */
  label: string;
  /** Count currently attached to this installation. */
  count: number;
  /** Tone keeps provider references visually distinct from runtime state. */
  tone: "provider" | "runtime";
}

interface SetupStateMap {
  /** Configuration state keyed by installation id. */
  [installationId: number]: ExtensionInstallationConfigurationState | undefined;
}

interface SetupDraftMap {
  /** Draft editable values keyed by installation id. */
  [installationId: number]: Record<string, unknown> | undefined;
}

/**
 * Build stable contribution groups for one installed extension version.
 *
 * Why: extensions can contribute infrastructure providers, runtime hooks, and
 * optional helper assets. Showing each class separately makes the package
 * surface area understandable before the operator enables it.
 */
function buildContributionGroups(summary: ExtensionContributionSummary): ContributionGroup[] {
  const groups: ContributionGroup[] = [
    {
      label: "Channel Providers",
      values: summary.channel_providers,
      tone: "provider",
    },
    {
      label: "Image Providers",
      values: summary.media_providers ?? [],
      tone: "provider",
    },
    {
      label: "Web Search Providers",
      values: summary.web_search_providers,
      tone: "provider",
    },
    {
      label: "Chat Surfaces",
      values: summary.chat_surfaces ?? [],
      tone: "runtime",
    },
    {
      label: "Lifecycle Hooks",
      values: summary.hooks,
      tone: "runtime",
    },
    {
      label: "Tools (Optional)",
      values: summary.tools,
      tone: "lightweight",
    },
    {
      label: "Skills (Optional)",
      values: summary.skills,
      tone: "lightweight",
    },
  ];
  return groups.filter((group) => group.values.length > 0);
}

/**
 * Map one contribution tone to a shared badge variant.
 */
function getContributionBadgeVariant(
  tone: ContributionGroup["tone"],
): "default" | "secondary" | "outline" {
  if (tone === "provider") {
    return "default";
  }
  if (tone === "runtime") {
    return "secondary";
  }
  return "outline";
}

/**
 * Choose one stable visual language for each contribution type.
 *
 * Why: the overview list should stay readable across tools, skills, providers,
 * and hooks without scattering icon and badge decisions throughout the JSX.
 */
function getContributionPresentation(
  item: ExtensionContributionItem,
): ContributionItemPresentation {
  switch (item.type) {
    case "hook":
      return {
        id: `hook-${item.name}`,
        badgeLabel: "Hook",
        item,
        icon: Zap,
      };
    case "skill":
      return {
        id: `skill-${item.name}`,
        badgeLabel: "Skill",
        item,
        icon: Brain,
      };
    case "tool":
      return {
        id: `tool-${item.name}`,
        badgeLabel: "Tool",
        item,
        icon: Wrench,
      };
    case "channel_provider":
      return {
        id: `channel_provider-${item.name}`,
        badgeLabel: "Channel",
        item,
        icon: Radio,
      };
    case "web_search_provider":
      return {
        id: `web_search_provider-${item.name}`,
        badgeLabel: "Web Search",
        item,
        icon: Globe2,
      };
    case "media_provider":
      return {
        id: `media_provider-${item.name}`,
        badgeLabel: "Media",
        item,
        icon: Server,
      };
    default:
      return {
        id: `${item.type}-${item.name}`,
        badgeLabel: item.type,
        item,
        icon: Server,
      };
  }
}

/**
 * Merge package contribution items so the newest installed version wins.
 *
 * Why: package overview should describe the current package surface area once,
 * even when multiple installed versions declare the same capability.
 */
function buildPackageContributionItems(pkg: ExtensionPackage): ContributionItemPresentation[] {
  const seenItems = new Set<string>();
  const items: ContributionItemPresentation[] = [];

  pkg.versions.forEach((version) => {
    version.contribution_items.forEach((item) => {
      const normalizedKey = `${item.type}:${item.name.trim().toLowerCase()}`;
      if (seenItems.has(normalizedKey)) {
        return;
      }
      seenItems.add(normalizedKey);
      items.push(getContributionPresentation(item));
    });
  });
  return items;
}

/**
 * Summarize package-level operational risk from every installed version.
 *
 * Why: the detail header should immediately tell operators whether the package
 * is currently in use or pinned before they inspect individual versions.
 */
function buildPackageStatusBadges(pkg: ExtensionPackage): PackageStatusBadge[] {
  const totalBindingCount = pkg.versions.reduce(
    (sum, version) => sum + (version.reference_summary?.binding_count ?? 0),
    0,
  );
  const totalPinnedCount = pkg.versions.reduce(
    (sum, version) =>
      sum
      + (version.reference_summary?.release_count ?? 0)
      + (version.reference_summary?.test_snapshot_count ?? 0)
      + (version.reference_summary?.saved_draft_count ?? 0),
    0,
  );

  const badges: PackageStatusBadge[] = [];
  if (totalBindingCount > 0) {
    badges.push({
      label: `In Use ${totalBindingCount}`,
      tone: "provider",
    });
  }
  if (totalPinnedCount > 0) {
    badges.push({
      label: `Pinned ${totalPinnedCount}`,
      tone: "runtime",
    });
  }
  return badges;
}

/**
 * Build visible usage badges for one installed version.
 *
 * Why: once the list page becomes intentionally compact, version-level usage
 * counts still need a clear home in the detail page before operators decide to
 * disable or uninstall a specific installation.
 */
function buildReferenceBadges(installation: ExtensionInstallation): ReferenceBadge[] {
  const summary = installation.reference_summary;
  if (!summary) {
    return [];
  }

  const badges: ReferenceBadge[] = [
    {
      label: "Extension Bindings",
      count: summary.extension_binding_count,
      tone: "runtime",
    },
    {
      label: "Channel Bindings",
      count: summary.channel_binding_count,
      tone: "provider",
    },
    {
      label: "Image Bindings",
      count: summary.media_provider_binding_count ?? 0,
      tone: "provider",
    },
    {
      label: "Web Search Bindings",
      count: summary.web_search_binding_count,
      tone: "provider",
    },
    {
      label: "Releases",
      count: summary.release_count,
      tone: "runtime",
    },
    {
      label: "Test Snapshots",
      count: summary.test_snapshot_count,
      tone: "runtime",
    },
    {
      label: "Saved Drafts",
      count: summary.saved_draft_count,
      tone: "runtime",
    },
  ];
  return badges.filter((badge) => badge.count > 0);
}

/**
 * Convert one trust status into a short human-readable badge label.
 */
function formatTrustStatusLabel(trustStatus: string): string {
  switch (trustStatus) {
    case "trusted_local":
      return "Trusted Local";
    case "verified":
      return "Verified";
    case "unverified":
      return "Unverified";
    default:
      return trustStatus;
  }
}

/**
 * Normalize one input value into a UI-friendly string.
 */
function formatConfigValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number") {
    return String(value);
  }
  return "";
}

/**
 * Build an initial draft from one fetched setup state.
 *
 * Why: setup forms should start from persisted values and fall back to manifest
 * defaults without hard-coding field names in the page component.
 */
function buildSetupDraft(
  state: ExtensionInstallationConfigurationState,
): Record<string, unknown> {
  const draft: Record<string, unknown> = { ...state.config };
  state.configuration_schema.installation.fields.forEach((field) => {
    if (!(field.key in draft) && field.default !== undefined) {
      draft[field.key] = field.default;
    }
  });
  return draft;
}

/**
 * Parse a draft input value according to one manifest field type.
 */
function parseConfigInputValue(
  field: ExtensionConfigurationField,
  rawValue: string | boolean,
): unknown {
  if (field.type === "boolean") {
    return Boolean(rawValue);
  }
  if (field.type === "number") {
    const parsed = Number(rawValue);
    return Number.isFinite(parsed) ? parsed : rawValue;
  }
  return rawValue;
}

/**
 * Render one package-scoped extension detail page.
 *
 * Why: extension inventory and extension debugging are different workflows.
 * The list page should stay compact, while this detail page becomes the home
 * for package overview, versions, and package-specific hook replay.
 */
export default function ExtensionDetailPage() {
  const { scope = "", name = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [packages, setPackages] = useState<ExtensionPackage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [setupStates, setSetupStates] = useState<SetupStateMap>({});
  const [setupDrafts, setSetupDrafts] = useState<SetupDraftMap>({});
  const [loadingSetupIds, setLoadingSetupIds] = useState<number[]>([]);
  const [savingSetupIds, setSavingSetupIds] = useState<number[]>([]);
  const [statusUpdatingId, setStatusUpdatingId] = useState<number | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<ExtensionInstallation | null>(null);
  const [uninstallingId, setUninstallingId] = useState<number | null>(null);
  const listPath = location.pathname.startsWith("/studio/")
    ? "/studio/assets/extensions"
    : "/extensions";

  const loadPackages = useCallback(async () => {
    setIsLoading(true);
    try {
      setPackages(await getExtensionPackages());
    } catch (error) {
      console.error("Failed to load extension detail:", error);
      toast.error("Failed to load extension detail");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPackages();
  }, [loadPackages]);

  const pkg = useMemo(
    () => packages.find((candidate) => candidate.scope === scope && candidate.name === name) ?? null,
    [name, packages, scope],
  );

  const loadSetupState = useCallback(async (installationId: number) => {
    setLoadingSetupIds((current) => [...new Set([...current, installationId])]);
    try {
      const state = await getExtensionInstallationConfiguration(installationId);
      setSetupStates((current) => ({
        ...current,
        [installationId]: state,
      }));
      setSetupDrafts((current) => ({
        ...current,
        [installationId]: current[installationId] ?? buildSetupDraft(state),
      }));
    } catch (error) {
      console.error("Failed to load extension setup state:", error);
      toast.error("Failed to load extension setup");
    } finally {
      setLoadingSetupIds((current) => current.filter((item) => item !== installationId));
    }
  }, []);

  useEffect(() => {
    if (!pkg) {
      return;
    }
    pkg.versions.forEach((installation) => {
      if (setupStates[installation.id]) {
        return;
      }
      void loadSetupState(installation.id);
    });
  }, [loadSetupState, pkg, setupStates]);

  const latestInstallation = pkg?.versions[0] ?? null;
  const isLatestStatusUpdating = latestInstallation?.id === statusUpdatingId;
  const isLatestUninstalling = latestInstallation?.id === uninstallingId;
  const aggregatedContributions = useMemo(() => {
    if (!pkg) {
      return [];
    }
    const merged = {
      channel_providers: Array.from(
        new Set(pkg.versions.flatMap((version) => version.contribution_summary.channel_providers)),
      ),
      chat_surfaces: Array.from(
        new Set(pkg.versions.flatMap((version) => version.contribution_summary.chat_surfaces ?? [])),
      ),
      media_providers: Array.from(
        new Set(pkg.versions.flatMap((version) => version.contribution_summary.media_providers ?? [])),
      ),
      web_search_providers: Array.from(
        new Set(pkg.versions.flatMap((version) => version.contribution_summary.web_search_providers)),
      ),
      hooks: Array.from(new Set(pkg.versions.flatMap((version) => version.contribution_summary.hooks))),
      tools: Array.from(new Set(pkg.versions.flatMap((version) => version.contribution_summary.tools))),
      skills: Array.from(new Set(pkg.versions.flatMap((version) => version.contribution_summary.skills))),
    };
    return buildContributionGroups(merged);
  }, [pkg]);
  const aggregatedContributionItems = useMemo(
    () => (pkg ? buildPackageContributionItems(pkg) : []),
    [pkg],
  );

  const updateDraftValue = useCallback(
    (installationId: number, field: ExtensionConfigurationField, rawValue: string | boolean) => {
      setSetupDrafts((current) => ({
        ...current,
        [installationId]: {
          ...(current[installationId] ?? {}),
          [field.key]: parseConfigInputValue(field, rawValue),
        },
      }));
    },
    [],
  );

  const saveSetup = useCallback(
    async (installation: ExtensionInstallation) => {
      const draft = setupDrafts[installation.id] ?? {};
      setSavingSetupIds((current) => [...new Set([...current, installation.id])]);
      try {
        const state = await updateExtensionInstallationConfiguration(installation.id, draft);
        setSetupStates((current) => ({
          ...current,
          [installation.id]: state,
        }));
        setSetupDrafts((current) => ({
          ...current,
          [installation.id]: buildSetupDraft(state),
        }));
        toast.success(`Saved setup for ${installation.package_id}@${installation.version}`);
      } catch (error) {
        console.error("Failed to save extension setup:", error);
        toast.error(
          error instanceof Error ? error.message : "Failed to save extension setup",
        );
      } finally {
        setSavingSetupIds((current) => current.filter((item) => item !== installation.id));
      }
    },
    [setupDrafts],
  );

  const handleStatusToggle = useCallback(
    async (installation: ExtensionInstallation) => {
      const nextStatus = installation.status === "active" ? "disabled" : "active";
      setStatusUpdatingId(installation.id);
      try {
        await updateExtensionInstallationStatus(installation.id, nextStatus);
        toast.success(
          nextStatus === "active"
            ? `Enabled ${installation.package_id}@${installation.version}`
            : `Disabled ${installation.package_id}@${installation.version}`,
        );
        await loadPackages();
      } catch (error) {
        console.error("Failed to update extension status:", error);
        toast.error(
          error instanceof Error ? error.message : "Failed to update extension status",
        );
      } finally {
        setStatusUpdatingId((current) => (current === installation.id ? null : current));
      }
    },
    [loadPackages],
  );

  const handleConfirmUninstall = useCallback(
    async (installation: ExtensionInstallation) => {
      setUninstallingId(installation.id);
      try {
        const result: ExtensionUninstallResult = await uninstallExtensionInstallation(
          installation.id,
        );
        toast.success(
          result.mode === "physical"
            ? "Extension version uninstalled"
            : "Extension version disabled because it is still referenced",
        );
        setPendingUninstall(null);

        if (pkg?.versions.length === 1 && result.mode === "physical") {
          navigate(listPath, { replace: true });
          return;
        }

        await loadPackages();
      } catch (error) {
        console.error("Failed to uninstall extension:", error);
        toast.error(error instanceof Error ? error.message : "Failed to uninstall extension");
      } finally {
        setUninstallingId((current) => (current === installation.id ? null : current));
      }
    },
    [listPath, loadPackages, navigate, pkg?.versions.length],
  );

  if (isLoading) {
    return (
      <div className="mx-auto flex h-64 max-w-5xl items-center justify-center px-6 text-sm text-muted-foreground">
        Loading extension…
      </div>
    );
  }

  if (!pkg) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-8">
        <Card>
          <CardHeader>
            <CardTitle>Extension Not Found</CardTitle>
            <CardDescription>
              Pivot could not find the requested package. It may have been removed or the URL may
              be outdated.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link to={listPath}>Back To Extensions</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Button asChild variant="ghost" className="-ml-3 w-fit">
          <Link to={listPath}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back To Extensions
          </Link>
        </Button>
        {latestInstallation ? (
          <div className="flex items-center gap-1 sm:ml-auto sm:justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className={
                latestInstallation.status === "active"
                  ? "text-muted-foreground hover:bg-amber-500/10 hover:text-amber-700 dark:hover:text-amber-300"
                  : "text-muted-foreground hover:bg-emerald-500/10 hover:text-emerald-700 dark:hover:text-emerald-300"
              }
              onClick={() => {
                void handleStatusToggle(latestInstallation);
              }}
              disabled={isLatestStatusUpdating || isLatestUninstalling}
            >
              {isLatestStatusUpdating ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : latestInstallation.status === "active" ? (
                <XCircle className="h-4 w-4" aria-hidden="true" />
              ) : (
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              )}
              {latestInstallation.status === "active" ? "Disable" : "Enable"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => {
                setPendingUninstall(latestInstallation);
              }}
              disabled={isLatestStatusUpdating || isLatestUninstalling}
            >
              {isLatestUninstalling ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              )}
              Uninstall
            </Button>
          </div>
        ) : null}
      </div>

      <div className="mb-6">
        <Card>
          <CardHeader className="space-y-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex-1 space-y-3">
                <div className="flex items-start gap-4">
                  <ExtensionLogoAvatar
                    name={pkg.display_name}
                    logoUrl={pkg.logo_url ?? latestInstallation?.logo_url ?? null}
                    fallback={<Server className="h-6 w-6 text-primary" aria-hidden="true" />}
                    containerClassName="flex aspect-square size-16 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-muted/20 p-2.5"
                    imageClassName="h-full w-full rounded-lg object-contain"
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <CardTitle className="min-w-0 text-2xl">{pkg.display_name}</CardTitle>
                    <CardDescription className="text-sm">
                      {pkg.description || "No description provided."}
                    </CardDescription>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">{pkg.package_id}</Badge>
                  <Badge variant="outline">Latest {pkg.latest_version}</Badge>
                  <Badge variant="outline">Enabled Versions {pkg.active_version_count}</Badge>
                  <Badge variant="outline">Disabled Versions {pkg.disabled_version_count}</Badge>
                  {buildPackageStatusBadges(pkg).map((badge) => (
                    <Badge
                      key={`${pkg.package_id}-${badge.label}`}
                      variant="default"
                    >
                      {badge.label}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </CardHeader>
        </Card>
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList className="grid h-auto w-full grid-cols-4">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="setup">Setup</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
          <TabsTrigger value="hook-replay">Hook Replay</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          {pkg.readme_markdown.trim() ? (
            <section className="space-y-3">
              <div className="space-y-1">
                <h2 className="text-base font-semibold text-foreground">README.md</h2>
                <p className="text-sm text-muted-foreground">
                  Package-authored documentation and usage notes for this extension.
                </p>
              </div>
              <Card>
                <CardContent className="pt-6">
                  <MarkdownRenderer content={pkg.readme_markdown} variant="document" />
                </CardContent>
              </Card>
            </section>
          ) : null}

          <section className="space-y-3">
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-foreground">Includes</h2>
              <p className="text-sm text-muted-foreground">
                Package-level contribution summary across all installed versions.
              </p>
            </div>
            <Card>
              <CardContent className="pt-6">
                {aggregatedContributionItems.length > 0 ? (
                  <div className="overflow-hidden rounded-lg border border-border">
                    {aggregatedContributionItems.map((entry, index) => {
                      const Icon = entry.icon;
                      return (
                      <div
                        key={entry.id}
                        className={`flex items-center gap-3 px-4 py-3 ${
                          index > 0 ? "border-t border-border" : ""
                        }`}
                      >
                        <div className="flex size-10 shrink-0 items-center justify-center rounded-full border border-border text-muted-foreground">
                          <Icon className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="text-sm font-medium text-foreground">
                              {entry.item.name}
                            </div>
                            <Badge variant="outline" className="font-normal">
                              {entry.badgeLabel}
                            </Badge>
                          </div>
                          <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                            {entry.item.description || "No description provided."}
                          </p>
                        </div>
                      </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">No contributions declared.</div>
                )}
              </CardContent>
            </Card>
          </section>

          <section className="space-y-3">
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-foreground">Information</h2>
              <p className="text-sm text-muted-foreground">
                Stable package metadata and the most recent installed version summary.
              </p>
            </div>
            <Card>
              <CardContent className="grid gap-4 pt-6 md:grid-cols-2">
                <div className="rounded-lg border border-border p-4">
                  <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Identity
                  </div>
                  <dl className="mt-3 space-y-2 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <dt className="text-muted-foreground">Package</dt>
                      <dd className="text-right text-foreground">{pkg.package_id}</dd>
                    </div>
                    <div className="flex items-start justify-between gap-3">
                      <dt className="text-muted-foreground">Latest version</dt>
                      <dd className="text-right text-foreground">{pkg.latest_version}</dd>
                    </div>
                    <div className="flex items-start justify-between gap-3">
                      <dt className="text-muted-foreground">Active versions</dt>
                      <dd className="text-right text-foreground">{pkg.active_version_count}</dd>
                    </div>
                  </dl>
                </div>

                {latestInstallation ? (
                  <div className="rounded-lg border border-border p-4">
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Latest installation
                    </div>
                    <dl className="mt-3 space-y-2 text-sm">
                      <div className="flex items-start justify-between gap-3">
                        <dt className="text-muted-foreground">Trust</dt>
                        <dd className="text-right text-foreground">
                          {formatTrustStatusLabel(latestInstallation.trust_status)}
                        </dd>
                      </div>
                      <div className="flex items-start justify-between gap-3">
                        <dt className="text-muted-foreground">Source</dt>
                        <dd className="text-right text-foreground">{latestInstallation.source}</dd>
                      </div>
                      <div className="flex items-start justify-between gap-3">
                        <dt className="text-muted-foreground">Installed</dt>
                        <dd className="text-right text-foreground">
                          {formatTimestamp(latestInstallation.created_at)}
                        </dd>
                      </div>
                    </dl>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </section>
        </TabsContent>

        <TabsContent value="setup" className="space-y-4">
          {pkg.versions.map((installation) => {
            const setupState = setupStates[installation.id];
            const setupDraft = setupDrafts[installation.id] ?? {};
            const installationFields =
              setupState?.configuration_schema.installation.fields ?? [];
            const isLoadingSetup = loadingSetupIds.includes(installation.id);
            const isSavingSetup = savingSetupIds.includes(installation.id);

            return (
              <Card key={`setup-${installation.id}`}>
                <CardHeader className="space-y-3">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-base">{installation.version}</CardTitle>
                        <Badge variant={installation.status === "active" ? "default" : "outline"}>
                          {installation.status}
                        </Badge>
                      </div>
                      <CardDescription className="mt-1">
                        Configure installation-level fields such as external service URLs,
                        credentials, and defaults for this version.
                      </CardDescription>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Installed {formatTimestamp(installation.created_at)}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {isLoadingSetup ? (
                    <div className="text-sm text-muted-foreground">Loading setup…</div>
                  ) : (
                    <>
                      {installationFields.length === 0 ? (
                        <div className="text-sm text-muted-foreground">
                          This version does not declare installation configuration fields.
                        </div>
                      ) : (
                        <div className="grid gap-4">
                          {installationFields.map((field) => (
                            <div key={`${installation.id}-${field.key}`} className="grid gap-2">
                              <div className="flex items-center justify-between gap-3">
                                <Label htmlFor={`setup-${installation.id}-${field.key}`}>
                                  {field.label}
                                </Label>
                                {field.required ? (
                                  <Badge variant="outline" className="text-[10px] uppercase">
                                    Required
                                  </Badge>
                                ) : null}
                              </div>
                              {field.type === "boolean" ? (
                                <div className="flex items-center gap-3 rounded-lg border border-border px-3 py-2">
                                  <Switch
                                    id={`setup-${installation.id}-${field.key}`}
                                    checked={Boolean(setupDraft[field.key])}
                                    onCheckedChange={(checked) => {
                                      updateDraftValue(installation.id, field, checked);
                                    }}
                                  />
                                  <span className="text-sm text-muted-foreground">
                                    {field.description || "Toggle this setting on or off."}
                                  </span>
                                </div>
                              ) : (
                                <Input
                                  id={`setup-${installation.id}-${field.key}`}
                                  type={
                                    field.type === "secret"
                                      ? "password"
                                      : field.type === "number"
                                        ? "number"
                                        : "text"
                                  }
                                  value={formatConfigValue(setupDraft[field.key])}
                                  placeholder={field.placeholder || field.label}
                                  onChange={(event) => {
                                    updateDraftValue(
                                      installation.id,
                                      field,
                                      event.currentTarget.value,
                                    );
                                  }}
                                />
                              )}
                              {field.description && field.type !== "boolean" ? (
                                <p className="text-xs text-muted-foreground">
                                  {field.description}
                                </p>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="flex justify-end">
                        <div className="flex flex-wrap justify-end gap-2">
                          <Button
                            onClick={() => {
                              void saveSetup(installation);
                            }}
                            disabled={isSavingSetup}
                          >
                            {isSavingSetup ? "Saving…" : "Save Setup"}
                          </Button>
                        </div>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </TabsContent>

        <TabsContent value="versions" className="space-y-4">
          {pkg.versions.map((installation) => (
            <Card key={installation.id}>
              <CardHeader className="space-y-3">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <CardTitle className="text-base">{installation.version}</CardTitle>
                      <Badge variant={installation.status === "active" ? "default" : "outline"}>
                        {installation.status}
                      </Badge>
                      <Badge variant="outline">
                        {formatTrustStatusLabel(installation.trust_status)}
                      </Badge>
                    </div>
                    <CardDescription className="mt-1">
                      {installation.source}
                      {" · "}
                      {installation.trust_source}
                      {" · "}
                      {installation.installed_by || "unknown"}
                    </CardDescription>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Installed {formatTimestamp(installation.created_at)}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {buildReferenceBadges(installation).length > 0 ? (
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      Current Usage
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {buildReferenceBadges(installation).map((badge) => (
                        <Badge
                          key={`${installation.id}-${badge.label}`}
                          variant={badge.tone === "provider" ? "default" : "outline"}
                          className="font-normal"
                        >
                          {badge.label} {badge.count}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ) : null}

                {buildContributionGroups(installation.contribution_summary).map((group) => (
                  <div key={`${installation.id}-${group.label}`}>
                    <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {group.label}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {group.values.map((value) => (
                        <Badge
                          key={`${installation.id}-${group.label}-${value}`}
                          variant={getContributionBadgeVariant(group.tone)}
                          className="font-normal"
                        >
                          {value}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="hook-replay">
          <ExtensionHookReplayPanel packageId={pkg.package_id} />
        </TabsContent>
      </Tabs>

      <ConfirmationModal
        isOpen={pendingUninstall !== null}
        title="Uninstall Extension Version"
        message={
          pendingUninstall
            ? [
                `${pendingUninstall.display_name} ${pendingUninstall.version}`,
                "If this version is still referenced by bindings, releases, snapshots, or drafts,",
                "Pivot will disable it instead of removing it physically.",
              ].join(" ")
            : ""
        }
        confirmText={isLatestUninstalling ? "Uninstalling…" : "Uninstall"}
        onConfirm={() => {
          if (pendingUninstall) {
            void handleConfirmUninstall(pendingUninstall);
          }
        }}
        onCancel={() => {
          if (!isLatestUninstalling) {
            setPendingUninstall(null);
          }
        }}
      />
    </div>
  );
}
