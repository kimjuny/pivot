import { useState, useEffect, useCallback, useMemo } from 'react';
import { Lock, User as UserIcon, Search, Loader2, Globe2 } from "@/lib/lucide";
import { toast } from 'sonner';
import {
  getSharedSkills,
  getPrivateSkills,
  updateAgentSkillIds,
  type SharedSkill,
  type UserSkill,
} from '../utils/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { ButtonGroup } from '@/components/ui/button-group';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Label } from '@/components/ui/label';
import DraggableDialog from './DraggableDialog';

interface SkillEntry {
  name: string;
  summary: string;
  kind: 'shared' | 'private';
  source: 'builtin' | 'user';
  creator: string | null;
  readOnly: boolean;
}

type FilterKind = 'all' | 'shared' | 'private';

interface SkillSelectorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  currentSkillIds: string | null | undefined;
  onSaved: (newSkillIds: string | null) => void;
}

/**
 * Dialog for configuring the skill allowlist of an agent.
 * Mirrors the tool selector interaction model for consistency.
 */
function SkillSelectorDialog({
  open,
  onOpenChange,
  agentId,
  currentSkillIds,
  onSaved,
}: SkillSelectorDialogProps) {
  const [allSkills, setAllSkills] = useState<SkillEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [allowAll, setAllowAll] = useState(true);

  const [searchQuery, setSearchQuery] = useState('');
  const [filterKind, setFilterKind] = useState<FilterKind>('all');

  const loadSkills = useCallback(async () => {
    setIsLoading(true);
    try {
      const [shared, priv] = await Promise.all([getSharedSkills(), getPrivateSkills()]);
      const merged: SkillEntry[] = [
        ...shared.map((s: SharedSkill): SkillEntry => ({
          name: s.name,
          summary: s.description,
          kind: 'shared',
          source: s.source,
          creator: s.creator,
          readOnly: s.read_only,
        })),
        ...priv.map((s: UserSkill): SkillEntry => ({
          name: s.name,
          summary: s.description,
          kind: 'private',
          source: 'user',
          creator: s.creator,
          readOnly: s.read_only,
        })),
      ];

      const deduped = Array.from(
        merged.reduce((map, item) => {
          if (!map.has(item.name)) map.set(item.name, item);
          return map;
        }, new Map<string, SkillEntry>()).values()
      );

      setAllSkills(deduped);

      if (currentSkillIds === null || currentSkillIds === undefined) {
        setAllowAll(true);
        setChecked(new Set(deduped.map((s) => s.name)));
      } else {
        setAllowAll(false);
        try {
          const parsed: unknown = JSON.parse(currentSkillIds);
          const names = Array.isArray(parsed)
            ? parsed.filter((item): item is string => typeof item === 'string')
            : [];
          setChecked(new Set(names));
        } catch {
          setChecked(new Set());
        }
      }
    } catch {
      toast.error('Failed to load skills');
    } finally {
      setIsLoading(false);
    }
  }, [currentSkillIds]);

  useEffect(() => {
    if (open) {
      setSearchQuery('');
      setFilterKind('all');
      void loadSkills();
    }
  }, [open, loadSkills]);

  const filteredSkills = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allSkills.filter((s) => {
      const matchesKind = filterKind === 'all' || s.kind === filterKind;
      const matchesSearch = !q || s.name.toLowerCase().includes(q) || s.summary.toLowerCase().includes(q);
      return matchesKind && matchesSearch;
    });
  }, [allSkills, searchQuery, filterKind]);

  const isSkillChecked = (name: string) => allowAll || checked.has(name);

  const toggleSkill = (name: string) => {
    const nextChecked = new Set(checked);
    if (allowAll) {
      allSkills.forEach((s) => nextChecked.add(s.name));
      nextChecked.delete(name);
      setAllowAll(false);
    } else {
      if (nextChecked.has(name)) nextChecked.delete(name);
      else nextChecked.add(name);
    }
    setChecked(nextChecked);
  };

  const toggleVisibleAll = () => {
    const visibleNames = filteredSkills.map((s) => s.name);
    const allVisible = visibleNames.every((n) => isSkillChecked(n));
    const nextChecked = new Set(checked);

    if (allVisible) {
      visibleNames.forEach((n) => nextChecked.delete(n));
      setAllowAll(false);
    } else {
      visibleNames.forEach((n) => nextChecked.add(n));
      const unfiltered = !searchQuery.trim() && filterKind === 'all';
      if (unfiltered && nextChecked.size === allSkills.length) {
        setAllowAll(true);
      } else {
        setAllowAll(false);
      }
    }

    setChecked(nextChecked);
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const newSkillIds = allowAll ? null : Array.from(checked);
      const updated = await updateAgentSkillIds(agentId, newSkillIds);
      onSaved(updated.skill_ids ?? null);
      toast.success('Skill allowlist saved');
      onOpenChange(false);
    } catch {
      toast.error('Failed to save skill allowlist');
    } finally {
      setIsSaving(false);
    }
  };

  const visibleAllChecked = filteredSkills.length > 0 && filteredSkills.every((s) => isSkillChecked(s.name));
  const visibleSomeChecked = !visibleAllChecked && filteredSkills.some((s) => isSkillChecked(s.name));

  const kindCounts = useMemo(() => ({
    all: allSkills.length,
    shared: allSkills.filter((s) => s.kind === 'shared').length,
    private: allSkills.filter((s) => s.kind === 'private').length,
  }), [allSkills]);

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Configure Agent Skills"
      size="default"
    >
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center gap-2 text-sm text-muted-foreground h-full">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading skills…
        </div>
      ) : (
        <div className="flex flex-col h-full">
          <div className="flex flex-col gap-2 px-4 pt-3 pb-2">
            <ButtonGroup className="w-full">
              <Input
                placeholder="Search skills…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 text-sm flex-1"
                autoComplete="off"
              />
              <Button variant="outline" size="sm" className="h-8 px-2.5 shrink-0" tabIndex={-1} aria-label="Search">
                <Search className="w-3.5 h-3.5" />
              </Button>
            </ButtonGroup>

            <Tabs value={filterKind} onValueChange={(v) => setFilterKind(v as FilterKind)}>
              <TabsList className="h-7 p-0.5 gap-0.5">
                <TabsTrigger value="all" className="h-6 px-2.5 text-xs gap-1">
                  All
                  <span className="tabular-nums text-[10px] opacity-70">{kindCounts.all}</span>
                </TabsTrigger>
                <TabsTrigger value="shared" className="h-6 px-2.5 text-xs gap-1">
                  <Globe2 className="w-3 h-3" />Shared
                  <span className="tabular-nums text-[10px] opacity-70">{kindCounts.shared}</span>
                </TabsTrigger>
                <TabsTrigger value="private" className="h-6 px-2.5 text-xs gap-1">
                  <UserIcon className="w-3 h-3" />Private
                  <span className="tabular-nums text-[10px] opacity-70">{kindCounts.private}</span>
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <Separator />

          <div className="flex-1 overflow-y-auto overflow-x-hidden">
            {filteredSkills.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
                {allSkills.length === 0 ? 'No skills available.' : 'No skills match your search.'}
              </div>
            ) : (
              <table className="w-full caption-bottom text-sm table-fixed">
                <thead className="sticky top-0 bg-background z-10 [&_tr]:border-b">
                  <tr className="border-b transition-colors">
                    <th className="w-10 h-10 px-3 text-left align-middle font-medium text-muted-foreground">
                      <Checkbox
                        checked={visibleAllChecked ? true : visibleSomeChecked ? 'indeterminate' : false}
                        onCheckedChange={toggleVisibleAll}
                        aria-label="Select all visible skills"
                      />
                    </th>
                    <th className="w-[38%] h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Skill name</th>
                    <th className="w-[22%] h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Type</th>
                    <th className="h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Description</th>
                  </tr>
                </thead>
                <tbody className="[&_tr:last-child]:border-0">
                  {filteredSkills.map((skill) => {
                    const isChecked = isSkillChecked(skill.name);
                    return (
                      <tr
                        key={`${skill.kind}-${skill.name}`}
                        className="border-b transition-colors hover:bg-muted/50 cursor-pointer data-[state=selected]:bg-muted"
                        onClick={() => toggleSkill(skill.name)}
                        data-state={isChecked ? 'selected' : undefined}
                      >
                        <td className="px-3 py-2 align-middle">
                          <Checkbox
                            checked={isChecked}
                            onCheckedChange={() => toggleSkill(skill.name)}
                            onClick={(e) => e.stopPropagation()}
                            aria-label={`Toggle ${skill.name}`}
                          />
                        </td>
                        <td className="px-2 py-2 align-middle overflow-hidden">
                          <span className="font-mono text-xs font-medium block truncate">{skill.name}</span>
                        </td>
                        <td className="px-2 py-2 align-middle">
                          {skill.kind === 'shared' ? (
                            <Badge variant="secondary" className="gap-1 text-[10px] px-1.5 h-5 whitespace-nowrap">
                              {skill.source === 'builtin' ? <Lock className="w-2.5 h-2.5" /> : <Globe2 className="w-2.5 h-2.5" />}
                              {skill.source === 'builtin' ? 'Builtin' : skill.readOnly ? `Shared / ${skill.creator ?? 'Unknown'}` : 'Shared / You'}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="gap-1 text-[10px] px-1.5 h-5 whitespace-nowrap">
                              <UserIcon className="w-2.5 h-2.5" />Private
                            </Badge>
                          )}
                        </td>
                        <td className="px-2 py-2 align-middle overflow-hidden">
                          {skill.summary ? (
                            <span className="text-xs text-muted-foreground block truncate">{skill.summary}</span>
                          ) : (
                            <span className="text-xs text-muted-foreground/40 italic">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <Separator />
          <div className="flex items-center justify-between px-4 py-2 text-xs text-muted-foreground">
            <Label className="flex items-center gap-1.5 cursor-pointer select-none font-normal" onClick={() => {
              if (allowAll) {
                setAllowAll(false);
                setChecked(new Set());
              } else {
                setAllowAll(true);
                setChecked(new Set(allSkills.map((s) => s.name)));
              }
            }}>
              <Checkbox
                checked={allowAll}
                onCheckedChange={(v) => {
                  if (v) {
                    setAllowAll(true);
                    setChecked(new Set(allSkills.map((s) => s.name)));
                  } else {
                    setAllowAll(false);
                  }
                }}
                onClick={(e) => e.stopPropagation()}
              />
              Allow all
            </Label>

            <div className="flex items-center gap-2">
              <span className="tabular-nums">
                {filteredSkills.filter((s) => isSkillChecked(s.name)).length} of {filteredSkills.length} shown selected
              </span>
              <Button
                size="sm"
                disabled={isSaving || isLoading}
                onClick={() => void handleSave()}
                className="h-6 text-xs px-3"
              >
                {isSaving ? <><Loader2 className="w-3 h-3 animate-spin mr-1" />Saving…</> : 'Save'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </DraggableDialog>
  );
}

export default SkillSelectorDialog;
