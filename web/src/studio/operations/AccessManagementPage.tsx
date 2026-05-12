import { useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";
import type { SVGProps } from "react";

import { hasPermission, useAuth } from "@/contexts/auth-core";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Plus, ShieldCheck, User, Users } from "lucide-react";

import GroupsPanel from "@/studio/operations/GroupsPanel";
import RolesPanel from "@/studio/operations/RolesPanel";
import UsersPanel from "@/studio/operations/UsersPanel";
import type { PanelHandle } from "@/studio/operations/UsersPanel";

type AccessTab = "users" | "groups" | "roles";

interface AccessTabConfig {
  value: AccessTab;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  permission: string;
  actionLabel: string;
}

const ALL_TABS: AccessTabConfig[] = [
  { value: "users", label: "Users", icon: User, permission: "users.manage", actionLabel: "New User" },
  { value: "groups", label: "Groups", icon: Users, permission: "groups.manage", actionLabel: "New Group" },
  { value: "roles", label: "Roles", icon: ShieldCheck, permission: "roles.manage", actionLabel: "New Role" },
];

/** Unified access management page with vertical tab sidebar for Users, Groups, and Roles. */
export default function AccessManagementPage() {
  const { user } = useAuth();

  const visibleTabs = ALL_TABS.filter((tab) =>
    hasPermission(user, tab.permission),
  );

  const [activeTab, setActiveTab] = useState<AccessTab>(
    visibleTabs[0]?.value ?? "users",
  );

  useEffect(() => {
    if (!visibleTabs.some((tab) => tab.value === activeTab)) {
      setActiveTab(visibleTabs[0]?.value ?? "users");
    }
  }, [activeTab, visibleTabs]);

  const usersRef = useRef<PanelHandle>(null);
  const groupsRef = useRef<PanelHandle>(null);
  const rolesRef = useRef<PanelHandle>(null);

  const activeTabConfig = visibleTabs.find((tab) => tab.value === activeTab);

  function handleCreate() {
    if (activeTab === "users") usersRef.current?.triggerCreate();
    else if (activeTab === "groups") groupsRef.current?.triggerCreate();
    else if (activeTab === "roles") rolesRef.current?.triggerCreate();
  }

  return (
    <ScrollArea className="h-full">
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as AccessTab)}
        orientation="vertical"
      >
        {/* Content area — same max-w-5xl mx-auto as other list pages */}
        <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              Access Management
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Manage users, groups, and role-based permissions
            </p>
          </div>
          <Button onClick={handleCreate} className="gap-2">
            <Plus className="h-4 w-4" />
            {activeTabConfig?.actionLabel ?? "New"}
          </Button>
        </div>

        <div className="relative">
          {/* Tab sidebar — absolutely positioned to the left of the content area */}
          <TabsList className="absolute -left-[11.5rem] top-0 flex h-auto w-40 flex-col items-stretch justify-start gap-1 overflow-visible rounded-none bg-transparent p-0">
            {visibleTabs.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                className="group relative h-9 justify-start gap-2 rounded-none bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              >
                <span
                  className="absolute left-0 top-1.5 h-6 w-0.5 scale-y-0 bg-foreground transition-transform duration-200 ease-out group-data-[state=active]:scale-y-100"
                  aria-hidden="true"
                />
                <tab.icon className="h-4 w-4" />
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* Content panels with fade + slide-up transition */}
          <div className="relative">
            {visibleTabs.some((t) => t.value === "users") && (
              <TabsContent value="users" forceMount className="mt-0 data-[state=inactive]:hidden data-[state=inactive]:animate-none data-[state=active]:animate-in data-[state=active]:fade-in-0 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-200">
                <UsersPanel ref={usersRef} />
              </TabsContent>
            )}
            {visibleTabs.some((t) => t.value === "groups") && (
              <TabsContent value="groups" forceMount className="mt-0 data-[state=inactive]:hidden data-[state=inactive]:animate-none data-[state=active]:animate-in data-[state=active]:fade-in-0 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-200">
                <GroupsPanel ref={groupsRef} />
              </TabsContent>
            )}
            {visibleTabs.some((t) => t.value === "roles") && (
              <TabsContent value="roles" forceMount className="mt-0 data-[state=inactive]:hidden data-[state=inactive]:animate-none data-[state=active]:animate-in data-[state=active]:fade-in-0 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-200">
                <RolesPanel ref={rolesRef} />
              </TabsContent>
            )}
          </div>
        </div>
      </div>
      </Tabs>
    </ScrollArea>
  );
}
