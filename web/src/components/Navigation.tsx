import { Github, Inbox } from 'lucide-react';

/**
 * Navigation bar component.
 * Displays app logo and user actions with proper accessibility support.
 */
function Navigation() {
  /**
   * Handle keyboard navigation for interactive elements.
   * Ensures buttons respond to Enter and Space keys.
   */
  const handleKeyDown = (e: React.KeyboardEvent, action: () => void) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      action();
    }
  };

  const handleInboxClick = () => {
    // TODO: Implement inbox functionality
  };

  const handleUserMenuClick = () => {
    // TODO: Implement user menu functionality
  };

  return (
    <nav className="sticky top-0 z-50 bg-dark-bg border-b border-dark-border">
      <div className="flex items-center justify-between h-12 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center">
          <img
            src="/pivot.svg"
            alt="Pivot"
            className="h-6 w-6"
          />
        </div>

        <div className="flex items-center space-x-6">
          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="nav-hover-effect flex items-center space-x-2 text-dark-text-secondary hover:text-dark-text-primary transition-colors px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg"
            aria-label="View on GitHub, 23.4K stars"
          >
            <Github className="w-4 h-4" aria-hidden="true" />
            <span className="text-sm font-medium">23.4K</span>
          </a>

          <button
            onClick={handleInboxClick}
            onKeyDown={(e) => handleKeyDown(e, handleInboxClick)}
            className="nav-hover-effect flex items-center text-dark-text-secondary hover:text-dark-text-primary transition-colors px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg"
            aria-label="View notifications"
          >
            <Inbox className="w-4 h-4" aria-hidden="true" />
          </button>

          <button
            onClick={handleUserMenuClick}
            onKeyDown={(e) => handleKeyDown(e, handleUserMenuClick)}
            className="flex items-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg rounded-full"
            aria-label="User menu"
          >
            <div className="w-8 h-8 rounded-full bg-dark-border-light flex items-center justify-center text-dark-text-secondary hover:bg-dark-border transition-colors">
              <span className="text-sm font-medium">U</span>
            </div>
          </button>
        </div>
      </div>
    </nav>
  );
}

export default Navigation;

