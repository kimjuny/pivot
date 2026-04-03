import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { ArrowLeft, Server } from "@/lib/lucide";
import { toast } from "sonner";

import ExtensionHookReplayPanel from "@/components/ExtensionHookReplayPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getExtensionPackages, type ExtensionContributionSummary, type ExtensionPackage } from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

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
                  <div className="rounded-xl border border-border bg-muted/40 p-3">
                    <Server className="h-6 w-6 text-primary" />
                  </div>
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
        <TabsList className="grid h-auto w-full grid-cols-3">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
          <TabsTrigger value="hook-replay">Hook Replay</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
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
