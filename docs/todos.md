

1. Reset sandbox
   Problem:
   Agent sandboxes are warm and reusable, so a broken environment can persist across tasks. After failed installs, accidental file mutations, or a polluted runtime, users currently have no direct way to force a clean rebuild.

   Idea:
   Add an explicit "Reset sandbox" action for one agent. The action should destroy the current sandbox container and clear the agent-scoped sandbox state that is safe to rebuild, so the next tool execution starts from a fresh base image and workspace mounts.

2. Agent sandbox cache
   Problem:
   When an idle/LRU cleanup removes a sandbox container, package manager downloads and similar warm data are lost, so later tasks may need to re-download Python and Node packages and become much slower.

   Idea:
   Add agent-scoped persistent cache volumes for sandbox package managers, starting with pip and npm. Keep cache volumes separate from the ephemeral container lifecycle so sandbox rebuilds stay clean while repeated dependency downloads can still be reused across tasks.
