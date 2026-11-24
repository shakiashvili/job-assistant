import React, { useState, useEffect, useRef } from 'react';
import {
  Bot,
  Sparkles,
  User,
  FileText,
  LayoutDashboard,
  Compass,
  Share2,
  X,
  Check,
  Copy,
  Building2,
  Globe2,
  GraduationCap,
  Shield,
  LogIn,
  LogOut,
  Menu,
  ChevronDown,
  MoreHorizontal,
} from 'lucide-react';
import { UserProfile } from '../types';

export type NavTab = 'dashboard' | 'audit' | 'b2b' | 'tracker' | 'variants' | 'vault' | 'plans' | 'admin';

interface NavbarProps {
  activeTab: NavTab;
  setActiveTab: (tab: NavTab) => void;
  backendHealth: { connected: boolean; model: string; mode: string; provider?: string } | null;
  currentUser: UserProfile | null;
  onOpenAuth: () => void;
  onLogout: () => void;
}

interface NavItem {
  id: NavTab;
  label: string;
  shortLabel: string;
  icon: React.FC<{ className?: string }>;
  adminOnly?: boolean;
  primaryDesktop?: boolean;
  primaryMobile?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Home', shortLabel: 'Home', icon: Sparkles, primaryDesktop: true, primaryMobile: true },
  { id: 'audit', label: 'Jobs', shortLabel: 'Jobs', icon: Compass, primaryDesktop: true, primaryMobile: true },
  { id: 'tracker', label: 'Tracker', shortLabel: 'Tracker', icon: LayoutDashboard, primaryDesktop: true, primaryMobile: true },
  { id: 'variants', label: 'CV Studio', shortLabel: 'CV Studio', icon: FileText, primaryDesktop: true, primaryMobile: true },
  { id: 'vault', label: 'Profile', shortLabel: 'Profile', icon: User, primaryDesktop: true, primaryMobile: false },
  { id: 'b2b', label: 'Remote & B2B', shortLabel: 'B2B', icon: Globe2, primaryDesktop: false, primaryMobile: false },
  { id: 'plans', label: 'Action Plans', shortLabel: 'Plans', icon: GraduationCap, primaryDesktop: false, primaryMobile: false },
  { id: 'admin', label: 'Admin Panel', shortLabel: 'Admin', icon: Shield, adminOnly: true, primaryDesktop: false, primaryMobile: false },
];

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  backendHealth,
  currentUser,
  onOpenAuth,
  onLogout,
}) => {
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);

  const visibleNavItems = NAV_ITEMS.filter((item) => !item.adminOnly || currentUser?.is_admin);
  const desktopPrimary = visibleNavItems.filter((item) => item.primaryDesktop);
  const desktopSecondary = visibleNavItems.filter((item) => !item.primaryDesktop);
  const mobilePrimary = visibleNavItems.filter((item) => item.primaryMobile);
  const mobileSecondaryIds = new Set(visibleNavItems.filter((item) => !item.primaryMobile).map((i) => i.id));
  const isDesktopMoreActive = desktopSecondary.some((item) => item.id === activeTab);
  const isMobileMoreActive = mobileSecondaryIds.has(activeTab);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsMoreOpen(false);
        setIsMobileMenuOpen(false);
        setIsShareOpen(false);
      }
    };
    const onClickOutside = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setIsMoreOpen(false);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousedown', onClickOutside);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('mousedown', onClickOutside);
    };
  }, []);

  const selectTab = (tab: NavTab) => {
    setActiveTab(tab);
    setIsMoreOpen(false);
    setIsMobileMenuOpen(false);
  };

  const gitCommands = `git clone https://github.com/shakiashvili/job-assistant.git
cd job-assistant
git checkout -b my-feature-branch
git push -u origin my-feature-branch`;

  const handleCopyGit = () => {
    navigator.clipboard.writeText(gitCommands);
    setCopiedCmd(true);
    setTimeout(() => setCopiedCmd(false), 3000);
  };

  return (
    <>
      <header className="border-b border-slate-800/80 bg-slate-950/95 backdrop-blur-xl sticky top-0 z-40 shadow-lg shadow-black/20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2.5 flex items-center justify-between gap-3">
          {/* Brand */}
          <button
            type="button"
            onClick={() => selectTab('dashboard')}
            className="flex items-center gap-2.5 min-w-0 text-left rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          >
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-700 via-teal-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-emerald-500/25 flex-shrink-0">
              <Bot className="w-5 h-5 text-white" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="font-extrabold text-sm sm:text-base text-white tracking-tight whitespace-nowrap">
                  TalentFlow AI
                </span>
                {currentUser?.is_admin && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-bold bg-amber-950/80 text-amber-300 border border-amber-800/60 px-1.5 py-0.5 rounded-full whitespace-nowrap">
                    <Shield className="w-2.5 h-2.5" aria-hidden="true" />
                    Admin
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400 truncate hidden xl:block">
                Career Discovery, Tailored CVs &amp; Application Workspace
              </p>
            </div>
          </button>

          {/* Desktop Navigation: 5 Primary Links + Accessible More Menu (fits cleanly from 1024px+) */}
          <nav
            aria-label="Primary navigation"
            className="hidden lg:flex items-center gap-1 bg-slate-900/90 p-1 rounded-xl border border-slate-800"
          >
            {desktopPrimary.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => selectTab(item.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-emerald-700 to-teal-700 text-white shadow-md shadow-emerald-500/25'
                      : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
                  }`}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <Icon className="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" />
                  <span>{item.label}</span>
                </button>
              );
            })}

            <div className="relative" ref={moreRef}>
              <button
                type="button"
                onClick={() => setIsMoreOpen((v) => !v)}
                aria-expanded={isMoreOpen}
                aria-haspopup="menu"
                aria-label="More navigation sections"
                className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                  isDesktopMoreActive || isMoreOpen
                    ? 'bg-emerald-950/90 text-emerald-200 border border-emerald-700/60'
                    : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
                }`}
              >
                <span>More</span>
                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${isMoreOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
              </button>

              {isMoreOpen && (
                <div
                  role="menu"
                  aria-label="Additional workspace sections"
                  className="absolute right-0 mt-2 w-56 rounded-xl bg-slate-900 border border-slate-700 shadow-2xl p-1.5 space-y-1 z-50"
                >
                  {desktopSecondary.map((item) => {
                    const Icon = item.icon;
                    const isActive = activeTab === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="menuitem"
                        onClick={() => selectTab(item.id)}
                        aria-current={isActive ? 'page' : undefined}
                        className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                          isActive
                            ? 'bg-emerald-700/90 text-white'
                            : 'text-slate-200 hover:bg-slate-800 hover:text-white'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" />
                        <span>{item.label}</span>
                      </button>
                    );
                  })}
                  <div className="border-t border-slate-800 my-1" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setIsShareOpen(true);
                      setIsMoreOpen(false);
                    }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold text-indigo-300 hover:bg-slate-800 hover:text-indigo-200"
                  >
                    <Share2 className="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" />
                    <span>Share Repository</span>
                  </button>
                  {backendHealth && (
                    <div className="px-3 py-1.5 text-[11px] text-slate-400 flex items-center justify-between border-t border-slate-800 mt-1 pt-2">
                      <span>AI Engine</span>
                      <span className={backendHealth.connected ? 'text-emerald-400 font-semibold' : 'text-amber-400 font-semibold'}>
                        {backendHealth.connected ? (backendHealth.provider || 'Active') : 'Deterministic'}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </nav>

          {/* Right Actions: User Profile / Auth Button & Mobile Menu Toggle */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {currentUser ? (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => selectTab('vault')}
                  title="Open Profile Vault"
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs transition-colors"
                >
                  <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-emerald-700 to-teal-700 flex items-center justify-center text-[10px] font-bold text-white uppercase">
                    {(currentUser.full_name?.trim()?.[0] || currentUser.email?.[0] || 'U').toUpperCase()}
                  </div>
                  <span className="font-semibold text-white max-w-[96px] truncate hidden sm:inline">
                    {currentUser.full_name || currentUser.email || 'Candidate'}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={onLogout}
                  title="Sign Out"
                  aria-label="Sign out"
                  className="min-h-[36px] min-w-[36px] flex items-center justify-center p-2 rounded-xl text-slate-400 hover:text-rose-400 hover:bg-slate-900 border border-transparent hover:border-slate-800"
                >
                  <LogOut className="w-4 h-4" aria-hidden="true" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={onOpenAuth}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white text-xs font-semibold shadow-md shadow-emerald-600/20"
              >
                <LogIn className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Sign In</span>
              </button>
            )}

            {/* Mobile Menu Hamburger Toggle */}
            <button
              type="button"
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              className="lg:hidden min-h-[44px] min-w-[44px] flex items-center justify-center p-2 rounded-xl text-slate-300 hover:text-white bg-slate-900 border border-slate-800"
              aria-label="Toggle navigation menu"
              aria-expanded={isMobileMenuOpen}
            >
              {isMobileMenuOpen ? <X className="w-5 h-5" aria-hidden="true" /> : <Menu className="w-5 h-5" aria-hidden="true" />}
            </button>
          </div>
        </div>

        {/* Mobile Dropdown Menu (all sections always accessible) */}
        {isMobileMenuOpen && (
          <div
            role="menu"
            aria-label="All navigation sections"
            className="lg:hidden border-t border-slate-800/80 bg-slate-950/95 backdrop-blur-xl px-4 py-3 space-y-1.5"
          >
            {visibleNavItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="menuitem"
                  onClick={() => selectTab(item.id)}
                  aria-current={isActive ? 'page' : undefined}
                  className={`w-full min-h-[44px] flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-emerald-700 to-teal-700 text-white shadow-md shadow-emerald-500/20'
                      : 'text-slate-200 hover:text-white hover:bg-slate-900'
                  }`}
                >
                  <Icon className="w-4 h-4" aria-hidden="true" />
                  <span>{item.label}</span>
                </button>
              );
            })}

            <div className="pt-2 border-t border-slate-900 flex items-center justify-between text-xs text-slate-400">
              <button
                type="button"
                onClick={() => {
                  setIsShareOpen(true);
                  setIsMobileMenuOpen(false);
                }}
                className="min-h-[44px] flex items-center gap-1.5 text-indigo-400 py-1 px-2"
              >
                <Share2 className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Share Repository</span>
              </button>
              {backendHealth && (
                <span className="text-[11px] text-emerald-400 font-medium">
                  ● {backendHealth.connected ? (backendHealth.provider || 'AI Active') : 'Deterministic'}
                </span>
              )}
            </div>
          </div>
        )}
      </header>

      {/* Mobile Bottom Navigation Bar: 4 Primary Tabs + More (reveals Profile, B2B, Action Plans, Admin) */}
      <nav
        aria-label="Mobile bottom navigation"
        className="lg:hidden fixed bottom-0 left-0 right-0 z-40 bg-slate-950/95 border-t border-slate-800 backdrop-blur-xl px-1.5 py-1 flex items-center justify-around shadow-2xl"
      >
        {mobilePrimary.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => selectTab(item.id)}
              aria-current={isActive ? 'page' : undefined}
              className={`min-h-[44px] min-w-[44px] flex-1 flex flex-col items-center justify-center py-1 px-1 rounded-xl transition-all ${
                isActive ? 'text-emerald-400 font-bold bg-emerald-950/30' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Icon className={`w-4 h-4 mb-0.5 ${isActive ? 'scale-110' : ''}`} aria-hidden="true" />
              <span className="text-[10px] tracking-tight">{item.shortLabel}</span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setIsMobileMenuOpen((v) => !v)}
          aria-expanded={isMobileMenuOpen}
          aria-label="More sections"
          className={`min-h-[44px] min-w-[44px] flex-1 flex flex-col items-center justify-center py-1 px-1 rounded-xl transition-all ${
            isMobileMoreActive || isMobileMenuOpen
              ? 'text-emerald-400 font-bold bg-emerald-950/30'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <MoreHorizontal className="w-4 h-4 mb-0.5" aria-hidden="true" />
          <span className="text-[10px] tracking-tight">More</span>
        </button>
      </nav>

      {/* Share Workspace Modal */}
      {isShareOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="share-modal-title"
          onKeyDown={(e) => {
            if (e.key === 'Escape') setIsShareOpen(false);
          }}
        >
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-2xl w-full p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400">
                  <Share2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 id="share-modal-title" className="text-base font-bold text-white">Share TalentFlow &amp; Deployment Guide</h3>
                  <p className="text-xs text-slate-300">Clone or self-host your career assistant</p>
                </div>
              </div>
              <button
                type="button"
                aria-label="Close share dialog"
                onClick={() => setIsShareOpen(false)}
                className="p-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4 text-xs text-slate-300">
              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-emerald-400 uppercase tracking-wider text-[11px]">
                    1. Push Monorepo to GitHub (1-Click Commands)
                  </span>
                  <button
                    onClick={handleCopyGit}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-medium"
                  >
                    {copiedCmd ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedCmd ? 'Copied!' : 'Copy Commands'}</span>
                  </button>
                </div>
                <pre className="p-3 rounded-lg bg-slate-900/90 border border-slate-800 text-[11px] text-emerald-300 font-mono overflow-x-auto leading-relaxed">
                  {gitCommands}
                </pre>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                  <div className="font-bold text-emerald-300 flex items-center gap-1.5">
                    <Globe2 className="w-4 h-4" />
                    <span>2. Remote Tunnel Access</span>
                  </div>
                  <p className="text-[11px] text-slate-300 leading-relaxed">
                    Share a temporary HTTPS URL cleanly using{' '}
                    <code className="text-slate-100 bg-slate-900 px-1.5 py-0.5 rounded">npx localtunnel --port 5173</code>{' '}
                    or <code className="text-slate-100 bg-slate-900 px-1.5 py-0.5 rounded">ngrok http 5173</code>.
                  </p>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                  <div className="font-bold text-emerald-400 flex items-center gap-1.5">
                    <Building2 className="w-4 h-4" />
                    <span>3. Why Businesses Love TalentFlow AI</span>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    Supports <strong>Mobile-First Kanban, JWT Auth, Admin Dashboard, Skill Action Plans, Interview Copilot & Gmail Dispatch</strong> with bilingual{' '}
                    <strong>English & Georgian (ქართული)</strong> CV synthesis.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-2 border-t border-slate-800">
              <button
                onClick={() => setIsShareOpen(false)}
                className="px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white text-xs font-semibold"
              >
                Got It
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
