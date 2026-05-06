# Pivot Canvas Surface

## Positioning

`canvas surface` is the second major surface category after
`workspace-editor`.

Its job is not to become a full Lovart clone in the first iteration. Its job is
to prove that Pivot can host a visual, direct-manipulation workspace where:

- the UI is owned by a surface extension
- the durable state lives in workspace files
- the agent and the surface can edit the same artifact
- images, text, and layout objects can be arranged on an infinite canvas

This makes `canvas surface` a natural extension of the existing surface model,
not a separate product line.

## Why This Should Be the Next Surface

Compared with a `pixel-agent` surface, the product shape of a canvas surface is
clearer and more immediately testable.

`pixel-agent` is still ambiguous at the product layer:

- what exactly is being visualized
- whether the value is debugging, replay, storytelling, or world-state
- what interaction model makes it better than transcript text

By contrast, the canvas surface has a simple and concrete value proposition:

- place images, text blocks, and frames on a board
- let the agent create or revise those artifacts
- let the user directly manipulate the result
- store everything in the workspace so the session stays inspectable

This means the second surface can validate the platform with less product risk.

## Goals

- Provide an infinite-canvas style workspace inside the chat dock.
- Support direct manipulation of visual nodes:
  - move
  - resize
  - rotate
  - reorder
- Support the core artifact types needed for image-first workflows:
  - image
  - text
  - frame
  - group
- Let the agent modify the same canvas document and assets through the
  workspace.
- Keep persistence service-mediated and file-backed.
- Reuse the existing surface runtime model and `@pivot/surface-core`.

## Non-Goals

- Do not attempt Lovart-level semantic editing in the first version.
- Do not build region-aware image inpainting into the canvas runtime.
- Do not build multi-user real-time collaboration in the first version.
- Do not build a general-purpose design system editor.
- Do not make the canvas surface depend on direct filesystem access from the
  browser.
- Do not introduce a special persistence model outside the service layer.

## Framework Choice

Use `Konva` with `react-konva` as the rendering and interaction foundation.

This is the recommended choice because it matches Pivot's needs better than the
alternatives:

- `Konva` is open, mature, React-friendly, and designed for interactive canvas
  applications.
- `react-konva` lets the surface stay in the same React-first development model
  as the rest of the frontend.
- The scene graph is low-level enough that Pivot can define its own document
  schema instead of inheriting a third-party app model.
- It already provides the primitives needed for MVP interaction:
  - stage
  - layer
  - group
  - text
  - image
  - transformer
  - drag and transform events

This choice intentionally optimizes for control over the document model.

We are not choosing `tldraw` for the first implementation because:

- it is more opinionated as an application framework
- its data model would pull us toward its own editor concepts
- it is not the best fit when we want Pivot-owned workspace document semantics

We are not choosing `Excalidraw` because its whiteboard model is a weaker match
for image-first layout editing.

We are not choosing `PixiJS` because it is lower-level than needed for the
first production-worthy iteration.

## Core Product Principles

- Surface code belongs to the extension package.
- Canvas data belongs to the workspace.
- The workspace document is the durable source of truth.
- All persistence is mediated by backend services.
- The surface is a visual editor, not the authority for storage semantics.
- The agent should be able to inspect and modify the same files without special
  hidden channels.
- The first iteration should prefer a clean, inspectable JSON document over a
  highly optimized binary format.

## Surface Identity

Recommended first surface package:

- package: `/extensions/extensions/canvas-editor`
- surface key: `canvas-editor`
- placement: `right_dock`

The first goal is to produce one internal sample surface that validates the
end-to-end workflow before worrying about templates or marketplace packaging.

## User Experience Summary

The canvas surface should feel like a focused visual workbench inside the chat
dock.

Recommended initial layout:

- top bar:
  - document title
  - zoom controls
  - undo / redo
  - export
- left rail:
  - layer list
  - asset list
- center:
  - infinite canvas viewport
- right inspector:
  - selected node properties

The interaction model should prioritize clarity over feature breadth.

Recommended first interactions:

- click to select
- shift-click for multi-select
- drag to move
- transformer handles for resize and rotate
- wheel or trackpad to zoom
- space-drag or middle-button drag to pan
- keyboard delete to remove selected nodes
- keyboard shortcuts:
  - copy
  - paste
  - undo
  - redo
  - bring forward / send backward

## Workspace Data Model

The canvas surface should use a file-backed document model under the workspace.

Recommended MVP layout:

