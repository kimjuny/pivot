# Skills In Pivot

## Overview

Pivot treats a skill as a reusable capability package that can be injected into an agent runtime when it is relevant to the current task.

A skill is not only a markdown prompt. In the long run, a skill may also include helper scripts, templates, examples, or other support files. Because of that, Pivot stores skills as directories, not as single loose files.

This document explains:

- what a skill is
- where skills live
- how they become visible to users and agents
- how GitHub import works
- why the current architecture is split between orchestration code and service code

The intended audience is developers working on Pivot itself.

## Design Principles

The skill system follows a few simple rules.

1. Skills are directory-based packages.
2. The markdown entry file is the identity anchor, but the whole directory is the deployable unit.
3. Imported skills become active immediately after installation.
4. All persistence goes through services.
5. The structure should stay easy to read for both humans and AI contributors.

Those rules are more important than backward compatibility. Pivot is still pre-launch, so the implementation favors a clean model over carrying old formats forever.

## Skill Package Format

Pivot recognizes a directory as a valid skill when that directory contains one of these markdown entry files:

- `SKILL.md`
- `skill.md`
- `Skill.md`

The markdown file may contain front matter like this:

```md
---
name: research_notes
description: Reusable research workflow for evidence collection.
---

# Research Notes
...
```

Important details:

- `name` is the globally unique skill identifier used by the system.
- `description` is short metadata shown in UI and used by selection logic.
- The full directory is copied and mounted, not only the markdown file.

If the imported skill is renamed locally, Pivot rewrites the front matter `name` so the on-disk package and the database registry stay aligned.

## Storage Layout

There are three practical origins of skills.

### Built-in skills

Built-in skills ship with the application and live under:

```text
server/app/orchestration/skills/builtin/
```

They are always shared and read-only.

### User private skills

Private skills live under:

```text
server/workspace/{username}/skills/private/{skill_name}/
```

Only the owner can manage them. Agents owned by that user can use them immediately.

### User shared skills

Shared user-created or user-imported skills live under:

```text
server/workspace/{username}/skills/shared/{skill_name}/
```

They belong to one creator but are visible to other users immediately after import or creation.

## Database Model

The `skill` table is a registry, not the source of truth for file contents.

The split is intentional:

- skill source stays on disk because the runtime may need the whole directory
- compact metadata stays in the database so listings and skill selection can stay lightweight

The registry currently stores:

- identity: `name`
- ownership and scope: `creator_id`, `kind`
- origin: `source`, `builtin`
- file location: `location`, `filename`
- integrity/change tracking: `md5`
- GitHub import metadata: `github_repo_url`, `github_ref`, `github_ref_type`, `github_skill_path`

`sync_skill_registry()` scans the filesystem and synchronizes the registry with what actually exists on disk.

## Visibility Model

Pivot now uses one simple visibility model.

- private skills are visible to and usable by their owner immediately
- shared skills are visible to all users immediately
- built-in skills are always visible

Runtime helpers and management screens both work from the same visible registry set:

- `list_visible_skills()`
- `build_selected_skills_prompt_block()`
- `build_skill_mounts()`

## GitHub Import Workflow

Pivot currently supports a focused import path for public GitHub repositories that follow the conventional layout:

```text
repo-root/
  skills/
    skill-a/
      SKILL.md
      ...
    skill-b/
      skill.md
      ...
```

Repositories without a top-level `skills/` directory are intentionally ignored for now.

That constraint is deliberate. It gives a predictable 90% solution without trying to support every ad-hoc community format.

### Step 1: Probe repository

The user enters a GitHub repository URL in the Skills page import dialog.

The backend probes:

- repository metadata
- default branch
- branch list
- tag list
- `skills/` contents for the chosen ref

Then Pivot checks each child folder under `skills/`:

- if it contains `SKILL.md`, `skill.md`, or `Skill.md`, it is a valid candidate
- otherwise it is ignored

### Step 2: Choose ref and candidate skill

The user selects:

- branch or tag
- one candidate skill directory
- local visibility: `private` or `shared`
- final local skill name

The final local name must be globally unique across all skills. The UI warns when the chosen name already exists, and the backend validates it again.

### Step 3: Install package

The backend downloads the repository archive for the chosen ref, extracts only the selected `skills/{folder}` subtree, rewrites the skill front matter `name`, and copies the full directory into the user workspace.

This preserves supporting files such as:

- scripts
- prompts
- templates
- examples

### Step 4: Skill becomes active

After import, the skill is immediately registered and available.

That means:

- it appears in the Skills page right away
- it can be selected for agent runtime right away
- shared imports become visible to other users right away

## Why The Code Is Split This Way

Skill-related code lives in two layers.

### `server/app/orchestration/skills/`

This layer contains skill-domain logic that is not responsible for persistence.

Examples:

- skill selection prompt logic
- skill file parsing helpers
- GitHub repository probing and archive download helpers

This folder is the natural place to look when you want to understand the skill concept itself.

### `server/app/services/skill_service.py`

This layer owns persistence and permission-sensitive operations.

Examples:

- filesystem writes into user workspace
- registry synchronization
- visibility filtering
- import installation into final storage

This boundary is important. File and database interactions should remain inside services so the rest of the system does not grow hidden persistence behavior.

## API Shape

The current API surface around skills is intentionally direct.

Examples:

- list shared skills
- list private skills
- read a skill source
- create or update a skill
- delete a skill
- probe GitHub import candidates
- import one GitHub skill

The API favors explicit operations over a highly generic abstraction because the current workflows are still evolving.

## Agent Integration

At runtime, skills participate in two different moments.

### Skill selection

Pivot can ask an LLM to select which skills are relevant for the current task. That selection works from compact registry metadata, not from full directory contents.

### Skill mounting / prompt injection

When a skill is selected and runtime-visible:

- its markdown content may be injected into the prompt bootstrap
- its directory may be mounted into the runtime sandbox

That is why keeping the full directory on disk matters.

## Current Constraints

The current implementation intentionally does not support:

- private GitHub repositories
- arbitrary repository layouts without `skills/`
- uploading zip/rar folders from the browser
- automatic security scanning
- reviewer assignment workflows

Those are future extensions, not accidental omissions.

## Practical Guidance For Contributors

If you want to change the skill system, start with these questions:

1. Is this a skill-domain concern, or a persistence concern?
2. Does this affect management visibility, runtime visibility, or both?
3. Does this keep the directory-based package model intact?
4. Does this preserve global uniqueness for skill names?

When in doubt:

- put parsing/probing logic under `server/app/orchestration/skills/`
- put filesystem and database writes in `server/app/services/skill_service.py`

That keeps the skill system easy to navigate and easy to evolve.
