import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App'
import LLMList from './components/LLMList'
import Navigation from './components/Navigation'
import LoginModal from './components/LoginModal'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from '@/components/ui/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import './index.css'

/**
 * LLM List Page wrapper with Navigation and login modal.
 */
function LLMListPage() {
  const [isLoginModalOpen, setIsLoginModalOpen] = React.useState(false);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navigation onLoginClick={() => setIsLoginModalOpen(true)} />
      <LLMList />
      <LoginModal open={isLoginModalOpen} onOpenChange={setIsLoginModalOpen} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="pivot-ui-theme">
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<App />} />
            <Route path="/agent/:agentId" element={<App />} />
            <Route path="/llms" element={<LLMListPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)

