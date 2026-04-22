import { useCallback, useEffect, useMemo, useState } from 'react';
import { ExternalLink, Search, X } from "@/lib/lucide";
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
  ProviderMetadataBadges,
} from '@/components/ProviderMetadataBadges';
import StaggeredFadeInList from '@/components/StaggeredFadeInList';
import { getChannels, type ChannelCatalogItem, type ChannelManifest } from '@/utils/api';
import {
  formatProviderExtensionLabel,
  formatProviderVisibilityLabel,
} from '@/utils/providerMetadata';

const PAGE_SIZE = 6;

const CHANNEL_ICON_PATHS: Record<string, string> = {
  work_wechat: '/work-wechat.svg',
  feishu: '/feishu.svg',
  telegram: '/telegram.svg',
  dingtalk: '/dingtalk.svg',
};

type TransportFilter = 'all' | 'webhook' | 'websocket' | 'polling';
type SourceFilter = 'all' | 'builtin' | 'extension';

/**
 * Build the page number list with ellipsis slots for a given total/current.
 */
function buildPageList(current: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages: (number | 'ellipsis')[] = [1];
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

/**
 * Resolve the public asset path for one built-in channel icon.
 * Why: brand assets in web/public keep this catalog visually aligned with the providers users recognize.
 */
function getChannelIconPath(channelKey: string): string | null {
  return CHANNEL_ICON_PATHS[channelKey] ?? null;
}

/**
 * Normalize manifest transport labels for badge text.
 */
function formatTransportLabel(transportMode: ChannelManifest['transport_mode']): string {
  switch (transportMode) {
    case 'webhook':
      return 'Webhook';
    case 'websocket':
      return 'WebSocket';
    case 'polling':
      return 'Polling';
    default:
      return transportMode;
  }
}

/**
 * Channel provider catalog page.
 * Mirrors the header, filter, and search layout used by the other top-level lists.
 */
function ChannelsPage() {
  const [channels, setChannels] = useState<ChannelCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [transportFilter, setTransportFilter] = useState<TransportFilter>('all');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [currentPage, setCurrentPage] = useState(1);

  const loadChannels = useCallback(async () => {
    setIsLoading(true);
    try {
      const nextChannels = await getChannels();
      setChannels(nextChannels);
    } catch {
      toast.error('Failed to load channels');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadChannels();
  }, [loadChannels]);

  const manifests = useMemo(() => channels.map(({ manifest }) => manifest), [channels]);

  const filteredChannels = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    return manifests.filter((manifest) => {
      if (transportFilter !== 'all' && manifest.transport_mode !== transportFilter) {
        return false;
      }
      if (sourceFilter !== 'all' && manifest.visibility !== sourceFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      return (
        manifest.name.toLowerCase().includes(query)
        || manifest.description.toLowerCase().includes(query)
        || manifest.transport_mode.toLowerCase().includes(query)
        || formatProviderVisibilityLabel(manifest.visibility).toLowerCase().includes(query)
        || manifest.capabilities.some((capability) => capability.toLowerCase().includes(query))
      );
    });
  }, [manifests, searchQuery, sourceFilter, transportFilter]);

  const transportCounts = useMemo(
    () => ({
      all: manifests.length,
      webhook: manifests.filter((manifest) => manifest.transport_mode === 'webhook').length,
      websocket: manifests.filter((manifest) => manifest.transport_mode === 'websocket').length,
      polling: manifests.filter((manifest) => manifest.transport_mode === 'polling').length,
    }),
    [manifests]
  );

  const sourceCounts = useMemo(
    () => ({
      all: manifests.length,
      builtin: manifests.filter((manifest) => manifest.visibility !== 'extension').length,
      extension: manifests.filter((manifest) => manifest.visibility === 'extension').length,
    }),
    [manifests]
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, sourceFilter, transportFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredChannels.length / PAGE_SIZE));

  const pagedChannels = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredChannels.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredChannels]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Channels</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Browse installed channel providers, including built-in and extension-backed delivery surfaces.
          </p>
        </div>
      </div>

      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap">
            {(
              [
                { value: 'all', label: 'All', count: transportCounts.all },
                { value: 'webhook', label: 'Webhook', count: transportCounts.webhook },
                { value: 'websocket', label: 'WebSocket', count: transportCounts.websocket },
                { value: 'polling', label: 'Polling', count: transportCounts.polling },
              ] as const
            ).map(({ value, label, count }) => (
              <button
                key={value}
                onClick={() => setTransportFilter(value)}
                className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
              >
                <Badge
                  variant={transportFilter === value ? 'default' : 'outline'}
                  className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                    transportFilter === value ? 'list-filter-badge-active' : ''
                  }`}
                >
                  {label}
                  <span className={transportFilter === value ? 'opacity-70' : 'text-muted-foreground'}>
                    {count}
                  </span>
                </Badge>
              </button>
            ))}
            {transportFilter !== 'all' && (
              <button
                onClick={() => setTransportFilter('all')}
                className="text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Clear transport filter"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <ButtonGroup className="list-search-group">
            <Input
              placeholder="Search by provider, transport, source, or capability…"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              aria-label="Search channels"
              autoComplete="off"
            />
            <Button variant="outline" size="sm" aria-label="Search channels" tabIndex={-1}>
              <Search className="w-4 h-4" />
              Search
            </Button>
          </ButtonGroup>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {(
            [
              { value: 'all', label: 'All Sources', count: sourceCounts.all },
              { value: 'builtin', label: 'Built-in', count: sourceCounts.builtin },
              { value: 'extension', label: 'Extension', count: sourceCounts.extension },
            ] as const
          ).map(({ value, label, count }) => (
            <button
              key={value}
              onClick={() => setSourceFilter(value)}
              className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
            >
              <Badge
                variant={sourceFilter === value ? 'default' : 'outline'}
                className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                  sourceFilter === value ? 'list-filter-badge-active' : ''
                }`}
              >
                {label}
                <span className={sourceFilter === value ? 'opacity-70' : 'text-muted-foreground'}>
                  {count}
                </span>
              </Badge>
            </button>
          ))}
          {sourceFilter !== 'all' && (
            <button
              onClick={() => setSourceFilter('all')}
              className="text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Clear source filter"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">Loading channels…</div>
      ) : filteredChannels.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
          <p className="text-sm">
            {manifests.length === 0 ? 'No channels found.' : 'No channels match your search.'}
          </p>
        </div>
      ) : (
        <>
          <StaggeredFadeInList
            items={pagedChannels}
            getItemKey={(manifest) => manifest.key}
            className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
            itemClassName="h-full"
            renderItem={(manifest) => <ChannelCard manifest={manifest} />}
          />

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {filteredChannels.length} channel{filteredChannels.length !== 1 ? 's' : ''}
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
  );
}

