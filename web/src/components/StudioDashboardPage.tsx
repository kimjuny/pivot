import { AlertCircle } from "@/lib/lucide";

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

/**
 * Temporary Studio dashboard placeholder.
 *
 * Why: the dashboard will later become the workspace statistics and overview
 * surface, but for now we only want a clear "under construction" state instead
 * of a misleading aggregation page.
 */
function StudioDashboardPage() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-8">
      <div>
        <Badge variant="outline" className="w-fit">
          Studio
        </Badge>
        <h1 className="mt-3 text-xl font-semibold text-foreground">
          Dashboard
        </h1>
        <p className="mt-0.5 max-w-3xl text-sm leading-6 text-muted-foreground">
          This page is under construction. Workspace metrics, quality signals,
          and operating statistics will live here later.
        </p>
      </div>

      <Card className="border-border/70">
        <CardHeader className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <AlertCircle className="h-4 w-4" />
            <span>Under Construction</span>
          </div>
          <CardTitle className="text-sm font-semibold">
            Dashboard metrics are not available yet
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm leading-6 text-muted-foreground">
          We will use this page for Studio-level reporting in a later pass,
          including activity, runtime health, release quality, and usage trends.
        </CardContent>
      </Card>
    </div>
  );
}

export default StudioDashboardPage;
