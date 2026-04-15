import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, Search, X } from "@/lib/lucide";
import { toast } from "sonner";

import { ImageProviderBadge } from "@/components/ImageProviderBadge";
import { ProviderMetadataBadges } from "@/components/ProviderMetadataBadges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  getImageGenerationProviders,
  type ImageProviderCatalogItem,
  type ImageProviderManifest,
} from "@/utils/api";
import { formatProviderExtensionLabel } from "@/utils/providerMetadata";

const PAGE_SIZE = 6;

type SourceFilter = "all" | "builtin" | "extension";

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
 * Workspace-level catalog for image-generation providers.
 */
function ImageGenerationProvidersPage() {
  const [providers, setProviders] = useState<ImageProviderCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [currentPage, setCurrentPage] = useState(1);

  const loadProviders = useCallback(async () => {
    setIsLoading(true);
    try {
      const nextProviders = await getImageGenerationProviders();
      setProviders(nextProviders);
    } catch {
      toast.error("Failed to load image providers");
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
      if (sourceFilter !== "all" && manifest.visibility !== sourceFilter) {
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
        || manifest.visibility.toLowerCase().includes(query)
      );
    });
  }, [manifests, searchQuery, sourceFilter]);

  const sourceCounts = useMemo(
    () => ({
      all: manifests.length,
      builtin: manifests.filter((manifest) => manifest.visibility !== "extension").length,
      extension: manifests.filter((manifest) => manifest.visibility === "extension").length,
    }),
    [manifests],
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, sourceFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredProviders.length / PAGE_SIZE));

  const pagedProviders = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredProviders.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredProviders]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Image Providers</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Review installed image-generation providers before binding them to specific agents.
          </p>
        </div>
      </div>

      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-1.5 flex-wrap">
            {(
              [
                { value: "all", label: "All Sources", count: sourceCounts.all },
                { value: "builtin", label: "Built-in", count: sourceCounts.builtin },
                { value: "extension", label: "Extension", count: sourceCounts.extension },
              ] as const
            ).map(({ value, label, count }) => (
              <button
                key={value}
                onClick={() => setSourceFilter(value)}
                className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
              >
                <Badge
                  variant={sourceFilter === value ? "default" : "outline"}
                  className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                    sourceFilter === value ? "list-filter-badge-active" : ""
                  }`}
                >
                  {label}
                  <span className={sourceFilter === value ? "opacity-70" : "text-muted-foreground"}>
                    {count}
                  </span>
                </Badge>
              </button>
            ))}
            {sourceFilter !== "all" && (
              <button
                onClick={() => setSourceFilter("all")}
                className="text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Clear source filter"
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
              aria-label="Search image providers"
              autoComplete="off"
            />
            <Button
              variant="outline"
              size="sm"
              aria-label="Search image providers"
              tabIndex={-1}
            >
              <Search className="w-4 h-4" />
              Search
            </Button>
          </ButtonGroup>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
          Loading image providers…
        </div>
      ) : filteredProviders.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
          <p className="text-sm">
            {manifests.length === 0
              ? "No image providers found."
              : "No image providers match your search."}
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {pagedProviders.map((manifest) => (
              <ImageProviderCard key={manifest.key} manifest={manifest} />
            ))}
          </div>

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

interface ImageProviderCardProps {
  manifest: ImageProviderManifest;
}

/**
 * Presentation card for one image-generation provider manifest.
 */
function ImageProviderCard({ manifest }: ImageProviderCardProps) {
  const extensionLabel = formatProviderExtensionLabel(
    manifest.extension_display_name,
    manifest.extension_name,
    manifest.extension_version,
  );

  return (
    <Card className="h-full">
      <CardHeader className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base">
              <ImageProviderBadge name={manifest.name} />
            </CardTitle>
            <CardDescription className="mt-1">
              {manifest.description}
            </CardDescription>
          </div>
          <a
            href={manifest.docs_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
          >
            Docs
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <ProviderMetadataBadges
          visibility={manifest.visibility}
          status={manifest.status}
        />
      </CardHeader>
      <CardContent className="space-y-4">
        {extensionLabel ? (
          <div className="text-xs text-muted-foreground">
            Package: {extensionLabel}
          </div>
        ) : null}

        {manifest.supported_operations.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-foreground">Supported Operations</div>
            <div className="flex flex-wrap gap-1.5">
              {manifest.supported_operations.map((operation) => (
                <Badge key={operation} variant="secondary" className="text-[11px]">
                  {operation}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {manifest.supported_parameters.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-foreground">Supported Parameters</div>
            <div className="flex flex-wrap gap-1.5">
              {manifest.supported_parameters.map((parameter) => (
                <Badge key={parameter} variant="outline" className="text-[11px]">
                  {parameter}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ImageGenerationProvidersPage;
