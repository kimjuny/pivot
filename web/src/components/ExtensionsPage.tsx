import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { Link, useLocation } from "react-router-dom";

import { Download, Search, Server, Upload, X } from "@/lib/lucide";
import { toast } from 'sonner';

import ConfirmationModal from './ConfirmationModal';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
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
  getExtensionInstallationReferences,
  getExtensionPackages,
  importExtensionBundle,
  previewExtensionBundle,
  uninstallExtensionInstallation,
  updateExtensionInstallationStatus,
  type ExtensionContributionSummary,
  type ExtensionImportPreview,
  type ExtensionInstallation,
  type ExtensionPackage,
  type ExtensionReferenceSummary,
} from '@/utils/api';
import { formatTimestamp } from '@/utils/timestamp';

const PAGE_SIZE = 6;

interface PendingUninstallState {
  installation: ExtensionInstallation;
  references: ExtensionReferenceSummary;
}

interface PendingImportState {
  files: File[];
  preview: ExtensionImportPreview;
}

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
  tone: 'provider' | 'lightweight';
}

interface ReferenceBadge {
  label: string;
  count: number;
  tone: 'provider' | 'runtime';
}

interface PackageStatusBadge {
  label: string;
  tone: 'provider' | 'runtime' | 'neutral';
}

/**
 * Build stable contribution groups for one installed extension version.
 *
 * Why: provider contributions are the primary package-level integration path,
 * while tools and skills remain optional lightweight additions. Grouping them
 * explicitly keeps that distinction visible in the UI.
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
      label: 'Web Search Providers',
      values: summary.web_search_providers,
      tone: 'provider',
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

/**
 * Build visible usage badges for one installed version.
 *
 * Why: extension operators should be able to see whether a provider package is
 * currently wired into live agent bindings before they attempt a disable or
 * uninstall action.
 */
function buildReferenceBadges(
  installation: ExtensionInstallation,
): ReferenceBadge[] {
  const summary = installation.reference_summary;
  if (!summary) {
    return [];
  }

  const badges: ReferenceBadge[] = [
    {
      label: 'Extension Bindings',
      count: summary.extension_binding_count,
      tone: 'runtime',
    },
    {
      label: 'Channel Bindings',
      count: summary.channel_binding_count,
      tone: 'provider',
    },
    {
      label: 'Web Search Bindings',
      count: summary.web_search_binding_count,
      tone: 'provider',
    },
    {
      label: 'Releases',
      count: summary.release_count,
      tone: 'runtime',
    },
    {
      label: 'Test Snapshots',
      count: summary.test_snapshot_count,
      tone: 'runtime',
    },
    {
      label: 'Saved Drafts',
      count: summary.saved_draft_count,
      tone: 'runtime',
    },
  ];
  return badges.filter((badge) => badge.count > 0);
}

/**
 * Build package-level risk badges from all installed versions.
 *
 * Why: operators first choose whether a package is safe to touch at all, then
 * drill into the version cards to inspect the exact source of those references.
 */
