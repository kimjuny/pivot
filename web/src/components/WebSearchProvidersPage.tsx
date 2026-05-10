import { useCallback, useEffect, useMemo, useState } from "react";
import { Globe, Search } from "lucide-react";
import { toast } from "sonner";

import StaggeredFadeInList from "@/components/StaggeredFadeInList";
import { Badge } from "@/components/ui/badge";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
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
  getWebSearchProviders,
  type WebSearchCatalogItem,
  type WebSearchProviderManifest,
} from "@/utils/api";
import { Link } from "react-router-dom";

const PAGE_SIZE = 6;

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
 * Workspace-level catalog for abstract web-search providers.
 */
function WebSearchProvidersPage() {
  const [providers, setProviders] = useState<WebSearchCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  const loadProviders = useCallback(async () => {
    setIsLoading(true);
    try {
      const nextProviders = await getWebSearchProviders();
      setProviders(nextProviders);
    } catch {
      toast.error("Failed to load web search providers");
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
      if (!query) {
        return true;
      }
      return (
        manifest.name.toLowerCase().includes(query)
        || manifest.description.toLowerCase().includes(query)
        || manifest.supported_parameters.some((item) => item.toLowerCase().includes(query))
      );
    });
  }, [manifests, searchQuery]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

  const totalPages = Math.max(1, Math.ceil(filteredProviders.length / PAGE_SIZE));

  const pagedProviders = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredProviders.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredProviders]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Web Search Providers</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Review installed abstract search providers before binding them to specific agents.
          </p>
        </div>
      </div>

      <div className="mb-4 flex justify-end">
        <ButtonGroup className="list-search-group">
          <Input
            placeholder="Search by provider or supported parameter…"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            aria-label="Search web search providers"
            autoComplete="off"
          />
          <Button
            variant="outline"
            size="sm"
            aria-label="Search web search providers"
            tabIndex={-1}
          >
            <Search className="w-4 h-4" />
            Search
          </Button>
        </ButtonGroup>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
          Loading web search providers…
        </div>
      ) : filteredProviders.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Globe className="size-6" />
            </EmptyMedia>
            {manifests.length === 0 ? (
              <>
                <EmptyTitle>No web search providers yet</EmptyTitle>
                <EmptyDescription>
                  Install an extension that provides web search.
                </EmptyDescription>
              </>
            ) : (
              <>
                <EmptyTitle>No web search providers found</EmptyTitle>
                <EmptyDescription>
                  No web search providers match your search.
                </EmptyDescription>
              </>
            )}
          </EmptyHeader>
          {manifests.length === 0 ? (
            <EmptyContent>
              <Button size="sm" variant="outline" asChild>
                <Link to="/studio/assets/extensions">Install Extension</Link>
              </Button>
            </EmptyContent>
          ) : null}
        </Empty>
      ) : (
        <>
          <StaggeredFadeInList
            items={pagedProviders}
            getItemKey={(manifest) => manifest.key}
            className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
            itemClassName="h-full"
            renderItem={(manifest) => <WebSearchProviderCard manifest={manifest} />}
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
                      className={currentPage === totalPages ? "pointer-events-none opacity-50" : ""}
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

interface WebSearchProviderCardProps {
  manifest: WebSearchProviderManifest;
}

/**
 * Presentation card for one web-search provider manifest.
 */
function WebSearchProviderCard({ manifest }: WebSearchProviderCardProps) {
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

export default WebSearchProvidersPage;
