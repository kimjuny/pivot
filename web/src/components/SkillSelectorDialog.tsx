import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Loader2, Inbox, Plus } from "@/lib/lucide";
import { toast } from 'sonner';
import {
  getUsableSkills,
  type SkillSource,
  type UsableSkill,
} from '../utils/api';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { ButtonGroup } from '@/components/ui/button-group';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import DraggableDialog from './DraggableDialog';

interface SkillEntry {
  name: string;
  summary: string;
  source: SkillSource;
  creator: string | null;
  readOnly: boolean;
}

interface SkillSelectorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  currentSkillIds: string | null | undefined;
  onSaved: (newSkillIds: string) => void;
}

/**
 * Dialog for configuring the explicit skill selection of an agent.
 * Mirrors the tool selector interaction model for consistency.
 */
function SkillSelectorDialog({
  open,
  onOpenChange,
  agentId,
  currentSkillIds,
  onSaved,
}: SkillSelectorDialogProps) {
  const navigate = useNavigate();
  const [allSkills, setAllSkills] = useState<SkillEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const [checked, setChecked] = useState<Set<string>>(new Set());

  const [searchQuery, setSearchQuery] = useState('');
  const loadSkills = useCallback(async () => {
    setIsLoading(true);
    try {
      const skills = await getUsableSkills();
      const merged: SkillEntry[] = [
        ...skills.map((s: UsableSkill): SkillEntry => ({
          name: s.name,
          summary: s.description,
          source: s.source,
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
        setChecked(new Set());
      } else {
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
      void loadSkills();
    }
  }, [open, loadSkills]);

  const filteredSkills = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allSkills.filter((s) => {
      const matchesSearch = !q || s.name.toLowerCase().includes(q) || s.summary.toLowerCase().includes(q);
      return matchesSearch;
    });
  }, [allSkills, searchQuery]);

  const isSkillChecked = (name: string) => checked.has(name);

  const toggleSkill = (name: string) => {
    const nextChecked = new Set(checked);
    if (nextChecked.has(name)) nextChecked.delete(name);
    else nextChecked.add(name);
    setChecked(nextChecked);
  };

  const toggleVisibleAll = () => {
    const visibleNames = filteredSkills.map((s) => s.name);
    const allVisible = visibleNames.every((n) => isSkillChecked(n));
    const nextChecked = new Set(checked);

    if (allVisible) {
      visibleNames.forEach((n) => nextChecked.delete(n));
    } else {
      visibleNames.forEach((n) => nextChecked.add(n));
    }

    setChecked(nextChecked);
  };

  const handleSave = () => {
    setIsSaving(true);
    try {
      const newSkillIds = JSON.stringify(Array.from(checked).sort());
      onSaved(newSkillIds);
      toast.success('Skill selection staged in draft');
      onOpenChange(false);
    } catch {
      toast.error('Failed to stage skill selection');
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenSkillsList = () => {
    navigate('/studio/assets/skills');
    onOpenChange(false);
  };

  const visibleAllChecked = filteredSkills.length > 0 && filteredSkills.every((s) => isSkillChecked(s.name));
  const visibleSomeChecked = !visibleAllChecked && filteredSkills.some((s) => isSkillChecked(s.name));

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
          </div>

          <Separator />

          <div className="flex-1 overflow-y-auto overflow-x-hidden">
            {filteredSkills.length === 0 ? (
              allSkills.length === 0 ? (
                <div className="flex h-full min-h-64 items-center justify-center px-4 py-6">
                  <Empty className="min-h-64 gap-4 p-4 md:p-6">
                    <EmptyHeader className="gap-1.5">
                      <EmptyMedia variant="icon">
                        <Inbox className="size-5" />
                      </EmptyMedia>
                      <EmptyTitle className="text-base">No skills available</EmptyTitle>
                      <EmptyDescription className="text-xs/relaxed">
                        Add or import a skill first, then configure it for this agent.
                      </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                      <Button type="button" size="sm" onClick={handleOpenSkillsList}>
                        <Plus className="size-3.5" />
                        Go to Skills
                      </Button>
                    </EmptyContent>
                  </Empty>
                </div>
              ) : (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  No skills match your search.
                </div>
              )
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
                    <th className="w-[42%] h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Skill name</th>
                    <th className="h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Description</th>
                  </tr>
                </thead>
                <tbody className="[&_tr:last-child]:border-0">
                  {filteredSkills.map((skill) => {
                    const isChecked = isSkillChecked(skill.name);
                    return (
                      <tr
                        key={skill.name}
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
          <div className="flex items-center justify-end px-4 py-2 text-xs text-muted-foreground">
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
