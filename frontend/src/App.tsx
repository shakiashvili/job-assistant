import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { AuditPanel } from './components/AuditPanel';
import { ProfileVault } from './components/ProfileVault';
import { CVVariantManager } from './components/CVVariantManager';
import { ApplicationTracker } from './components/ApplicationTracker';
import { fetchHealth } from './services/api';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'audit' | 'vault' | 'variants' | 'tracker'>('audit');
  const [backendHealth, setBackendHealth] = useState<{ connected: boolean; model: string; mode: string } | null>(null);

  useEffect(() => {
    checkHealth();

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

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        backendHealth={backendHealth}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === 'audit' && <AuditPanel />}
        {activeTab === 'tracker' && <ApplicationTracker />}
        {activeTab === 'vault' && <ProfileVault />}
        {activeTab === 'variants' && <CVVariantManager />}
      </main>

      <footer className="border-t border-slate-900 bg-slate-950/60 py-6 mt-12 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span>AI-Powered Job Application Assistant • Human-in-the-Loop Architecture</span>
          <div className="flex items-center gap-4">
            <span>FastAPI Backend :8000</span>
            <span>Vite React :5173</span>
            <span>Gemini 2.5 Flash</span>
            <span>Playwright Automated Staging</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default App;