```text
/workspace/.pivot/apps/canvas/
  document.json
  assets/
    asset-001.png
    asset-002.webp
  exports/
    export-20260423-120501.png
```

This keeps the first iteration simple:

- one canvas document per workspace
- one document file
- one asset directory
- one export directory

If Pivot later needs multiple canvas documents, it can move to:

```text
/workspace/.pivot/apps/canvas/
  documents/
    canvas-1/
      document.json
      assets/
      exports/
```

That future expansion should not require changing the scene node schema itself.

## Document Schema

Use one JSON document as the canonical scene description.

Recommended MVP schema shape:

```json
{
  "version": 1,
  "document_id": "default",
  "title": "Canvas",
  "created_at": "2026-04-23T12:00:00Z",
  "updated_at": "2026-04-23T12:05:00Z",
  "revision": 12,
  "scene": {
    "width": 4000,
    "height": 4000,
    "background": {
      "type": "solid",
      "color": "#F7F4EE"
    },
    "nodes": []
  }
}
```

Recommended node types for MVP:

- `frame`
- `text`
- `image`
- `group`

Suggested TypeScript shape:

```ts
type CanvasNodeType = "frame" | "text" | "image" | "group";

type CanvasPoint = {
  x: number;
  y: number;
};

type CanvasSize = {
  width: number;
  height: number;
};

type CanvasTransform = {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  opacity: number;
};

type CanvasBaseNode = {
  id: string;
  type: CanvasNodeType;
  name: string;
  parent_id: string | null;
  z_index: number;
  locked: boolean;
  visible: boolean;
  transform: CanvasTransform;
};

type FrameNode = CanvasBaseNode & {
  type: "frame";
  fill: string;
  stroke: string | null;
  stroke_width: number;
  corner_radius: number;
};

type TextNode = CanvasBaseNode & {
  type: "text";
  text: string;
  font_family: string;
  font_size: number;
  font_weight: number;
  line_height: number;
  letter_spacing: number;
  color: string;
  align: "left" | "center" | "right";
};

type ImageNode = CanvasBaseNode & {
  type: "image";
  asset_path: string;
  fit: "contain" | "cover" | "fill";
  corner_radius: number;
};

type GroupNode = CanvasBaseNode & {
  type: "group";
};
```

Design notes:

- `revision` exists to support optimistic updates and conflict detection.
- `scene.width` and `scene.height` describe an initial working area, not a hard
  clipping boundary.
- Viewport state is not part of the canonical workspace document.
- Selection state is not part of the canonical workspace document.

The surface may persist small local UI preferences in browser storage, but the
business artifact should stay in workspace files.

## Asset Model

Binary assets should live beside the document, not inside it.

Recommended metadata strategy:

- store the asset file in `assets/`
- store only references in `document.json`
- let the surface resolve display URLs through the generic workspace file
  contract

The document should reference images by stable workspace-relative file path:

```json
{
  "id": "node-image-1",
  "type": "image",
  "asset_path": ".pivot/apps/canvas/assets/asset-001.png",
  "name": "Moodboard image",
  "parent_id": null,
  "z_index": 30,
  "locked": false,
  "visible": true,
  "transform": {
    "x": 180,
    "y": 160,
    "width": 720,
    "height": 960,
    "rotation": 0,
    "opacity": 1
  },
  "fit": "cover",
  "corner_radius": 24
}
```

## Persistence Model

All persistent reads and writes must go through backend services under
`server/app/service`.

The surface should reason about logical workspace-relative paths, not raw host
filesystem locations.

For MVP, Pivot should avoid introducing canvas-specific persistence endpoints.

Instead, canvas should be built on top of a more generic workspace artifact
contract exposed through the surface session.

Recommended generic file capabilities:

- `listDirectory(path)`
- `readTextFile(path)`
- `writeTextFile(path, content, expectedRevision?)`
- `createDirectory(path)`
- `deletePath(path)`
- `getFileUrl(path)`
- `writeBinaryFile(path, file)`
- `watch(path)`

The canvas-specific logic should live in:

- the document schema under `.pivot/apps/canvas/document.json`
- the surface UI
- optional server-side validation helpers used by agents or future workflows

This keeps the platform contract reusable for future non-canvas surfaces.

## Surface API Contract

The canvas surface should reuse the existing surface session model.

For MVP, the surface should use generic workspace file endpoints through
`@pivot/surface-core`.

Recommended endpoints:

