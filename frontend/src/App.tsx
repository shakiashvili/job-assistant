import React, { useState, useEffect, Suspense, lazy } from 'react';
import { Bot } from 'lucide-react';
import { Navbar, NavTab } from './components/Navbar';
import { AuthModal } from './components/AuthModal';
import { BACKEND_ORIGIN, fetchHealth, fetchCurrentUser, logoutUser } from './services/api';
import { UserProfile } from './types';

const AuditPanel = lazy(() => import('./components/AuditPanel').then((m) => ({ default: m.AuditPanel })));
const ProfileVault = lazy(() => import('./components/ProfileVault').then((m) => ({ default: m.ProfileVault })));
const CVVariantManager = lazy(() => import('./components/CVVariantManager').then((m) => ({ default: m.CVVariantManager })));
const ApplicationTracker = lazy(() => import('./components/ApplicationTracker').then((m) => ({ default: m.ApplicationTracker })));
const ActionPlanView = lazy(() => import('./components/ActionPlanView').then((m) => ({ default: m.ActionPlanView })));
const AdminDashboard = lazy(() => import('./components/AdminDashboard').then((m) => ({ default: m.AdminDashboard })));

const LoadingSkeleton: React.FC<{ fullScreen?: boolean }> = ({ fullScreen = false }) => (
  <div
    className={
      fullScreen
        ? 'min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center p-6'
        : 'w-full space-y-4 animate-pulse'
    }
    aria-busy="true"
    aria-label="Loading workspace"
  >
    <div className={fullScreen ? 'w-full max-w-md space-y-4 animate-pulse' : 'w-full space-y-4'}>
      <div className="h-10 rounded-2xl bg-slate-900/90 border border-slate-800/80" />
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="h-28 rounded-2xl bg-slate-900/80 border border-slate-800/70" />
        <div className="h-28 rounded-2xl bg-slate-900/80 border border-slate-800/70" />
        <div className="h-28 rounded-2xl bg-slate-900/80 border border-slate-800/70" />
      </div>
      <div className="h-56 rounded-2xl bg-slate-900/70 border border-slate-800/60" />
    </div>
  </div>
);

class TabErrorBoundary extends React.Component<
  { children: React.ReactNode; onReset: () => void },
  { error: Error | null }
> {
  constructor(props: { children: React.ReactNode; onReset: () => void }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="bg-slate-900 border border-rose-800/60 rounded-2xl p-6 text-center space-y-3">
          <h3 className="text-base font-bold text-rose-300">A view error occurred</h3>
          <p className="text-xs text-slate-400">{this.state.error.message}</p>
          <button
            onClick={() => {
              this.setState({ error: null });
              this.props.onReset();
            }}
            className="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold"
          >
            Recover View
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>('audit');
  const [backendHealth, setBackendHealth] = useState<{ connected: boolean; model: string; mode: string } | null>(null);
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [isAuthChecking, setIsAuthChecking] = useState<boolean>(() =>
    Boolean(localStorage.getItem('talentflow_token') || localStorage.getItem('talentflow_refresh_token'))
  );
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);

  useEffect(() => {
    if (!document.hidden) {
      checkHealth();
    }
    checkCurrentUser();

    let timer: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (!timer) {
        timer = setInterval(() => {
          if (!document.hidden) {
            checkHealth();
          }
        }, 30000);
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

    const handleAuthExpired = () => {
      syncAuthToExtension(null);
      setCurrentUser(null);
      setIsAuthChecking(false);
    };

    startPolling();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('talentflow:auth-expired', handleAuthExpired);

    return () => {
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('talentflow:auth-expired', handleAuthExpired);
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

  const syncAuthToExtension = (user: UserProfile | null) => {
    try {
      if (user) {
        const token = localStorage.getItem('talentflow_token') || '';
        const refreshToken = localStorage.getItem('talentflow_refresh_token') || '';
        if (!token && !refreshToken) return;
        window.postMessage(
          {
            type: 'TALENTFLOW_AUTH_SYNC',
            token,
            refreshToken,
            apiBaseUrl: BACKEND_ORIGIN || window.location.origin,
            userEmail: user.email,
            userName: user.full_name,
          },
          window.location.origin
        );
      } else {
        window.postMessage({ type: 'TALENTFLOW_AUTH_LOGOUT' }, window.location.origin);
      }
    } catch {
      // Non-fatal if messaging unavailable
    }
  };

  const checkCurrentUser = async () => {
    const token = localStorage.getItem('talentflow_token');
    const refreshToken = localStorage.getItem('talentflow_refresh_token');
    if (!token && !refreshToken) {
      setIsAuthChecking(false);
      return;
    }
    setIsAuthChecking(true);
    try {
      const user = await fetchCurrentUser();
      setCurrentUser(user);
      syncAuthToExtension(user);
    } catch (err: any) {
      const status = err?.status;
      // Preserve tokens on transient 5xx / cold-start network errors; only clear on confirmed 401/403
      if (status === 401 || status === 403) {
        logoutUser();
        syncAuthToExtension(null);
      }
      setCurrentUser(null);
    } finally {
      setIsAuthChecking(false);
    }
  };

  const handleLogout = () => {
    logoutUser();
    syncAuthToExtension(null);
    setCurrentUser(null);
    if (activeTab === 'admin') {
      setActiveTab('tracker');
    }
  };

  if (isAuthChecking) {
    return <LoadingSkeleton fullScreen />;
  }

  // Zero-Data Gate: Unauthenticated users see ONLY the login / OTP authentication screen.
  // No vacancies, no application cards, and no profiles can render before authentication.
  if (!currentUser) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center p-4 relative overflow-hidden">
        {/* Glow ambient decoration */}
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-sky-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Brand Header */}
        <div className="mb-6 text-center space-y-2 relative z-10">
          <div className="inline-flex items-center gap-2.5 px-3.5 py-1.5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-sky-500 via-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/25">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <span className="font-extrabold text-base text-white tracking-tight">TalentFlow AI</span>
            <span className="text-[10px] font-bold uppercase tracking-wider bg-sky-950 text-sky-300 border border-sky-800 px-2 py-0.5 rounded-full">
              Mobile Pro v3.0
            </span>
          </div>
          <h1 className="text-xl sm:text-2xl font-extrabold text-white">Sign In to Your Career Portal</h1>
          <p className="text-xs text-slate-400 max-w-sm mx-auto">
            Autonomous multi-portal job hunter & application stager. Sign in via passwordless email OTP to scan live vacancies and tailored CVs.
          </p>
        </div>

        <AuthModal
          isOpen={true}
          onClose={() => {}}
          isGate={true}
          onAuthSuccess={(user) => {
            setCurrentUser(user);
            syncAuthToExtension(user);
            if (user.is_admin) {
              setActiveTab('admin');
            }
          }}
        />
      </div>
    );
  }

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
        <TabErrorBoundary key={activeTab} onReset={() => setActiveTab('audit')}>
          <Suspense fallback={<LoadingSkeleton />}>
            {activeTab === 'tracker' && <ApplicationTracker />}
            {activeTab === 'audit' && <AuditPanel />}
            {activeTab === 'plans' && <ActionPlanView />}
            {activeTab === 'vault' && <ProfileVault />}
            {activeTab === 'variants' && <CVVariantManager />}
            {activeTab === 'admin' && <AdminDashboard currentUser={currentUser} />}
          </Suspense>
        </TabErrorBoundary>
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
          syncAuthToExtension(user);
          if (user.is_admin) {
            setActiveTab('admin');
          }
        }}
      />
    </div>
  );
};

export default App;
