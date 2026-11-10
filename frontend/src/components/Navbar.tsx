import React, { useState } from 'react';
import {
  Bot,
  AlertCircle,
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
} from 'lucide-react';
import { UserProfile } from '../types';

export type NavTab = 'audit' | 'vault' | 'variants' | 'tracker' | 'plans' | 'admin';

interface NavbarProps {
  activeTab: NavTab;
  setActiveTab: (tab: NavTab) => void;
  backendHealth: { connected: boolean; model: string; mode: string } | null;
  currentUser: UserProfile | null;
  onOpenAuth: () => void;
  onLogout: () => void;
}

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
  const [copiedCmd, setCopiedCmd] = useState(false);

  const gitCommands = `cd "C:\\Users\\giorg\\.gemini\\antigravity\\scratch\\job-application-assistant"
git init
git add .
git commit -m "feat: Mobile-First Career Platform with Auth, Admin Panel & Interview Copilot"
git branch -M main
# Create a new repo on https://github.com/new then run:
git remote add origin https://github.com/YOUR_USERNAME/ai-job-application-assistant.git
git push -u origin main`;

  const handleCopyGit = () => {
    navigator.clipboard.writeText(gitCommands);
    setCopiedCmd(true);
    setTimeout(() => setCopiedCmd(false), 3000);
  };

  const navItems: Array<{ id: NavTab; label: string; icon: React.FC<{ className?: string }>; adminOnly?: boolean }> = [
    { id: 'tracker', label: 'Kanban Tracker', icon: LayoutDashboard },
    { id: 'audit', label: 'Audit & Feed', icon: Compass },
    { id: 'plans', label: 'Action Plans', icon: GraduationCap },
    { id: 'vault', label: 'Profile Vault', icon: User },
    { id: 'variants', label: 'CV Variants', icon: FileText },
    { id: 'admin', label: 'Admin Panel', icon: Shield, adminOnly: true },
  ];

  return (
    <>
      <header className="border-b border-slate-800/80 bg-slate-950/95 backdrop-blur-xl sticky top-0 z-40 shadow-lg shadow-black/20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-3">
          {/* Brand */}
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 via-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/25 flex-shrink-0">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-extrabold text-sm sm:text-base text-white tracking-tight whitespace-nowrap">
                  TalentFlow AI
                </span>
                <span className="text-[10px] font-bold uppercase tracking-wider bg-sky-950/90 text-sky-300 border border-sky-700/60 px-2 py-0.5 rounded-full whitespace-nowrap">
                  Mobile Pro v3.0
                </span>
                {currentUser?.is_admin && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-bold bg-amber-950/80 text-amber-300 border border-amber-800/60 px-2 py-0.5 rounded-full whitespace-nowrap">
                    <Shield className="w-3 h-3" />
                    Admin
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400 truncate hidden sm:block">
                Mobile-First Autonomous Job Hunter • Auth, Action Plans & Interview Copilot
              </p>
            </div>
          </div>

          {/* Desktop Navigation Tabs */}
          <nav className="hidden lg:flex items-center gap-1 bg-slate-900/90 p-1 rounded-xl border border-slate-800">
            {navItems
              .filter((item) => !item.adminOnly || currentUser?.is_admin)
              .map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => setActiveTab(item.id)}
                    className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                      isActive
                        ? 'bg-gradient-to-r from-sky-600 to-blue-600 text-white shadow-sm'
                        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/70'
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>{item.label}</span>
                  </button>
                );
              })}
          </nav>

          {/* Right Actions: User Profile / Auth Button & Mobile Menu Toggle */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsShareOpen(true)}
              className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-950/80 hover:bg-indigo-900/80 text-indigo-300 border border-indigo-700/60 text-xs font-semibold whitespace-nowrap transition-colors"
              title="Share Repository"
            >
              <Share2 className="w-3.5 h-3.5" />
              <span>Share</span>
            </button>

            {currentUser ? (
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs">
                  <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-sky-500 to-blue-600 flex items-center justify-center text-[10px] font-bold text-white uppercase">
                    {currentUser.full_name[0] || 'U'}
                  </div>
                  <span className="font-semibold text-white max-w-[100px] truncate hidden sm:inline">
                    {currentUser.full_name}
                  </span>
                </div>
                <button
                  onClick={onLogout}
                  title="Sign Out"
                  className="p-2 rounded-xl text-slate-400 hover:text-rose-400 hover:bg-slate-900 border border-transparent hover:border-slate-800"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <button
                onClick={onOpenAuth}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold shadow-md shadow-sky-600/20"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>Sign In</span>
              </button>
            )}

            {/* Mobile Menu Hamburger Toggle */}
            <button
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              className="lg:hidden p-2 rounded-xl text-slate-400 hover:text-white bg-slate-900 border border-slate-800"
              aria-label="Toggle navigation menu"
            >
              {isMobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* Mobile Dropdown Menu (on toggle) */}
        {isMobileMenuOpen && (
          <div className="lg:hidden border-t border-slate-800/80 bg-slate-950 px-4 py-3 space-y-1 animate-in fade-in slide-in-from-top-2">
            {navItems
              .filter((item) => !item.adminOnly || currentUser?.is_admin)
              .map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      setActiveTab(item.id);
                      setIsMobileMenuOpen(false);
                    }}
                    className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                      isActive
                        ? 'bg-sky-600 text-white'
                        : 'text-slate-400 hover:text-white hover:bg-slate-900'
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                    <span>{item.label}</span>
                  </button>
                );
              })}

            <div className="pt-2 border-t border-slate-900 flex items-center justify-between text-xs text-slate-400">
              <button
                onClick={() => {
                  setIsShareOpen(true);
                  setIsMobileMenuOpen(false);
                }}
                className="flex items-center gap-1.5 text-indigo-400 py-1"
              >
                <Share2 className="w-3.5 h-3.5" />
                <span>Share Repository</span>
              </button>
              {backendHealth && (
                <span className="text-[11px] text-emerald-400 font-medium">
                  ● {backendHealth.connected ? 'Gemini Active' : 'Offline'}
                </span>
              )}
            </div>
          </div>
        )}
      </header>

      {/* Mobile Bottom Navigation Bar (1-Thumb Touch Ready) */}
      <div className="lg:hidden fixed bottom-0 left-0 right-0 z-40 bg-slate-950/95 border-t border-slate-800 backdrop-blur-xl px-2 py-1.5 flex items-center justify-around shadow-2xl">
        {navItems
          .filter((item) => !item.adminOnly || currentUser?.is_admin)
          .slice(0, 5)
          .map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`flex flex-col items-center justify-center py-1 px-2 rounded-xl transition-all ${
                  isActive ? 'text-sky-400 font-bold' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Icon className={`w-4 h-4 mb-0.5 ${isActive ? 'scale-110' : ''}`} />
                <span className="text-[10px] tracking-tight">{item.label.split(' ')[0]}</span>
              </button>
            );
          })}
      </div>

      {/* Share Repository & B2B SaaS Modal */}
      {isShareOpen && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-2xl w-full p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400">
                  <Share2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">Share Your Repository & B2B SaaS Deployment Guide</h3>
                  <p className="text-xs text-slate-400">Publish to GitHub or share live with businesses & recruiters</p>
                </div>
              </div>
              <button
                onClick={() => setIsShareOpen(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4 text-xs text-slate-300">
              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-sky-400 uppercase tracking-wider text-[11px]">
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
                  <div className="font-bold text-indigo-400 flex items-center gap-1.5">
                    <Globe2 className="w-4 h-4" />
                    <span>2. Live Demo Link (Ngrok / Cloudflare)</span>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    Want to show a client or business partner right now without deploying? Run{' '}
                    <code className="text-slate-200 bg-slate-900 px-1.5 py-0.5 rounded">npx localtunnel --port 5173</code>{' '}
                    or <code className="text-slate-200 bg-slate-900 px-1.5 py-0.5 rounded">ngrok http 5173</code> to get an instant public HTTPS URL.
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
                className="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold"
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
