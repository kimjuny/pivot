import { LogOut, Moon, Sun } from "@/lib/lucide";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/contexts/auth-core";
import { useTheme } from "@/lib/use-theme";

interface ConsumerUserMenuProps {
  isCollapsed: boolean;
}

/**
 * Workspace-local account menu anchored to the bottom of the Consumer sidebar.
 */
function ConsumerUserMenu({ isCollapsed }: ConsumerUserMenuProps) {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { theme, setTheme } = useTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";

  /**
   * Returns the user to the login entrypoint after clearing local auth state.
   */
  const handleLogout = () => {
    logout();
    navigate("/", { replace: true });
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className={`h-10 ${isCollapsed ? "w-10 px-0" : "w-full justify-start gap-3 px-3"}`}
          aria-label={user ? `User menu: ${user.username}` : "User menu"}
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
            {user?.username.charAt(0).toUpperCase() ?? "U"}
          </div>
          {!isCollapsed && (
            <div className="min-w-0 text-left">
              <div className="truncate text-sm font-medium text-foreground">
                {user?.username ?? "Workspace"}
              </div>
              <div className="text-xs text-muted-foreground">
                Account
              </div>
            </div>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={isCollapsed ? "start" : "end"}
        side="top"
        className="w-52"
      >
        <div className="px-2 py-1.5 text-sm font-medium">
          {user?.username ?? "Workspace"}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setTheme(nextTheme)}>
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </DropdownMenuItem>
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
  );
}

export default ConsumerUserMenu;
