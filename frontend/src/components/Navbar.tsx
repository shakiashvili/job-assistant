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
  Globe2
} from 'lucide-react';

interface NavbarProps {
  activeTab: 'audit' | 'vault' | 'variants' | 'tracker';
  setActiveTab: (tab: 'audit' | 'vault' | 'variants' | 'tracker') => void;
  backendHealth: { connected: boolean; model: string; mode: string } | null;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, setActiveTab, backendHealth }) => {
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState(false);

  const gitCommands = `cd "C:\\Users\\giorg\\.gemini\\antigravity\\scratch\\job-application-assistant"
git init
git add .
git commit -m "feat: Universal AI Job & CV Assistant (EN/KA + Multi-Industry)"
git branch -M main
# Create a new repo on https://github.com/new then run:
git remote add origin https://github.com/YOUR_USERNAME/ai-job-application-assistant.git
git push -u origin main`;

  const handleCopyGit = () => {
    navigator.clipboard.writeText(gitCommands);
    setCopiedCmd(true);
    setTimeout(() => setCopiedCmd(false), 3000);
  };

  return (
    <>
      <header className="border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-xl sticky top-0 z-50 shadow-lg shadow-black/20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex flex-wrap items-center justify-between gap-3">
          {/* Brand — Never wraps awkwardly or overflows */}
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
                  Enterprise HITL v2.0
                </span>
                <span className="hidden xl:inline-flex items-center gap-1 text-[10px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800/60 px-2 py-0.5 rounded-full whitespace-nowrap">
                  🇬🇧 EN / 🇬🇪 KA ქართული
                </span>
              </div>
              <p className="text-[11px] text-slate-400 truncate">
                Universal Multi-Industry CV & Application Platform • QA, Hospitality, Customer Care & Healthcare
              </p>
            </div>
          </div>

          {/* Navigation Tabs — Scrollable on ultra-small viewports, crisp pills on desktop */}
          <nav className="flex items-center gap-1 bg-slate-900/90 p-1 rounded-xl border border-slate-800 overflow-x-auto max-w-full order-3 lg:order-2 w-full lg:w-auto justify-start sm:justify-center">
            <button
              onClick={() => setActiveTab('audit')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                activeTab === 'audit'
                  ? 'bg-gradient-to-r from-sky-600 to-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/70'
              }`}
            >
              <Compass className="w-3.5 h-3.5 flex-shrink-0" />
              <span>Audit & Stage</span>
            </button>

            <button
              onClick={() => setActiveTab('tracker')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                activeTab === 'tracker'
                  ? 'bg-gradient-to-r from-sky-600 to-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/70'
              }`}
            >
              <LayoutDashboard className="w-3.5 h-3.5 flex-shrink-0" />
              <span>Tracker Board</span>
            </button>

            <button
              onClick={() => setActiveTab('vault')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                activeTab === 'vault'
                  ? 'bg-gradient-to-r from-sky-600 to-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/70'
              }`}
            >
              <User className="w-3.5 h-3.5 flex-shrink-0" />
              <span>Profile Vault</span>
            </button>

            <button
              onClick={() => setActiveTab('variants')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                activeTab === 'variants'
                  ? 'bg-gradient-to-r from-sky-600 to-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/70'
              }`}
            >
              <FileText className="w-3.5 h-3.5 flex-shrink-0" />
              <span>CV Variants & PDFs</span>
            </button>
          </nav>

          {/* Right Actions: Share Repository Button + Backend Status */}
          <div className="flex items-center gap-2.5 order-2 lg:order-3">
            <button
              onClick={() => setIsShareOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-950/80 hover:bg-indigo-900/80 text-indigo-300 border border-indigo-700/60 text-xs font-semibold whitespace-nowrap transition-colors"
              title="How to Share Repository & B2B Pitch"
            >
              <Share2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Share Repo</span>
            </button>

            {backendHealth ? (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs whitespace-nowrap">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
                <div className="flex flex-col text-left leading-tight">
                  <span className="text-[11px] font-semibold text-slate-200 flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-sky-400 flex-shrink-0" />
                    <span>{backendHealth.connected ? 'Gemini 2.5 Flash' : 'AI Engine Ready'}</span>
                  </span>
                  <span className="text-[9px] text-slate-400 capitalize hidden sm:inline">
                    {backendHealth.mode.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-xs text-rose-400 px-3 py-1.5 rounded-xl bg-rose-950/30 border border-rose-900/50 whitespace-nowrap">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>Backend Offline</span>
              </div>
            )}
          </div>
        </div>
      </header>

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
                    Supports <strong>Tech/QA, Hospitality & Receptionists, Customer Care, and Hospitals</strong> with bilingual{' '}
                    <strong>English & Georgian (ქართული)</strong> CV synthesis, 3+ review employer verification, and Playwright autofill.
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