interface ChannelCardProps {
  manifest: ChannelManifest;
}

/**
 * Presentation card for one channel manifest.
 */
function ChannelCard({ manifest }: ChannelCardProps) {
  const iconPath = getChannelIconPath(manifest.key);
  const extensionLabel = formatProviderExtensionLabel(
    manifest.extension_display_name,
    manifest.extension_name,
    manifest.extension_version,
  );

  return (
    <Card className="h-full border-border/70">
        <CardHeader className="space-y-3">
          <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10">
              {iconPath ? (
                <img
                  src={iconPath}
                  alt={`${manifest.name} logo`}
                  className="h-5 w-5"
                  loading="lazy"
                />
              ) : (
                <span className="text-sm font-semibold text-primary">
                  {manifest.name.slice(0, 1)}
                </span>
              )}
            </div>
            <div className="min-w-0">
              <CardTitle className="text-base truncate">{manifest.name}</CardTitle>
              <CardDescription className="mt-0.5">
                {formatTransportLabel(manifest.transport_mode)}
              </CardDescription>
            </div>
          </div>
          <Button asChild size="sm" variant="outline" className="shrink-0">
            <a href={manifest.docs_url} target="_blank" rel="noreferrer">
              <ExternalLink className="h-3.5 w-3.5" />
              Docs
            </a>
          </Button>
        </div>
        <ProviderMetadataBadges
          visibility={manifest.visibility}
          status={manifest.status}
        />
        {extensionLabel ? (
          <CardDescription className="text-xs">
            Package: {extensionLabel}
          </CardDescription>
        ) : null}
        <CardDescription className="leading-6">
          {manifest.description}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {manifest.capabilities.map((capability) => (
            <Badge key={capability} variant="outline" className="text-[11px]">
              {capability}
            </Badge>
          ))}
        </div>

      </CardContent>
    </Card>
  );
}

export default ChannelsPage;
