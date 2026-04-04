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
  Loader2,
  MoreHorizontal,
  Search,
  Server,
  Trash2,
  Upload,
  XCircle,
} from "@/lib/lucide";
import { toast } from 'sonner';

import ConfirmationModal from './ConfirmationModal';
import { ExtensionLogoAvatar } from '@/components/ExtensionLogoAvatar';
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
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card';
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
  const [packages, setPackages] = useState<ExtensionPackage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [isImporting, setIsImporting] = useState(false);
  const [isPreviewingImport, setIsPreviewingImport] = useState(false);
  const [pendingImport, setPendingImport] = useState<PendingImportState | null>(null);
  const [pendingUninstall, setPendingUninstall] = useState<PendingUninstallState | null>(null);
  const [isUninstalling, setIsUninstalling] = useState(false);
  const [statusUpdatingIds, setStatusUpdatingIds] = useState<number[]>([]);
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
      const shouldOverwrite = pendingImport.preview.requires_overwrite_confirmation;
      const reusesExisting = pendingImport.preview.identical_to_installed;
      await importExtensionBundle(pendingImport.files, {
        trustConfirmed: true,
        overwriteConfirmed: shouldOverwrite,
      });
      toast.success(
        shouldOverwrite
          ? 'Extension version overwritten'
          : reusesExisting
            ? 'Existing extension version reused'
            : 'Extension imported',
      );
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
            <div className="grid gap-4 md:grid-cols-2">
              {pagedPackages.map((pkg) => (
                <ExtensionPackageCard
                  key={pkg.package_id}
                  pkg={pkg}
                  detailBasePath={detailBasePath}
                  onStatusToggle={handleStatusToggle}
                  onPromptUninstall={handlePromptUninstall}
                  isStatusUpdating={statusUpdatingIds.includes(
                    getMostRecentInstallation(pkg)?.id ?? -1,
                  )}
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

              {pendingImport.preview.identical_to_installed ? (
                <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
                  This exact package version is already installed. Confirming this import will
                  reuse the existing installation instead of replacing files.
                </div>
              ) : null}

              {pendingImport.preview.requires_overwrite_confirmation ? (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-foreground">
                  A different payload is already installed at{' '}
                  <code>{pendingImport.preview.package_id}@{pendingImport.preview.version}</code>.
                  Confirming this import will replace that installed version because it currently
                  has no bindings, releases, test snapshots, or saved drafts referencing it.
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
              disabled={isImporting || pendingImport?.preview.overwrite_blocked_reason !== ''}
            >
              {isImporting
                ? 'Installing…'
                : pendingImport?.preview.requires_overwrite_confirmation
                  ? 'Trust and Overwrite'
                  : pendingImport?.preview.identical_to_installed
                    ? 'Trust and Reuse Existing'
                    : 'Trust and Install'}
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
          containerClassName="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"
          imageClassName="size-full rounded-xl object-cover"
        />

        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex h-10 flex-col justify-between">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-sm font-medium leading-[1.1rem] text-foreground">
                  {pkg.display_name}
                </span>
                <span className="shrink-0 text-[11px] leading-[1.1rem] text-muted-foreground">
                  by {pkg.scope}
                </span>
              </div>
              <HoverCard openDelay={150} closeDelay={100}>
                <HoverCardTrigger asChild>
                  <p className="line-clamp-1 text-[11px] leading-[1.1rem] text-muted-foreground">
                    {pkg.description || 'No description provided.'}
                  </p>
                </HoverCardTrigger>
                <HoverCardContent
                  align="start"
                  className="w-80"
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className="space-y-2">
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Description
                    </div>
                    <p className="text-sm leading-6 text-foreground">
                      {pkg.description || 'No description provided.'}
                    </p>
                  </div>
                </HoverCardContent>
              </HoverCard>
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
            <Badge variant="default" className="h-4 px-1.5 py-0 text-[10px]">
              v{pkg.latest_version}
            </Badge>
            <Badge
              variant="outline"
              className="h-4 border-emerald-500/30 px-1.5 py-0 text-[10px] text-emerald-700 dark:text-emerald-300"
            >
              Enabled {pkg.active_version_count}
            </Badge>
            <Badge
              variant="outline"
              className="h-4 border-amber-500/30 px-1.5 py-0 text-[10px] text-amber-700 dark:text-amber-300"
            >
              Disabled {pkg.disabled_version_count}
            </Badge>
            {pkg.versions.length > 1 ? (
              <Badge variant="outline" className="h-4 px-1.5 py-0 text-[10px]">
                {pkg.versions.length} versions
              </Badge>
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default ExtensionsPage;
