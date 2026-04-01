import { ChevronsUpDown, LogOut, Moon, Sun } from "@/lib/lucide";
import { useNavigate } from "react-router-dom";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useAuth } from "@/contexts/auth-core";
import { useSidebar } from "@/hooks/use-sidebar";
import { useTheme } from "@/lib/use-theme";

interface ConsumerUserMenuProps {
  isCollapsed: boolean;
}

/**
 * Workspace-local account menu styled like the shadcn sidebar footer pattern.
 *
 * Why: the bottom account entry is both identity context and a menu trigger, so
 * matching the sidebar's own menu button treatment keeps the affordance clear
 * without introducing a second interaction language just for the footer.
 */
function ConsumerUserMenu({ isCollapsed }: ConsumerUserMenuProps) {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { theme, setTheme } = useTheme();
  const { isMobile } = useSidebar();
  const nextTheme = theme === "dark" ? "light" : "dark";
  const accountName = user?.username ?? "Workspace";
  const accountSubtitle = "Consumer workspace";
  const accountInitial = accountName.charAt(0).toUpperCase();

  /**
   * Returns the user to the login entrypoint after clearing local auth state.
   */
  const handleLogout = () => {
    logout();
    navigate("/", { replace: true });
  };

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              tooltip={accountName}
              aria-label={user ? `User menu: ${user.username}` : "User menu"}
              className="h-12 gap-2 rounded-xl px-2 data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-primary text-sm font-semibold text-sidebar-primary-foreground">
                {accountInitial}
              </div>
              {!isCollapsed ? (
                <div className="grid min-w-0 flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold text-sidebar-foreground">
                    {accountName}
                  </span>
                  <span className="truncate text-xs text-sidebar-foreground/60">
                    {accountSubtitle}
                  </span>
                </div>
              ) : null}
              {!isCollapsed ? (
                <ChevronsUpDown className="ml-auto size-4 shrink-0 text-sidebar-foreground/70" />
              ) : null}
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
            size="large"
            className="w-[--radix-dropdown-menu-trigger-width] min-w-56 rounded-lg"
          >
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-2 px-2 py-1.5 text-left text-sm">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-primary text-sm font-semibold text-sidebar-primary-foreground">
                  {accountInitial}
                </div>
                <div className="grid min-w-0 flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold text-popover-foreground">
                    {accountName}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {accountSubtitle}
                  </span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem onSelect={() => setTheme(nextTheme)}>
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
                {theme === "dark" ? "Light mode" : "Dark mode"}
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={handleLogout}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

export default ConsumerUserMenu;
