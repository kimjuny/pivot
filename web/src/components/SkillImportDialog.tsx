import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import {
  AlertCircle,
  ExternalLink,
  FileText,
  FolderUp,
  Info,
  Loader2,
  Upload,
} from "@/lib/lucide";
import { toast } from 'sonner';

import type {
  BundleSkillImportFile,
  GitHubSkillCandidate,
  GitHubSkillProbeResponse,
  SkillImportProgressEvent,
} from '@/utils/api';
import {
  createSkillArchiveImportJob,
  importBundleSkill,
  importGitHubSkill,
  importSkillArchive,
  probeGitHubSkills,
  streamSkillArchiveImportJobEvents,
} from '@/utils/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Field, FieldLabel } from '@/components/ui/field';
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Progress } from '@/components/ui/progress';

type SkillVisibility = 'private' | 'shared';
type GitHubRefType = 'branch' | 'tag';
type ImportTabValue = 'bundle' | 'github';

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

const SKILL_ENTRY_FILENAMES = ['SKILL.md', 'skill.md', 'Skill.md'] as const;
const MAX_DIRECTORY_BUNDLE_FILES = 100;

function formatFileCount(count: number): string {
  return count.toLocaleString();
}

function archiveSkillName(filename: string): string {
  return sanitizeSkillName(
    filename.replace(/\.(tar\.gz|tgz|zip|tar)$/i, '')
  );
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

function parseBundleSelection(fileList: FileList): {
  bundleName: string;
  files: BundleSkillImportFile[];
  entryFilename: string;
} {
  const files = Array.from(fileList);
  if (files.length === 0) {
    throw new Error('Choose a local skill folder before importing.');
  }

  const rootNames = new Set<string>();
  const entries: BundleSkillImportFile[] = files.map((file) => {
    const rawRelativePath =
      (file as File & { webkitRelativePath?: string }).webkitRelativePath?.trim() ||
      file.name;
    const segments = rawRelativePath.split('/').filter(Boolean);
    if (segments.length === 0) {
      throw new Error('The selected folder contains a file with an invalid path.');
    }

    rootNames.add(segments[0] ?? file.name);
    const relativePath =
      segments.length > 1 ? segments.slice(1).join('/') : file.name;

    return {
      file,
      relativePath,
    };
  });

  if (rootNames.size !== 1) {
    throw new Error('Choose exactly one local skill folder at a time.');
  }

  const bundleName = Array.from(rootNames)[0] ?? '';
  const entryFilename = entries.find(
    (entry) =>
      !entry.relativePath.includes('/') &&
      SKILL_ENTRY_FILENAMES.includes(
        entry.relativePath as (typeof SKILL_ENTRY_FILENAMES)[number]
      )
  )?.relativePath;

  if (!bundleName) {
    throw new Error('Unable to determine the selected folder name.');
  }
  if (!entryFilename) {
    throw new Error(
      `The selected folder must contain ${SKILL_ENTRY_FILENAMES.join(', ')} at its top level.`
    );
  }

  return {
    bundleName,
    files: entries,
    entryFilename,
  };
}

/**
 * Dialog for importing skills from either a local bundle or a GitHub repository.
 */
function SkillImportDialog({
  open,
  onOpenChange,
  existingSkillNames,
  onImported,
}: SkillImportDialogProps) {
  const bundleInputRef = useRef<HTMLInputElement | null>(null);
  const archiveInputRef = useRef<HTMLInputElement | null>(null);
  const archiveStreamAbortRef = useRef<AbortController | null>(null);
  const [activeTab, setActiveTab] = useState<ImportTabValue>('bundle');

  const [bundleName, setBundleName] = useState('');
  const [bundleFiles, setBundleFiles] = useState<BundleSkillImportFile[]>([]);
  const [bundleEntryFilename, setBundleEntryFilename] = useState('');
  const [bundleSkillName, setBundleSkillName] = useState('');
  const [bundleVisibility, setBundleVisibility] = useState<SkillVisibility>('private');
  const [bundleMessage, setBundleMessage] = useState<string | null>(null);
  const [archiveFile, setArchiveFile] = useState<File | null>(null);
  const [archiveSkillNameValue, setArchiveSkillNameValue] = useState('');
  const [archiveVisibility, setArchiveVisibility] = useState<SkillVisibility>('private');
  const [archiveMessage, setArchiveMessage] = useState<string | null>(null);
  const [archiveProgress, setArchiveProgress] = useState<SkillImportProgressEvent | null>(null);

  const [githubUrl, setGitHubUrl] = useState('');
  const [probeResult, setProbeResult] = useState<GitHubSkillProbeResponse | null>(null);
  const [selectedRefKey, setSelectedRefKey] = useState<string | null>(null);
  const [selectedDirectoryName, setSelectedDirectoryName] = useState('');
  const [githubSkillName, setGitHubSkillName] = useState('');
  const [githubVisibility, setGitHubVisibility] = useState<SkillVisibility>('private');
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
  const trimmedBundleSkillName = bundleSkillName.trim();
  const trimmedArchiveSkillName = archiveSkillNameValue.trim();
  const trimmedGitHubSkillName = githubSkillName.trim();
  const bundleNameConflict =
    trimmedBundleSkillName.length > 0 && existingSkillNames.has(trimmedBundleSkillName);
  const archiveNameConflict =
    trimmedArchiveSkillName.length > 0 && existingSkillNames.has(trimmedArchiveSkillName);
  const githubNameConflict =
    trimmedGitHubSkillName.length > 0 && existingSkillNames.has(trimmedGitHubSkillName);

  const resetState = useCallback(() => {
    archiveStreamAbortRef.current?.abort();
    archiveStreamAbortRef.current = null;
    setActiveTab('bundle');
    setBundleName('');
    setBundleFiles([]);
    setBundleEntryFilename('');
    setBundleSkillName('');
    setBundleVisibility('private');
    setBundleMessage(null);
    setArchiveFile(null);
    setArchiveSkillNameValue('');
    setArchiveVisibility('private');
    setArchiveMessage(null);
    setArchiveProgress(null);
    setGitHubUrl('');
    setProbeResult(null);
    setSelectedRefKey(null);
    setSelectedDirectoryName('');
    setGitHubSkillName('');
    setGitHubVisibility('private');
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
      setGitHubSkillName('');
      setProbeMessage('This repository does not contain a top-level skills/ directory.');
      return;
    }

    if (result.candidates.length === 0) {
      setSelectedDirectoryName('');
      setGitHubSkillName('');
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
    setGitHubSkillName(sanitizeSkillName(nextCandidate.suggested_name));
  }, []);

  useEffect(() => {
    if (!open) {
      resetState();
    }
  }, [open, resetState]);

  const handleBundleSelection = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const fileList = event.target.files;
    if (!fileList || fileList.length === 0) {
      return;
    }

    try {
      if (fileList.length > MAX_DIRECTORY_BUNDLE_FILES) {
        throw new Error(
          `This folder contains ${formatFileCount(fileList.length)} files. Compress large skills as .zip, .tar, .tar.gz, or .tgz before importing.`
        );
      }
      const selection = parseBundleSelection(fileList);
      setBundleName(selection.bundleName);
      setBundleFiles(selection.files);
      setBundleEntryFilename(selection.entryFilename);
      setBundleSkillName(sanitizeSkillName(selection.bundleName));
      setBundleMessage(null);
      setArchiveFile(null);
      setArchiveSkillNameValue('');
      setArchiveMessage(null);
      setArchiveProgress(null);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to read the selected folder.';
      setBundleName('');
      setBundleFiles([]);
      setBundleEntryFilename('');
      setBundleSkillName('');
      setBundleMessage(message);
      toast.error(message);
    } finally {
      event.target.value = '';
    }
  }, []);

  const handleArchiveSelection = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) {
      return;
    }

    const isSupportedArchive = /\.(zip|tar|tar\.gz|tgz)$/i.test(selectedFile.name);
    if (!isSupportedArchive) {
      const message = 'Choose a .zip, .tar, .tar.gz, or .tgz skill archive.';
      setArchiveFile(null);
      setArchiveSkillNameValue('');
      setArchiveMessage(message);
      toast.error(message);
      event.target.value = '';
      return;
    }

    setArchiveFile(selectedFile);
    setArchiveSkillNameValue(archiveSkillName(selectedFile.name));
    setArchiveMessage(null);
    setArchiveProgress(null);
    setBundleName('');
    setBundleFiles([]);
    setBundleEntryFilename('');
    setBundleSkillName('');
    setBundleMessage(null);
    event.target.value = '';
  }, []);

  const handleProbe = useCallback(async (refName?: string | null) => {
    if (!githubUrl.trim()) {
      toast.error('Github repository URL is required');
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
      setGitHubSkillName('');
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
    if (activeTab === 'bundle') {
      if (archiveFile) {
        if (!trimmedArchiveSkillName) {
          toast.error('Skill name is required');
          return;
        }
        if (archiveNameConflict) {
          toast.error('Skill name already exists. Choose a different name.');
          return;
        }

        setIsImporting(true);
        setArchiveProgress({
          event_id: 0,
          job_id: '',
          stage: 'preparing',
          label: 'Preparing archive import',
          percent: 0,
          status: 'running',
          detail: null,
          metadata: null,
          timestamp: new Date().toISOString(),
        });

        const streamAbortController = new AbortController();
        archiveStreamAbortRef.current = streamAbortController;

        try {
          const job = await createSkillArchiveImportJob();
          const streamPromise = streamSkillArchiveImportJobEvents(
            job.job_id,
            setArchiveProgress,
            streamAbortController.signal,
          ).catch((error) => {
            if (error instanceof Error && error.name === 'AbortError') {
              return;
            }
            console.error('Archive import progress stream failed:', error);
          });

          await importSkillArchive({
            jobId: job.job_id,
            kind: archiveVisibility,
            skillName: trimmedArchiveSkillName,
            archive: archiveFile,
          });
          await streamPromise;
          toast.success('Skill imported and available immediately.');
          await onImported();
          onOpenChange(false);
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Failed to import skill';
          setArchiveProgress((current) => ({
            event_id: current?.event_id ?? 0,
            job_id: current?.job_id ?? '',
            stage: 'failed',
            label: 'Import failed',
            percent: 100,
            status: 'failed',
            detail: message,
            metadata: null,
            timestamp: new Date().toISOString(),
          }));
          toast.error(message);
        } finally {
          streamAbortController.abort();
          if (archiveStreamAbortRef.current === streamAbortController) {
            archiveStreamAbortRef.current = null;
          }
          setIsImporting(false);
        }
        return;
      }

      if (!bundleName || bundleFiles.length === 0 || !bundleEntryFilename) {
        toast.error('Choose a local skill folder before importing');
        return;
      }
      if (!trimmedBundleSkillName) {
        toast.error('Skill name is required');
        return;
      }
      if (bundleNameConflict) {
        toast.error('Skill name already exists. Choose a different name.');
        return;
      }

      setIsImporting(true);
      try {
        await importBundleSkill({
          bundleName,
          kind: bundleVisibility,
          skillName: trimmedBundleSkillName,
          files: bundleFiles,
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
      return;
    }

    if (!probeResult || !selectedCandidate || !effectiveSelectedRefKey) {
      toast.error('Probe a repository and choose a skill before importing');
      return;
    }
    if (!trimmedGitHubSkillName) {
      toast.error('Skill name is required');
      return;
    }
    if (githubNameConflict) {
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
        kind: githubVisibility,
        remote_directory_name: selectedCandidate.directory_name,
        skill_name: trimmedGitHubSkillName,
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
    activeTab,
    archiveFile,
    archiveNameConflict,
    archiveVisibility,
    bundleEntryFilename,
    bundleFiles,
    bundleName,
    bundleNameConflict,
    bundleVisibility,
    effectiveSelectedRefKey,
    githubNameConflict,
    githubUrl,
    githubVisibility,
    onImported,
    onOpenChange,
    probeResult,
    selectedCandidate,
    trimmedArchiveSkillName,
    trimmedBundleSkillName,
    trimmedGitHubSkillName,
  ]);

  const importDisabled =
    activeTab === 'bundle'
      ? archiveFile
        ? isImporting ||
          !trimmedArchiveSkillName ||
          archiveNameConflict
        : isImporting ||
          !bundleName ||
          bundleFiles.length === 0 ||
          !bundleEntryFilename ||
          !trimmedBundleSkillName ||
          bundleNameConflict
      : isImporting ||
        isProbing ||
        !probeResult ||
        !selectedCandidate ||
        !effectiveSelectedRefKey ||
        !trimmedGitHubSkillName ||
        githubNameConflict;

  return (
    <TooltipProvider>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden sm:max-w-[760px]">
          <DialogHeader>
            <DialogTitle>Import Skills</DialogTitle>
          </DialogHeader>

          <Tabs
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as ImportTabValue)}
            className="flex min-h-0 flex-1 flex-col"
          >
            <TabsList className="grid h-auto w-full grid-cols-2">
              <TabsTrigger value="bundle">Bundle</TabsTrigger>
              <TabsTrigger value="github">Github</TabsTrigger>
            </TabsList>

            <TabsContent value="bundle" className="min-h-0 flex-1 space-y-4 pt-4">
              <div className="space-y-4 rounded-lg border border-dashed border-border p-4">
                <div className="space-y-1">
                  <p className="text-sm font-medium text-foreground">Local Skill Bundle</p>
                  <p className="text-sm text-muted-foreground">
                    Import a skill directory that contains a top-level skill entry file.
                  </p>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <Tooltip delayDuration={1000}>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => bundleInputRef.current?.click()}
                        disabled={isImporting}
                        className={`h-auto justify-start gap-3 whitespace-normal rounded-lg p-4 text-left ${
                          bundleName ? 'border-primary bg-primary/5' : ''
                        }`}
                      >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-background">
                          <FolderUp className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 space-y-1">
                          <span className="block text-sm font-medium leading-none text-foreground">
                            Choose Folder
                          </span>
                          <span className="block text-xs leading-5 text-muted-foreground">
                            Small skills, up to {MAX_DIRECTORY_BUNDLE_FILES} files.
                          </span>
                        </span>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      <p>
                        Use folder import only for small skills with {MAX_DIRECTORY_BUNDLE_FILES} files or fewer.
                      </p>
                    </TooltipContent>
                  </Tooltip>

                  <Tooltip delayDuration={1000}>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => archiveInputRef.current?.click()}
                        disabled={isImporting}
                        className={`h-auto justify-start gap-3 whitespace-normal rounded-lg p-4 text-left ${
                          archiveFile ? 'border-primary bg-primary/5' : ''
                        }`}
                      >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-background">
                          <FileText className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 space-y-1">
                          <span className="block text-sm font-medium leading-none text-foreground">
                            Choose Archive
                          </span>
                          <span className="block text-xs leading-5 text-muted-foreground">
                            .zip, .tar, .tar.gz, or .tgz.
                          </span>
                        </span>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      <p>
                        Use archive import for larger skills packaged as .zip, .tar, .tar.gz, or .tgz.
                      </p>
                    </TooltipContent>
                  </Tooltip>
                </div>

                {(bundleName || archiveFile) && (
                  <div className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                    {bundleName ? (
                      <>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-foreground">{bundleName}</span>
                          <Badge variant="secondary">{bundleFiles.length} files</Badge>
                          <Badge variant="outline">{bundleEntryFilename}</Badge>
                        </div>
                        <p className="mt-2 text-sm text-muted-foreground">
                          The backend will keep the full directory tree when importing.
                        </p>
                      </>
                    ) : null}
                    {archiveFile ? (
                      <>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-foreground">{archiveFile.name}</span>
                          <Badge variant="secondary">
                            {Math.max(1, Math.round(archiveFile.size / 1024)).toLocaleString()} KB
                          </Badge>
                        </div>
                        <p className="mt-2 text-sm text-muted-foreground">
                          The backend will extract the archive, validate the skill entry, and install the full tree.
                        </p>
                      </>
                    ) : null}
                  </div>
                )}

                <div className="grid gap-2">
                  {bundleMessage && (
                    <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{bundleMessage}</span>
                    </div>
                  )}

                  {archiveMessage && (
                    <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{archiveMessage}</span>
                    </div>
                  )}
                </div>

                <input
                  ref={bundleInputRef}
                  type="file"
                  multiple
                  directory=""
                  webkitdirectory=""
                  className="hidden"
                  onChange={handleBundleSelection}
                />

                <input
                  ref={archiveInputRef}
                  type="file"
                  accept=".zip,.tar,.tar.gz,.tgz"
                  className="hidden"
                  onChange={handleArchiveSelection}
                />
              </div>

              {(bundleName || archiveFile) && (
                <div className="grid items-start gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <div className="flex min-h-6 items-center gap-1.5">
                      <Label htmlFor="bundle-import-visibility">Visibility</Label>
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
                      value={archiveFile ? archiveVisibility : bundleVisibility}
                      onValueChange={(value) => {
                        if (archiveFile) {
                          setArchiveVisibility(value as SkillVisibility);
                        } else {
                          setBundleVisibility(value as SkillVisibility);
                        }
                      }}
                      disabled={isImporting}
                    >
                      <SelectTrigger id="bundle-import-visibility">
                        <SelectValue placeholder="Choose visibility" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="private">Private</SelectItem>
                        <SelectItem value="shared">Shared</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <div className="flex min-h-6 items-center">
                      <Label htmlFor="bundle-import-name">Local Skill Name</Label>
                    </div>
                    <Input
                      id="bundle-import-name"
                      value={archiveFile ? archiveSkillNameValue : bundleSkillName}
                      onChange={(event) => {
                        if (archiveFile) {
                          setArchiveSkillNameValue(event.target.value);
                        } else {
                          setBundleSkillName(event.target.value);
                        }
                      }}
                      placeholder="unique_skill_name"
                      autoComplete="off"
                      aria-invalid={archiveFile ? archiveNameConflict : bundleNameConflict}
                      className={
                        (archiveFile ? archiveNameConflict : bundleNameConflict)
                          ? 'border-destructive focus-visible:ring-destructive'
                          : ''
                      }
                    />
                    {(archiveFile ? archiveNameConflict : bundleNameConflict) && (
                      <p className="text-xs text-destructive">
                        This name already exists globally. Pick a different name before importing.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {archiveProgress && (
                <Field className="rounded-lg border border-border bg-muted/30 px-3 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <FieldLabel>{archiveProgress.label}</FieldLabel>
                    <span className="text-sm text-muted-foreground">
                      {Math.round(archiveProgress.percent)}%
                    </span>
                  </div>
                  <Progress value={archiveProgress.percent} />
                  {archiveProgress.detail && (
                    <p className="text-sm text-muted-foreground">{archiveProgress.detail}</p>
                  )}
                </Field>
              )}
            </TabsContent>

            <TabsContent value="github" className="min-h-0 flex-1 space-y-4 pt-4">
              <div className="space-y-4 rounded-lg border border-dashed border-border p-4">
                <div className="space-y-2">
                  <div className="flex min-h-6 items-center gap-1.5">
                    <Label htmlFor="skill-import-url">
                      Github Repository URL <span className="text-destructive">*</span>
                    </Label>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs">
                        <p>
                          Public Github repositories only for now. The repository must expose a top-level skills/ directory.
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <ButtonGroup className="w-full">
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
                      variant="outline"
                      onClick={() => void handleProbe()}
                      disabled={isProbing || isImporting}
                      className="shrink-0 gap-1.5"
                    >
                      {isProbing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                      {isProbing ? 'Probing…' : 'Probe'}
                    </Button>
                  </ButtonGroup>
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
                      <Badge variant="secondary">Github</Badge>
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
              {probeResult && (
                <div className="grid items-start gap-5 md:grid-cols-2">
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
                      <div className="flex min-h-6 items-center gap-1.5">
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
                        value={githubVisibility}
                        onValueChange={(value) => setGitHubVisibility(value as SkillVisibility)}
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
                      <div className="flex min-h-6 items-center gap-1.5">
                        <Label htmlFor="skill-import-name">Local Skill Name</Label>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                          </TooltipTrigger>
                          <TooltipContent side="top" className="max-w-xs">
                            <p>
                              Source folder {selectedCandidate?.directory_name ?? 'the selected skill'} will be installed as {trimmedGitHubSkillName || 'the local skill name you choose'}.
                            </p>
                          </TooltipContent>
                        </Tooltip>
                      </div>
                      <Input
                        id="skill-import-name"
                        value={githubSkillName}
                        onChange={(event) => setGitHubSkillName(event.target.value)}
                        placeholder="unique_skill_name"
                        autoComplete="off"
                        aria-invalid={githubNameConflict}
                        className={githubNameConflict ? 'border-destructive focus-visible:ring-destructive' : ''}
                      />
                      {githubNameConflict && (
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
                      <div className="h-[252px] space-y-2 overflow-y-auto pr-1">
                        {probeResult.candidates.map((candidate) => {
                          const isSelected = candidate.directory_name === selectedDirectoryName;
                          return (
                            <button
                              key={candidate.directory_name}
                              type="button"
                              onClick={() => {
                                setSelectedDirectoryName(candidate.directory_name);
                                setGitHubSkillName(sanitizeSkillName(candidate.suggested_name));
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
            </TabsContent>
          </Tabs>

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
              disabled={importDisabled}
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
