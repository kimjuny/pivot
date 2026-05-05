import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarProvider } from "@/components/ui/sidebar";

import ConsumerUserMenu from "./ConsumerUserMenu";

const logoutMock = vi.fn();
const navigateMock = vi.fn();
const setThemeMock = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

vi.mock("@/contexts/auth-core", () => ({
  useAuth: () => ({
    logout: logoutMock,
    user: {
      id: 1,
      username: "shadcn",
      role: "user",
      permissions: ["client.access"],
    },
  }),
}));

vi.mock("@/lib/use-theme", () => ({
  useTheme: () => ({
    theme: "dark" as const,
    setTheme: setThemeMock,
  }),
}));

/**
 * Renders the footer menu inside the sidebar provider it depends on.
 */
function renderConsumerUserMenu(isCollapsed: boolean = false) {
  return render(
    <SidebarProvider defaultOpen={!isCollapsed}>
      <ConsumerUserMenu isCollapsed={isCollapsed} />
    </SidebarProvider>,
  );
}

describe("ConsumerUserMenu", () => {
  beforeEach(() => {
    logoutMock.mockReset();
    navigateMock.mockReset();
    setThemeMock.mockReset();
  });

  it("opens the footer menu and runs the available account actions", async () => {
    const user = userEvent.setup();

    renderConsumerUserMenu();

    expect(screen.getByText("Consumer workspace")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "User menu: shadcn" }));

    expect(await screen.findByText("Light mode")).toBeInTheDocument();
    expect(screen.getAllByText("shadcn").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("menuitem", { name: "Light mode" }));
    expect(setThemeMock).toHaveBeenCalledWith("light");

    await user.click(screen.getByRole("button", { name: "User menu: shadcn" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    expect(logoutMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith("/", { replace: true });
  });

  it("keeps the collapsed footer trigger icon-only until the menu is opened", async () => {
    const user = userEvent.setup();

    renderConsumerUserMenu(true);

    expect(screen.queryByText("Consumer workspace")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "User menu: shadcn" }));

    expect(await screen.findByText("Consumer workspace")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
  });
});