```text
GET  /api/chat-surfaces/{mode}-sessions/{surface_session_id}/files/directory
POST /api/chat-surfaces/{mode}-sessions/{surface_session_id}/files/directory
GET  /api/chat-surfaces/{mode}-sessions/{surface_session_id}/files/text
PUT  /api/chat-surfaces/{mode}-sessions/{surface_session_id}/files/text
GET  /api/chat-surfaces/{mode}-sessions/{surface_session_id}/files/blob
POST /api/chat-surfaces/{mode}-sessions/{surface_session_id}/files/blob
DELETE /api/chat-surfaces/{mode}-sessions/{surface_session_id}/files/path
```

Recommended canvas file contract:

```text
.pivot/apps/canvas/document.json
.pivot/apps/canvas/assets/*
.pivot/apps/canvas/exports/*
```

Recommended usage:

- load the canvas scene with `readTextFile(".pivot/apps/canvas/document.json")`
- persist scene changes with `writeTextFile(...)`
- upload image assets with `writeBinaryFile(...)`
- display assets with `getFileUrl(path)`
- react to agent-side changes with `watch(".pivot/apps/canvas")`

## Service-Layer Architecture

Recommended backend layering:

- `WorkspaceFileService`
- surface-session authorization service
- existing workspace persistence services

Important constraint:

- file services should stay reusable and CRUD-oriented
- do not create `CanvasDocumentService` or `CanvasAssetService` just to
  compensate for missing generic file APIs

The API layer should stay thin:

- authenticate the surface session
- validate capability scope
- delegate to generic workspace file operations
- serialize the response

## Capabilities

Recommended `chat_surfaces` capabilities for the canvas surface:

```json
[
  "workspace.read",
  "workspace.write",
  "workspace.watch",
  "shell.controls"
]
```

Do not require `task.events.read` for the MVP.

That capability can be added later if the canvas begins to support live
generation progress, task overlays, or streaming placement hints.

## Interaction Model

The first interaction model should be intentionally small and polished.

### Selection

- click selects one node
- shift-click toggles node selection
- drag on empty canvas clears selection
- optional marquee selection can be added if cheap, but it is not required for
  MVP

### Transform

- selected nodes show a Konva `Transformer`
- drag moves nodes
- handles resize nodes
- rotation is supported from the same transformer controls

### Layering

- each node has a stable `z_index`
- layer reorder operations update `z_index`
- the left rail shows the same stacking order as the scene

### Pan and Zoom

- wheel zooms around the pointer
- space-drag pans
- a simple "fit to content" action is useful for recovery

### Text Editing

For MVP, text editing can use an HTML overlay editor instead of trying to make
inline Konva text editing perfect on day one.

That is the simplest path to a good result:

- double-click text node
- show positioned HTML textarea
- save back into the node on blur or confirm

### Image Placement

Image nodes are created by:

- upload from the local machine
- agent-generated assets written into the workspace
- future import from URLs if needed

The surface should create a default image node placement when a new asset
appears and the user explicitly inserts it onto the board.

## Rendering Model

Recommended Konva composition:

- one `Stage`
- separate `Layer`s for:
  - background
  - scene nodes
  - selection / guides

Use React state as the editor state authority inside the surface. Konva should
be treated as the rendering/interactivity layer, not the durable document store.

Recommended local state split:

- `document`
- `selection`
- `viewport`
- `asset metadata`
- `history stack`
- `dirty state`

## Save Model

The save model should be simple and predictable.

Recommended behavior:

- load the document once on open
- keep edits in local React state
- debounce document saves
- mark the surface dirty when local changes exist
- clear dirty state after a successful save

Recommended first save strategy:

- debounce save by 400ms to 800ms after edits settle
- also save on explicit `Cmd/Ctrl+S`
- if a save fails because of revision conflict, reload the latest document and
  ask the user to retry

For the first version, do not build operational transform or CRDT merging.

## Workspace Watch Integration

The surface should watch the canvas workspace subtree so it can react to
external changes.

Recommended root:

```text
.pivot/apps/canvas
```

Useful watch reactions:

- if `document.json` changes externally and the surface is not dirty:
  reload it
- if a new asset file appears:
  refresh the asset list
- if an export appears:
  refresh export history

If the surface is dirty and the document changes externally, prefer a clear
conflict state over trying to merge silently.

## Agent Collaboration Model

The most important part of this design is that the surface and the agent should
be able to collaborate on the same artifact.

Recommended collaboration contract:

- the agent may create or modify `document.json`
- the agent may create files in `assets/`
- the surface watches those files and updates accordingly
- the surface may save document edits back through the canvas document API

Example flows:

