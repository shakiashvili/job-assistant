import React, { useState, useEffect } from 'react';
import { Navbar, NavTab } from './components/Navbar';
import { AuditPanel } from './components/AuditPanel';
import { ProfileVault } from './components/ProfileVault';
import { CVVariantManager } from './components/CVVariantManager';
import { ApplicationTracker } from './components/ApplicationTracker';
import { ActionPlanView } from './components/ActionPlanView';
import { AdminDashboard } from './components/AdminDashboard';
import { AuthModal } from './components/AuthModal';
import { fetchHealth, fetchCurrentUser, logoutUser } from './services/api';
import { UserProfile } from './types';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>('tracker');
  const [backendHealth, setBackendHealth] = useState<{ connected: boolean; model: string; mode: string } | null>(null);
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);

  useEffect(() => {
    checkHealth();
    checkCurrentUser();

    let timer: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (!timer) {
        timer = setInterval(() => {
          if (!document.hidden) {
            checkHealth();
          }
        }, 8000);
      }
    };

    const stopPolling = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopPolling();
      } else {
        checkHealth();
        startPolling();
      }
    };

    startPolling();
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  const checkHealth = async () => {
    try {
      const data = await fetchHealth();
      setBackendHealth({
        connected: data.gemini.connected,
        model: data.gemini.model,
        mode: data.gemini.mode,
      });
    } catch {
      setBackendHealth(null);
    }
  };

  const checkCurrentUser = async () => {
    const token = localStorage.getItem('talentflow_token');
    if (!token) return;
    try {
      const user = await fetchCurrentUser();
      setCurrentUser(user);
    } catch {
      logoutUser();
      setCurrentUser(null);
    }
  };

  const handleLogout = () => {
    logoutUser();
    setCurrentUser(null);
    if (activeTab === 'admin') {
      setActiveTab('tracker');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        backendHealth={backendHealth}
        currentUser={currentUser}
        onOpenAuth={() => setIsAuthModalOpen(true)}
        onLogout={handleLogout}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-3 sm:px-6 lg:px-8 py-6 pb-24 lg:pb-10">
        {activeTab === 'tracker' && <ApplicationTracker />}
        {activeTab === 'audit' && <AuditPanel />}
        {activeTab === 'plans' && <ActionPlanView />}
        {activeTab === 'vault' && <ProfileVault />}
        {activeTab === 'variants' && <CVVariantManager />}
        {activeTab === 'admin' && <AdminDashboard currentUser={currentUser} />}
      </main>

      <footer className="hidden lg:block border-t border-slate-900 bg-slate-950/60 py-6 mt-12 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span>TalentFlow AI • Mobile-First Autonomous Career Accelerator & Interview Copilot</span>
          <div className="flex items-center gap-4">
            <span>FastAPI Backend :8000</span>
            <span>Vite React :5173</span>
            <span>JWT Auth & RBAC</span>
            <span>Gemini 2.5 Flash</span>
          </div>
        </div>
      </footer>

      {/* Authentication Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onAuthSuccess={(user) => {
          setCurrentUser(user);
          if (user.is_admin) {
            setActiveTab('admin');
          }
        }}
      />
    </div>
  );
};

export default App;
