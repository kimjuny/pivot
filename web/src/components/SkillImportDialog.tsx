import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  ExternalLink,
  Info,
  Loader2,
  Upload,
} from "@/lib/lucide";
import { toast } from 'sonner';

import type {
  GitHubSkillCandidate,
  GitHubSkillProbeResponse,
} from '@/utils/api';
import { importGitHubSkill, probeGitHubSkills } from '@/utils/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

type SkillVisibility = 'private' | 'shared';
type GitHubRefType = 'branch' | 'tag';

interface SkillImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existingSkillNames: Set<string>;
  onImported: () => Promise<void> | void;
}

interface RefOption {
  key: string;
  label: string;
}

function sanitizeSkillName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_.-]/g, '_')
    .replace(/^_+|_+$/g, '') || 'imported_skill';
}

function buildRefOptions(probe: GitHubSkillProbeResponse | null): RefOption[] {
  if (!probe) return [];

  return [
    ...probe.branches.map((name) => ({
      key: `branch:${name}`,
      label: `Branch · ${name}`,
    })),
    ...probe.tags.map((name) => ({
      key: `tag:${name}`,
      label: `Tag · ${name}`,
    })),
  ];
}

function buildSelectedRefKey(probe: GitHubSkillProbeResponse): string | null {
  if (probe.branches.includes(probe.selected_ref)) {
    return `branch:${probe.selected_ref}`;
  }
  if (probe.tags.includes(probe.selected_ref)) {
    return `tag:${probe.selected_ref}`;
  }
  if (probe.default_ref) {
    return `branch:${probe.default_ref}`;
  }
  return null;
}

function buildRefSummary(probe: GitHubSkillProbeResponse): string {
  return `Branches: ${probe.branches.length} · Tags: ${probe.tags.length}`;
}

function findCandidate(
  probe: GitHubSkillProbeResponse | null,
  directoryName: string
): GitHubSkillCandidate | null {
  if (!probe) return null;
  return probe.candidates.find((candidate) => candidate.directory_name === directoryName) ?? null;
}

/**
 * Dialog for probing and importing skills from a public repository source.
 *
 * The current implementation focuses on GitHub, but the title and framing stay
 * generic so we can extend the import flow to other hubs later.
 */
