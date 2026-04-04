import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { ArrowLeft, Server } from "@/lib/lucide";
import { toast } from "sonner";

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
  updateExtensionInstallationConfiguration,
  type ExtensionConfigurationField,
  type ExtensionContributionSummary,
  type ExtensionInstallation,
  type ExtensionInstallationConfigurationState,
  type ExtensionPackage,
} from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";
import { MarkdownRenderer } from "@/pages/chat/components/MarkdownRenderer";

interface ContributionGroup {
  /** Human-readable group title shown in Overview and Versions. */
  label: string;
  /** Contribution names or provider keys displayed as badges. */
  values: string[];
  /** Visual emphasis for providers vs optional lightweight assets. */
  tone: "provider" | "lightweight";
}

interface PackageStatusBadge {
  /** Operator-facing summary label. */
  label: string;
  /** Visual tone that distinguishes live usage from neutral state. */
  tone: "provider" | "runtime" | "neutral";
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
 * Why: providers are the standardized package path, while tools and skills are
 * optional lightweight additions. Showing them separately keeps that product
 * boundary visible in the package detail page.
 */
function buildContributionGroups(summary: ExtensionContributionSummary): ContributionGroup[] {
  const groups: ContributionGroup[] = [
    {
      label: "Channel Providers",
      values: summary.channel_providers,
      tone: "provider",
    },
    {
      label: "Web Search Providers",
      values: summary.web_search_providers,
      tone: "provider",
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
 * Summarize package-level operational risk from every installed version.
 *
 * Why: the detail header should immediately tell operators whether the package
 * is active, pinned, or safe to disable before they inspect individual
 * versions.
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
  if (totalBindingCount === 0 && totalPinnedCount === 0) {
    badges.push({
      label: pkg.active_version_count > 0 ? "Safe To Disable" : "Inactive",
      tone: "neutral",
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
  const [packages, setPackages] = useState<ExtensionPackage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [setupStates, setSetupStates] = useState<SetupStateMap>({});
  const [setupDrafts, setSetupDrafts] = useState<SetupDraftMap>({});
  const [loadingSetupIds, setLoadingSetupIds] = useState<number[]>([]);
  const [savingSetupIds, setSavingSetupIds] = useState<number[]>([]);
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
  const aggregatedContributions = useMemo(() => {
    if (!pkg) {
      return [];
    }
    const merged = {
      channel_providers: Array.from(
        new Set(pkg.versions.flatMap((version) => version.contribution_summary.channel_providers)),
      ),
      web_search_providers: Array.from(
        new Set(pkg.versions.flatMap((version) => version.contribution_summary.web_search_providers)),
      ),
      tools: Array.from(new Set(pkg.versions.flatMap((version) => version.contribution_summary.tools))),
      skills: Array.from(new Set(pkg.versions.flatMap((version) => version.contribution_summary.skills))),
    };
    return buildContributionGroups(merged);
  }, [pkg]);

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
      <div className="mb-6">
        <Button asChild variant="ghost" className="mb-3 -ml-3">
          <Link to={listPath}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back To Extensions
          </Link>
        </Button>

        <Card>
          <CardHeader className="space-y-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <ExtensionLogoAvatar
                    name={pkg.display_name}
                    logoUrl={pkg.logo_url ?? latestInstallation?.logo_url ?? null}
                    fallback={<Server className="h-6 w-6 text-primary" aria-hidden="true" />}
                    containerClassName="flex size-12 items-center justify-center rounded-xl border border-border bg-muted/40"
                    imageClassName="size-full rounded-xl object-cover"
                  />
                  <div>
                    <CardTitle className="text-2xl">{pkg.display_name}</CardTitle>
                    <CardDescription className="mt-1 text-sm">
                      {pkg.description || "No description provided."}
                    </CardDescription>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">{pkg.package_id}</Badge>
                  <Badge variant="outline">Latest {pkg.latest_version}</Badge>
                  <Badge variant="outline">Active {pkg.active_version_count}</Badge>
                  <Badge variant="outline">Disabled {pkg.disabled_version_count}</Badge>
                  {buildPackageStatusBadges(pkg).map((badge) => (
                    <Badge
                      key={`${pkg.package_id}-${badge.label}`}
                      variant={badge.tone === "neutral" ? "outline" : "default"}
                    >
                      {badge.label}
                    </Badge>
                  ))}
                </div>
              </div>

              <div className="rounded-xl border border-border bg-muted/20 px-4 py-3 text-sm">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Current Package Status
                </div>
                <div className="mt-2 space-y-1 text-muted-foreground">
                  <div>Scope: <code>{pkg.scope}</code></div>
                  <div>Name: <code>{pkg.name}</code></div>
                  <div>Installed versions: {pkg.versions.length}</div>
                  <div>
                    Latest trust:{" "}
                    <span className="text-foreground">
                      {latestInstallation
                        ? formatTrustStatusLabel(latestInstallation.trust_status)
                        : "Unknown"}
                    </span>
                  </div>
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
            <Card>
              <CardContent className="pt-6">
                <MarkdownRenderer content={pkg.readme_markdown} variant="document" />
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Includes</CardTitle>
              <CardDescription>
                Package-level contribution summary across all installed versions.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {aggregatedContributions.length > 0 ? (
                aggregatedContributions.map((group) => (
                  <div key={group.label}>
                    <div className="text-sm font-medium text-foreground">{group.label}</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {group.values.map((value) => (
                        <Badge
                          key={`${group.label}-${value}`}
                          variant={group.tone === "provider" ? "default" : "outline"}
                          className="font-normal"
                        >
                          {value}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-muted-foreground">No contributions declared.</div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Information</CardTitle>
              <CardDescription>
                Stable package metadata and the most recent installed version summary.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
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
                          variant={group.tone === "provider" ? "default" : "outline"}
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
    </div>
  );
}
