import { Github, Inbox } from 'lucide-react';

function Navigation() {
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
            className="nav-hover-effect flex items-center space-x-2 text-dark-text-secondary hover:text-dark-text-primary transition-colors px-2 py-1 rounded"
          >
            <Github className="w-4 h-4" />
            <span className="text-sm font-medium">23.4K</span>
          </a>

          <button className="nav-hover-effect flex items-center text-dark-text-secondary hover:text-dark-text-primary transition-colors px-2 py-1 rounded">
            <Inbox className="w-4 h-4" />
          </button>

          <div className="flex items-center">
            <div className="w-8 h-8 rounded-full bg-dark-border-light flex items-center justify-center text-dark-text-secondary">
              <span className="text-sm font-medium">U</span>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}

export default Navigation;