### Flow A: Agent creates a moodboard draft

1. User asks the agent to create a canvas composition.
2. Agent generates or gathers images.
3. Agent writes assets into `.pivot/apps/canvas/assets/`.
4. Agent updates `document.json` with image and text nodes.
5. The surface reloads and shows the composition.
6. User manually adjusts layout and exports the result.

### Flow B: User edits, then asks the agent to continue

1. User rearranges nodes in the surface.
2. Surface persists the new document revision.
3. User asks the agent to add captions or a new reference image.
4. Agent reads the updated document and appends new nodes.
5. The surface reflects the new state.

This is exactly the kind of workspace-mediated collaboration the surface model
is supposed to unlock.

## Export Model

The first export path can be client-rendered.

Recommended MVP behavior:

- surface renders the current stage to a PNG blob
- surface uploads the blob with `writeBinaryFile(".pivot/apps/canvas/exports/...")`
- backend stores the file under the workspace export directory
- export list becomes visible in the surface

This is acceptable because:

- it is simple
- it avoids introducing a server-side graphics renderer too early
- the output is still persisted through the service layer

Future export options can include:

- JPEG
- WEBP
- PDF
- server-side deterministic export

## Suggested MVP Scope

The MVP should be intentionally narrow.

Include:

- one canvas document per workspace
- load document
- save document with revision checking
- asset upload
- asset list
- insert image node
- create text node
- create frame node
- move / resize / rotate nodes
- reorder layers
- undo / redo
- zoom / pan
- export PNG
- workspace watch refresh for document and assets

Do not include:

- path drawing tools
- masking
- blend modes
- filters panel
- smart guides with full Figma-level behavior
- multi-page documents
- comments
- live multiplayer
- AI inpainting or semantic region editing

## Implementation Phases

### Phase 1: File-Backed Canvas Loop

Goal:

- prove that a visual surface can load, edit, and save a workspace-backed canvas
  artifact

Scope:

- create `/extensions/extensions/canvas-editor`
- build a React surface using `Konva` and `react-konva`
- add canvas document and asset APIs
- add default document bootstrap on first open
- support text, image, and frame nodes
- support save, reload, watch, and export

Success criteria:

- a new workspace can open the canvas surface without manual setup
- a user can upload an image and place it on the board
- a user can add text and frames
- the surface persists the document through service APIs
- the agent can modify the same document and assets
- the surface reflects external updates correctly

### Phase 2: Better Editing Ergonomics

Goal:

- make the canvas feel good enough for frequent use

Scope:

- multi-select
- group / ungroup
- duplicate
- alignment actions
- fit-to-content
- better keyboard shortcuts
- richer inspector controls

### Phase 3: Agent-Native Visual Workflows

Goal:

- make the canvas a first-class output surface for creative agents

Scope:

- generation placeholders
- asset insertion hints
- explicit "insert result onto canvas" actions
- optional task progress overlays
- optional preview of agent-proposed layout changes before apply

This is where the product can begin to move toward Lovart-like workflows
without pretending the first version needs to do all of that.

## Recommended SDK Direction

The MVP can use `surface.fetch()` directly for canvas-specific endpoints.

After the first surface is stable, add a higher-level helper to
`@pivot/surface-core`.

Recommended eventual helper shape:

```ts
type SurfaceCanvasApi = {
  getDocument(): Promise<CanvasDocument>;
  updateDocument(
    input: UpdateCanvasDocumentInput,
  ): Promise<CanvasDocumentResponse>;
  listAssets(): Promise<CanvasAsset[]>;
  uploadAsset(file: File): Promise<CanvasAsset>;
  deleteAsset(assetId: string): Promise<void>;
  createExport(input: CreateCanvasExportInput): Promise<CanvasExport>;
};
```

This should only be added after the first real surface validates the contract.

## Open Questions

- Should the first document be auto-created silently on first open, or should
  the user explicitly create the canvas artifact?
- Should asset upload metadata include original filenames, mime types, and image
  dimensions in a separate index file, or only in service responses?
- Should export history be represented only by files in `exports/`, or also by
  a small metadata manifest for faster listing?
- Should the surface support one default background only, or should background
  images be first-class from the beginning?

## Recommendation

Build `canvas surface` now as a focused, file-backed visual document editor
using `Konva` and `react-konva`.

Do not frame it as "build Lovart." Frame it as:

- a workspace-backed infinite canvas
- direct manipulation of visual nodes
- agent and user collaboration on the same document

That is both simpler and more aligned with Pivot's platform architecture.
