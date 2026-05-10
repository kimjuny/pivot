import { useCallback, useEffect, useMemo, useState } from "react";
import { Search, X } from "@/lib/lucide";
import { toast } from "sonner";

import StaggeredFadeInList from "@/components/StaggeredFadeInList";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import {
  getMediaGenerationProviders,
  type MediaProviderCatalogItem,
  type MediaProviderManifest,
} from "@/utils/api";
import { Link } from "react-router-dom";

const PAGE_SIZE = 6;

type MediaTypeFilter = "all" | "image" | "video";

/**
 * Build the page number list with ellipsis slots for a given total/current.
 */
function buildPageList(current: number, total: number): (number | "ellipsis")[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  const pages: (number | "ellipsis")[] = [1];
  if (current > 3) {
    pages.push("ellipsis");
  }
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let index = start; index <= end; index += 1) {
    pages.push(index);
  }
  if (current < total - 2) {
    pages.push("ellipsis");
  }
  pages.push(total);
  return pages;
}

/**
 * Workspace-level catalog for media-generation providers.
 */
function MediaGenerationProvidersPage() {
  const [providers, setProviders] = useState<MediaProviderCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [mediaTypeFilter, setMediaTypeFilter] = useState<MediaTypeFilter>("all");
  const [currentPage, setCurrentPage] = useState(1);

  const loadProviders = useCallback(async () => {
    setIsLoading(true);
    try {
      const nextProviders = await getMediaGenerationProviders();
      setProviders(nextProviders);
    } catch {
      toast.error("Failed to load media providers");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  const manifests = useMemo(
    () => providers.map(({ manifest }) => manifest),
    [providers],
  );

  const filteredProviders = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    return manifests.filter((manifest) => {
      if (mediaTypeFilter !== "all" && manifest.media_type !== mediaTypeFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      return (
        manifest.name.toLowerCase().includes(query)
        || manifest.description.toLowerCase().includes(query)
        || manifest.supported_operations.some((item) => item.toLowerCase().includes(query))
        || manifest.supported_parameters.some((item) => item.toLowerCase().includes(query))
        || manifest.media_type.toLowerCase().includes(query)
      );
    });
  }, [manifests, searchQuery, mediaTypeFilter]);

  const mediaTypeCounts = useMemo(
    () => ({
      all: manifests.length,
      image: manifests.filter((m) => m.media_type === "image").length,
      video: manifests.filter((m) => m.media_type === "video").length,
    }),
    [manifests],
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, mediaTypeFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredProviders.length / PAGE_SIZE));

  const pagedProviders = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredProviders.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredProviders]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Media Providers</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Review installed media-generation providers before binding them to specific agents.
          </p>
        </div>
      </div>

      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-1.5 flex-wrap">
          {(
            [
              { value: "all", label: "All", count: mediaTypeCounts.all },
              { value: "image", label: "Image", count: mediaTypeCounts.image },
              { value: "video", label: "Video", count: mediaTypeCounts.video },
            ] as const
          ).map(({ value, label, count }) => (
            <button
              key={value}
              onClick={() => setMediaTypeFilter(value)}
              className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
            >
              <Badge
                variant={mediaTypeFilter === value ? "default" : "outline"}
                className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                  mediaTypeFilter === value ? "list-filter-badge-active" : ""
                }`}
              >
                {label}
                <span className={mediaTypeFilter === value ? "opacity-70" : "text-muted-foreground"}>
                  {count}
                </span>
              </Badge>
            </button>
          ))}
          {mediaTypeFilter !== "all" && (
            <button
              onClick={() => setMediaTypeFilter("all")}
              className="text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Clear media type filter"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        <ButtonGroup className="list-search-group">
          <Input
            placeholder="Search by provider, operation, or parameter…"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            aria-label="Search media providers"
            autoComplete="off"
          />
          <Button
            variant="outline"
            size="sm"
            aria-label="Search media providers"
            tabIndex={-1}
          >
            <Search className="w-4 h-4" />
            Search
          </Button>
        </ButtonGroup>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
          Loading media providers…
        </div>
      ) : filteredProviders.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
          <p className="text-sm">
            {manifests.length === 0
              ? "No media providers found."
              : "No media providers match your search."}
          </p>
        </div>
      ) : (
        <>
          <StaggeredFadeInList
            items={pagedProviders}
            getItemKey={(manifest) => manifest.key}
            className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
            itemClassName="h-full"
            renderItem={(manifest) => <MediaProviderCard manifest={manifest} />}
          />

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {filteredProviders.length} provider{filteredProviders.length !== 1 ? "s" : ""}
                {searchQuery ? " found" : " total"}
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
                      className={currentPage === 1 ? "pointer-events-none opacity-50" : ""}
                    />
                  </PaginationItem>

                  {buildPageList(currentPage, totalPages).map((page, index) => (
                    page === "ellipsis" ? (
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
                      className={currentPage >= totalPages ? "pointer-events-none opacity-50" : ""}
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

interface MediaProviderCardProps {
  manifest: MediaProviderManifest;
}

/**
 * Presentation card for one media-generation provider manifest.
 */
function MediaProviderCard({ manifest }: MediaProviderCardProps) {
  return (
    <Card className="h-full border-border/70">
      <CardHeader className="space-y-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            {manifest.logo_url ? (
              <img
                src={manifest.logo_url}
                alt={`${manifest.name} logo`}
                className="size-full rounded-lg object-cover"
                loading="lazy"
              />
            ) : (
              <span className="text-sm font-semibold text-primary">
                {manifest.name.slice(0, 1)}
              </span>
            )}
          </div>
          <div className="min-w-0 space-y-0.5">
            <CardTitle className="text-base truncate">{manifest.name}</CardTitle>
            {manifest.extension_name ? (
              <Link to={`/studio/assets/extensions/${manifest.extension_name.replace(/^@/, "")}`}>
                <Badge variant="secondary" className="text-[10px] font-mono cursor-pointer hover:bg-secondary/80">
                  {manifest.extension_name}
                </Badge>
              </Link>
            ) : null}
          </div>
        </div>
        <CardDescription className="leading-6">
          {manifest.description}{" "}
          <a
            href={manifest.docs_url}
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline"
          >
            Learn more
          </a>
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

export default MediaGenerationProvidersPage;