function buildPackageStatusBadges(
  pkg: ExtensionPackage,
): PackageStatusBadge[] {
  const totalBindingCount = pkg.versions.reduce(
    (sum, version) => sum + (version.reference_summary?.binding_count ?? 0),
    0,
  );
  const totalPinnedCount = pkg.versions.reduce(
    (sum, version) => sum + (
      (version.reference_summary?.release_count ?? 0)
      + (version.reference_summary?.test_snapshot_count ?? 0)
      + (version.reference_summary?.saved_draft_count ?? 0)
    ),
    0,
  );

  const badges: PackageStatusBadge[] = [];
  if (totalBindingCount > 0) {
    badges.push({
      label: `In Use ${totalBindingCount}`,
      tone: 'provider',
    });
  }
  if (totalPinnedCount > 0) {
    badges.push({
      label: `Pinned ${totalPinnedCount}`,
      tone: 'runtime',
    });
  }
  if (totalBindingCount === 0 && totalPinnedCount === 0) {
    badges.push({
      label: pkg.active_version_count > 0 ? 'Safe To Disable' : 'Inactive',
      tone: 'neutral',
    });
  }
  return badges;
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

/**
 * Global Extensions inventory page.
 * Why: package installation and lifecycle operations belong at the workspace
 * level, while agent sidebars only handle per-agent bindings.
 */
function ExtensionsPage() {
  const location = useLocation();
  const [packages, setPackages] = useState<ExtensionPackage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [isImporting, setIsImporting] = useState(false);
  const [isPreviewingImport, setIsPreviewingImport] = useState(false);
  const [pendingImport, setPendingImport] = useState<PendingImportState | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<PendingUninstallState | null>(null);
  const [isUninstalling, setIsUninstalling] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const detailBasePath = location.pathname.startsWith("/studio/")
    ? "/studio/assets/extensions"
    : "/extensions";

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

  const filteredPackages = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) {
      return packages;
    }
    return packages.filter((pkg) => {
      const versionText = pkg.versions.map((version) => version.version).join(' ');
      const contributionText = pkg.versions
        .flatMap((version) => [
          ...version.contribution_summary.channel_providers,
          ...version.contribution_summary.web_search_providers,
          ...version.contribution_summary.tools,
          ...version.contribution_summary.skills,
        ])
        .join(' ');
      return (
        pkg.display_name.toLowerCase().includes(query)
        || pkg.package_id.toLowerCase().includes(query)
        || pkg.description.toLowerCase().includes(query)
        || versionText.toLowerCase().includes(query)
        || contributionText.toLowerCase().includes(query)
      );
    });
  }, [packages, searchQuery]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

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

  const handleConfirmImport = async () => {
    if (!pendingImport) {
      return;
    }

    setIsImporting(true);
    try {
      await importExtensionBundle(pendingImport.files, { trustConfirmed: true });
      toast.success('Extension imported');
      setPendingImport(null);
      await loadPackages();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to import extension',
      );
    } finally {
      setIsImporting(false);
    }
  };

  const handleStatusToggle = async (
    installation: ExtensionInstallation,
  ) => {
    const nextStatus = installation.status === 'active' ? 'disabled' : 'active';
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
          ? 'Extension version uninstalled'
          : 'Extension version disabled because it is still referenced',
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

  return (
    <>
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-foreground">Extensions</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Import, inspect, and operate extension packages before binding them to agents.
            </p>
            <p className="text-xs text-muted-foreground mt-2">
              Open one package for version details, included contributions, and package-scoped
              hook replay. Operations still remains the session-first debugging entrypoint.
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
            >
              {isImporting || isPreviewingImport ? (
                <Download className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Upload className="mr-2 h-4 w-4" />
              )}
              {isPreviewingImport ? 'Inspecting…' : isImporting ? 'Installing…' : 'Import Folder'}
            </Button>
          </div>
        </div>

        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="text-xs text-muted-foreground">
            {packages.length} package{packages.length !== 1 ? 's' : ''} installed
          </div>
          <ButtonGroup className="list-search-group">
            <Input
              placeholder="Search by package, description, or version…"
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
          <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
            Loading extensions…
          </div>
        ) : filteredPackages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
            <p className="text-sm">
              {packages.length === 0 ? 'No extensions installed yet.' : 'No extensions match your search.'}
            </p>
          </div>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {pagedPackages.map((pkg) => (
                <ExtensionPackageCard
                  key={pkg.package_id}
                  pkg={pkg}
                  detailBasePath={detailBasePath}
                  onStatusToggle={handleStatusToggle}
                  onPromptUninstall={handlePromptUninstall}
                />
              ))}
            </div>

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
          if (!open && !isImporting) {
            setPendingImport(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Trust Extension</DialogTitle>
            <DialogDescription>
              Local imports can claim any scope in <code>manifest.json</code>. Pivot will only
              treat the package as trusted after you explicitly approve this install.
            </DialogDescription>
          </DialogHeader>

          {pendingImport ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-border bg-muted/30 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-foreground">
                    {pendingImport.preview.display_name}
                  </span>
                  <Badge variant="outline">{pendingImport.preview.package_id}</Badge>
                  <Badge variant="outline">{pendingImport.preview.version}</Badge>
                  <Badge variant="outline">
                    {formatTrustStatusLabel(pendingImport.preview.trust_status)}
                  </Badge>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {pendingImport.preview.description || 'No description provided.'}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Claimed scope: <code>{pendingImport.preview.scope}</code>
                  {' · '}
                  Source: <code>{pendingImport.preview.source}</code>
                  {' · '}
                  Manifest hash: <code>{pendingImport.preview.manifest_hash}</code>
                </p>
              </div>

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
                              <Badge key={`${group.label}-${value}`} variant="outline">
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
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPendingImport(null)}
              disabled={isImporting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleConfirmImport()}
              disabled={isImporting}
            >
              {isImporting ? 'Installing…' : 'Trust and Install'}
            </Button>
          </DialogFooter>
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
}

/**
 * Render one installed extension package card with version-level operations.
 */
function ExtensionPackageCard({
  pkg,
  detailBasePath,
  onStatusToggle,
  onPromptUninstall,
}: ExtensionPackageCardProps) {
  const detailPath = `${detailBasePath}/${pkg.scope}/${pkg.name}`;
  return (
    <Card className="h-full">
      <CardHeader className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="h-4 w-4 text-primary" />
              <Link
                to={detailPath}
                className="truncate transition-colors hover:text-primary"
              >
                {pkg.display_name}
              </Link>
            </CardTitle>
            <CardDescription className="mt-1 break-words">
              {pkg.description || 'No description provided.'}
            </CardDescription>
          </div>
          <Badge variant="outline">{pkg.latest_version}</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">Active {pkg.active_version_count}</Badge>
          <Badge variant="outline">Disabled {pkg.disabled_version_count}</Badge>
          {buildPackageStatusBadges(pkg).map((badge) => (
            <Badge
              key={`${pkg.package_id}-${badge.label}`}
              variant={badge.tone === 'neutral' ? 'outline' : 'default'}
            >
              {badge.label}
            </Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex justify-end">
          <Button asChild size="sm" variant="outline">
            <Link to={detailPath}>Open Details</Link>
          </Button>
        </div>
        {pkg.versions.map((installation) => (
          <div
            key={installation.id}
            className="rounded-lg border border-border px-3 py-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-foreground">
                    {installation.version}
                  </span>
                  <Badge
                    variant={installation.status === 'active' ? 'default' : 'outline'}
                  >
                    {installation.status}
                  </Badge>
                  <Badge variant="outline">
                    {formatTrustStatusLabel(installation.trust_status)}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {installation.source}
                  {' · '}
                  {installation.trust_source}
                  {' · '}
                  {installation.installed_by || 'unknown'}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Installed {formatTimestamp(installation.created_at)}
                </div>
                {buildReferenceBadges(installation).length > 0 && (
                  <div className="mt-3">
                    <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      Current Usage
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {buildReferenceBadges(installation).map((badge) => (
                        <Badge
                          key={`${installation.id}-${badge.label}`}
                          variant={badge.tone === 'provider' ? 'default' : 'outline'}
                          className="font-normal"
                        >
                          {badge.label} {badge.count}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                <div className="mt-3 space-y-2">
                  {buildContributionGroups(installation.contribution_summary).map((group) => (
                    <div key={group.label}>
                      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                        {group.label}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {group.values.map((value) => (
                          <Badge
                            key={`${group.label}-${value}`}
                            variant={group.tone === 'provider' ? 'default' : 'outline'}
                            className="font-normal"
                          >
                            {value}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="flex flex-col items-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void onStatusToggle(installation);
                  }}
                >
                  {installation.status === 'active' ? 'Disable' : 'Enable'}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    void onPromptUninstall(installation);
                  }}
                  className="text-destructive hover:text-destructive"
                >
                  <X className="mr-1 h-3.5 w-3.5" />
                  Uninstall
                </Button>
              </div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export default ExtensionsPage;