function SkillImportDialog({
  open,
  onOpenChange,
  existingSkillNames,
  onImported,
}: SkillImportDialogProps) {
  const [githubUrl, setGitHubUrl] = useState('');
  const [probeResult, setProbeResult] = useState<GitHubSkillProbeResponse | null>(null);
  const [selectedRefKey, setSelectedRefKey] = useState<string | null>(null);
  const [selectedDirectoryName, setSelectedDirectoryName] = useState('');
  const [skillName, setSkillName] = useState('');
  const [visibility, setVisibility] = useState<SkillVisibility>('private');
  const [isProbing, setIsProbing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [probeMessage, setProbeMessage] = useState<string | null>(null);

  const refOptions = useMemo(() => buildRefOptions(probeResult), [probeResult]);
  const effectiveSelectedRefKey = useMemo(
    () => selectedRefKey ?? (probeResult ? buildSelectedRefKey(probeResult) : null),
    [probeResult, selectedRefKey]
  );
  const selectedCandidate = useMemo(
    () => findCandidate(probeResult, selectedDirectoryName),
    [probeResult, selectedDirectoryName]
  );
  const trimmedSkillName = skillName.trim();
  const nameConflict = trimmedSkillName.length > 0 && existingSkillNames.has(trimmedSkillName);

  const resetState = useCallback(() => {
    setGitHubUrl('');
    setProbeResult(null);
    setSelectedRefKey(null);
    setSelectedDirectoryName('');
    setSkillName('');
    setVisibility('private');
    setProbeMessage(null);
    setIsProbing(false);
    setIsImporting(false);
  }, []);

  const applyProbeResult = useCallback((
    result: GitHubSkillProbeResponse,
    preferredDirectoryName?: string
  ) => {
    setProbeResult(result);
    setSelectedRefKey(buildSelectedRefKey(result));

    if (!result.has_skills_dir) {
      setSelectedDirectoryName('');
      setSkillName('');
      setProbeMessage('This repository does not contain a top-level skills/ directory.');
      return;
    }

    if (result.candidates.length === 0) {
      setSelectedDirectoryName('');
      setSkillName('');
      setProbeMessage(
        'No importable skill folders were found under skills/. Each folder needs SKILL.md, skill.md, or Skill.md.'
      );
      return;
    }

    const preserved = preferredDirectoryName
      ? result.candidates.find(
        (candidate) => candidate.directory_name === preferredDirectoryName
      )
      : null;
    const nextCandidate = preserved ?? result.candidates[0];
    setProbeMessage(null);
    setSelectedDirectoryName(nextCandidate.directory_name);
    setSkillName(sanitizeSkillName(nextCandidate.suggested_name));
  }, []);

  useEffect(() => {
    if (!open) {
      resetState();
    }
  }, [open, resetState]);

  const handleProbe = useCallback(async (refName?: string | null) => {
    if (!githubUrl.trim()) {
      toast.error('GitHub repository URL is required');
      return;
    }

    setIsProbing(true);
    setProbeMessage(null);
    try {
      const result = await probeGitHubSkills(githubUrl.trim(), refName ?? null);
      applyProbeResult(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to probe repository';
      setProbeResult(null);
      setSelectedRefKey(null);
      setSelectedDirectoryName('');
      setSkillName('');
      setProbeMessage(message);
      toast.error(message);
    } finally {
      setIsProbing(false);
    }
  }, [applyProbeResult, githubUrl]);

  const handleRefChange = useCallback(async (value: string) => {
    const separatorIndex = value.indexOf(':');
    const refName = separatorIndex === -1 ? value : value.slice(separatorIndex + 1);
    setSelectedRefKey(value);

    // Ref changes can surface a different skills/ tree, so we re-probe from the
    // backend instead of trying to keep stale client-side candidate data around.
    setIsProbing(true);
    setProbeMessage(null);
    try {
      const result = await probeGitHubSkills(githubUrl.trim(), refName);
      applyProbeResult(result, selectedDirectoryName);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load ref';
      setProbeMessage(message);
      toast.error(message);
    } finally {
      setIsProbing(false);
    }
  }, [applyProbeResult, githubUrl, selectedDirectoryName]);

  const handleImport = useCallback(async () => {
    if (!probeResult || !selectedCandidate || !effectiveSelectedRefKey) {
      toast.error('Probe a repository and choose a skill before importing');
      return;
    }
    if (!trimmedSkillName) {
      toast.error('Skill name is required');
      return;
    }
    if (nameConflict) {
      toast.error('Skill name already exists. Choose a different name.');
      return;
    }

    const separatorIndex = effectiveSelectedRefKey.indexOf(':');
    const refType = effectiveSelectedRefKey.slice(0, separatorIndex) as GitHubRefType;
    const refName = effectiveSelectedRefKey.slice(separatorIndex + 1);

    setIsImporting(true);
    try {
      await importGitHubSkill({
        github_url: githubUrl.trim(),
        ref: refName,
        ref_type: refType,
        kind: visibility,
        remote_directory_name: selectedCandidate.directory_name,
        skill_name: trimmedSkillName,
      });
      toast.success('Skill imported and available immediately.');
      await onImported();
      onOpenChange(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to import skill';
      toast.error(message);
    } finally {
      setIsImporting(false);
    }
  }, [
    effectiveSelectedRefKey,
    githubUrl,
    nameConflict,
    onImported,
    onOpenChange,
    probeResult,
    selectedCandidate,
    trimmedSkillName,
    visibility,
  ]);

  return (
    <TooltipProvider>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden sm:max-w-[740px]">
          <DialogHeader>
            <DialogTitle>Import Skills</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="skill-import-url">
                  GitHub Repository URL <span className="text-destructive">*</span>
                </Label>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <p>
                      Public GitHub repositories only for now. The repository must expose a top-level skills/ directory.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="flex gap-2">
                <Input
                  id="skill-import-url"
                  value={githubUrl}
                  onChange={(event) => setGitHubUrl(event.target.value)}
                  placeholder="https://github.com/owner/repository"
                  autoComplete="off"
                  disabled={isProbing || isImporting}
                />
                <Button
                  type="button"
                  onClick={() => void handleProbe()}
                  disabled={isProbing || isImporting}
                  className="shrink-0 gap-1.5"
                >
                  {isProbing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  {isProbing ? 'Probing…' : 'Probe'}
                </Button>
              </div>
            </div>

            {probeResult && (
              <div className="rounded-lg border border-border bg-muted/30 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <a
                    href={probeResult.repository.html_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground transition-colors hover:text-primary"
                  >
                    {probeResult.repository.owner}/{probeResult.repository.repo}
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                  <Badge variant="secondary">GitHub</Badge>
                </div>
                {probeResult.repository.description && (
                  <p className="mt-2 text-sm text-muted-foreground">
                    {probeResult.repository.description}
                  </p>
                )}
              </div>
            )}

            {probeMessage && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{probeMessage}</span>
              </div>
            )}
          </div>

          <Separator />

          {!probeResult ? (
            <div className="flex min-h-52 items-center justify-center text-sm text-muted-foreground">
              Enter a GitHub repository URL and probe it to discover importable skills.
            </div>
          ) : (
            <div className="grid items-start gap-5 py-1 md:grid-cols-[minmax(0,320px)_minmax(0,320px)] md:justify-center">
              <div className="space-y-5">
                <div className="space-y-2">
                  <div className="flex min-h-6 items-center gap-2">
                    <Label htmlFor="skill-import-ref">Git Ref</Label>
                    <span className="text-xs text-muted-foreground">
                      {buildRefSummary(probeResult)}
                    </span>
                  </div>
                  <Select
                    value={effectiveSelectedRefKey ?? undefined}
                    onValueChange={(value) => void handleRefChange(value)}
                    disabled={isProbing || isImporting || refOptions.length === 0}
                  >
                    <SelectTrigger id="skill-import-ref">
                      <SelectValue placeholder="Select a branch or tag" />
                    </SelectTrigger>
                    <SelectContent>
                      {refOptions.map((option) => (
                        <SelectItem key={option.key} value={option.key}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Label htmlFor="skill-import-visibility">Visibility</Label>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                      </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      <p>
                          Private imports go to your own workspace. Shared imports are visible to other users immediately after import.
                      </p>
                    </TooltipContent>
                  </Tooltip>
                  </div>
                  <Select
                    value={visibility}
                    onValueChange={(value) => setVisibility(value as SkillVisibility)}
                    disabled={isImporting}
                  >
                    <SelectTrigger id="skill-import-visibility">
                      <SelectValue placeholder="Choose visibility" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="private">Private</SelectItem>
                      <SelectItem value="shared">Shared</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Label htmlFor="skill-import-name">Local Skill Name</Label>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs">
                        <p>
                          Source folder {selectedCandidate?.directory_name ?? 'the selected skill'} will be installed as {trimmedSkillName || 'the local skill name you choose'}.
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <Input
                    id="skill-import-name"
                    value={skillName}
                    onChange={(event) => setSkillName(event.target.value)}
                    placeholder="unique_skill_name"
                    autoComplete="off"
                    aria-invalid={nameConflict}
                    className={nameConflict ? 'border-destructive focus-visible:ring-destructive' : ''}
                  />
                  {nameConflict && (
                    <p className="text-xs text-destructive">
                      This name already exists globally. Pick a different name before importing.
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex min-h-6 items-center">
                  <Label>Detected Skills</Label>
                </div>
                {probeResult.candidates.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
                    No importable skill folders are available for the selected ref.
                  </div>
                ) : (
                  <div className="h-[324px] space-y-2 overflow-y-auto pr-1">
                    {probeResult.candidates.map((candidate) => {
                      const isSelected = candidate.directory_name === selectedDirectoryName;
                      return (
                        <button
                          key={candidate.directory_name}
                          type="button"
                          onClick={() => {
                            setSelectedDirectoryName(candidate.directory_name);
                            setSkillName(sanitizeSkillName(candidate.suggested_name));
                          }}
                          className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                            isSelected
                              ? 'border-primary bg-primary/5'
                              : 'border-border hover:border-primary/40 hover:bg-accent/40'
                          }`}
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium text-foreground">{candidate.directory_name}</span>
                            <Badge variant="outline" className="text-[11px]">
                              {candidate.entry_filename}
                            </Badge>
                            {candidate.name_conflict && (
                              <Badge variant="destructive" className="text-[11px]">
                                Duplicated name
                              </Badge>
                            )}
                          </div>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <p className="mt-1 cursor-help truncate text-xs text-muted-foreground">
                                {candidate.description || 'No description provided in skill front matter.'}
                              </p>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="max-w-md whitespace-pre-wrap break-words">
                              <p>
                                {candidate.description || 'No description provided in skill front matter.'}
                              </p>
                            </TooltipContent>
                          </Tooltip>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          <Separator />

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isImporting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleImport()}
              disabled={
                isImporting ||
                isProbing ||
                !probeResult ||
                !selectedCandidate ||
                !effectiveSelectedRefKey ||
                !trimmedSkillName ||
                nameConflict
              }
              className="gap-1.5"
            >
              {isImporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {isImporting ? 'Importing…' : 'Import Skill'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}

export default SkillImportDialog;
