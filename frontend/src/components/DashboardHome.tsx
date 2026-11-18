import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  Compass,
  FileText,
  User,
  Calendar,
  TrendingUp,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Bookmark,
  RefreshCw,
  ArrowRight,
  Cpu,
} from 'lucide-react';
import { fetchCandidateAnalytics } from '../services/api';
import { CandidateAnalyticsResponse, UserProfile } from '../types';
import { NavTab } from './Navbar';

interface DashboardHomeProps {
  user: UserProfile;
  onNavigate: (tab: NavTab) => void;
}

export const DashboardHome: React.FC<DashboardHomeProps> = ({ user, onNavigate }) => {
  const [analytics, setAnalytics] = useState<CandidateAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAnalytics = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCandidateAnalytics();
      setAnalytics(data);
    } catch (err: any) {
      setError(err?.message || 'Unable to load dashboard analytics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalytics();
  }, []);

  if (loading && !analytics) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-28 rounded-2xl bg-slate-900/90 border border-slate-800" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="h-28 rounded-2xl bg-slate-900/80 border border-slate-800" />
          <div className="h-28 rounded-2xl bg-slate-900/80 border border-slate-800" />
          <div className="h-28 rounded-2xl bg-slate-900/80 border border-slate-800" />
          <div className="h-28 rounded-2xl bg-slate-900/80 border border-slate-800" />
        </div>
        <div className="h-56 rounded-2xl bg-slate-900/70 border border-slate-800" />
      </div>
    );
  }

  const completeness = analytics?.completeness_score ?? 0;
  const missingFields = analytics?.missing_fields ?? [];
  const tierBreakdown = analytics?.tier_breakdown ?? {};
  const upcomingInterviews = analytics?.upcoming_interviews ?? [];

  return (
    <div className="space-y-6">
      {/* Hero Greeting & Profile Completeness Meter */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
        <div className="space-y-2 max-w-2xl">
          <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800/70">
            <LayoutDashboard className="w-3.5 h-3.5" />
            <span>Career Command Center</span>
          </div>
          <h1 className="text-xl sm:text-2xl font-extrabold text-white">
            Welcome back, {user.full_name || user.email}
          </h1>
          <p className="text-xs sm:text-sm text-slate-400">
            Track profile readiness, matched vacancies, tailored CVs, and active applications across every portal.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4">
          <div className="bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 min-w-[240px] space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400 font-semibold">Profile Completeness</span>
              <span
                className={`font-extrabold ${
                  completeness >= 80
                    ? 'text-emerald-400'
                    : completeness >= 50
                    ? 'text-amber-300'
                    : 'text-rose-400'
                }`}
              >
                {completeness}%
              </span>
            </div>
            <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  completeness >= 80
                    ? 'bg-emerald-500'
                    : completeness >= 50
                    ? 'bg-amber-500'
                    : 'bg-rose-500'
                }`}
                style={{ width: `${Math.min(100, Math.max(4, completeness))}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span>{analytics?.profile_uploaded ? 'CV / Profile Synced' : 'No CV uploaded yet'}</span>
              <button
                type="button"
                onClick={() => onNavigate('vault')}
                className="text-emerald-400 hover:text-emerald-300 font-semibold"
              >
                {analytics?.profile_uploaded ? 'Edit Vault' : 'Upload CV'} →
              </button>
            </div>
          </div>

          <button
            type="button"
            onClick={loadAnalytics}
            disabled={loading}
            className="flex items-center justify-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-950/40 border border-rose-800 text-xs text-rose-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <button
          type="button"
          onClick={() => onNavigate('audit')}
          className="text-left p-5 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-emerald-500/60 transition-all space-y-2"
        >
          <div className="flex items-center justify-between text-slate-300 text-xs font-semibold uppercase">
            <span>Matching Jobs</span>
            <Compass className="w-4 h-4 text-emerald-400" aria-hidden="true" />
          </div>
          <div className="text-3xl font-extrabold text-white font-mono">{analytics?.matching_jobs_count ?? 0}</div>
          <div className="text-[11px] text-slate-300">
            Remote B2B: <strong className="text-emerald-300">{analytics?.remote_b2b_matches_count ?? 0}</strong> &bull; Georgia Local:{' '}
            <strong className="text-cyan-300">{analytics?.local_georgia_matches_count ?? 0}</strong> &bull; Direct: {tierBreakdown.DIRECT ?? 0}
          </div>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('tracker')}
          className="text-left p-5 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-emerald-600/60 transition-all space-y-2"
        >
          <div className="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase">
            <span>Active Pipeline</span>
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-3xl font-extrabold text-white">{analytics?.active_applications_count ?? 0}</div>
          <div className="text-[11px] text-emerald-400 font-medium">
            {analytics?.applied_count ?? 0} submitted • {analytics?.response_rate_pct ?? 0}% response rate
          </div>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('tracker')}
          className="text-left p-5 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-indigo-600/60 transition-all space-y-2"
        >
          <div className="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase">
            <span>Interviews & Offers</span>
            <Calendar className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-3xl font-extrabold text-white">{analytics?.interviews_count ?? 0}</div>
          <div className="text-[11px] text-indigo-300">
            {analytics?.offers_count ?? 0} offer(s) recorded
          </div>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('audit')}
          className="text-left p-5 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-amber-600/60 transition-all space-y-2"
        >
          <div className="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase">
            <span>Saved Bookmarks</span>
            <Bookmark className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-3xl font-extrabold text-white">{analytics?.saved_jobs_count ?? 0}</div>
          <div className="text-[11px] text-slate-400 flex items-center gap-1">
            <Cpu className="w-3 h-3 text-emerald-400" />
            <span>{analytics?.detected_industry || 'Domain Auto-Detected'}</span>
          </div>
        </button>
      </div>

      {/* Actionable Checklist + Upcoming Interviews */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Missing Fields & Recommended Next Actions */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-emerald-400" />
              <span>Recommended Next Actions</span>
            </h2>
            {missingFields.length === 0 && analytics?.profile_uploaded && (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 font-semibold">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Profile Complete</span>
              </span>
            )}
          </div>

          {!analytics?.profile_uploaded ? (
            <div className="p-4 rounded-xl bg-amber-950/30 border border-amber-800/60 space-y-3">
              <p className="text-xs text-amber-200 leading-relaxed">
                Upload your CV (<code>.pdf</code>, <code>.docx</code>, <code>.md</code>, or <code>.txt</code>) in the
                Profile Vault so matching, salary alignment, and tailored resume generation reflect your actual history.
              </p>
              <button
                type="button"
                onClick={() => onNavigate('vault')}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white text-xs font-semibold"
              >
                <User className="w-3.5 h-3.5" />
                <span>Upload CV in Profile Vault</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : missingFields.length > 0 ? (
            <div className="space-y-2.5">
              <p className="text-xs text-slate-400">
                Complete these missing Ground Truth fields to eliminate application form gaps and improve match precision:
              </p>
              <div className="flex flex-wrap gap-2">
                {missingFields.map((field) => (
                  <button
                    key={field}
                    type="button"
                    onClick={() => onNavigate('vault')}
                    className="px-2.5 py-1 rounded-lg bg-amber-950/50 border border-amber-800/70 text-amber-200 text-xs hover:bg-amber-900/50"
                  >
                    + Add {field}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <button
                type="button"
                onClick={() => onNavigate('audit')}
                className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-emerald-500/60 text-left space-y-1 transition-all"
              >
                <div className="text-xs font-bold text-white flex items-center gap-1.5">
                  <Compass className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />
                  <span>Scan Live Portals</span>
                </div>
                <p className="text-[11px] text-slate-300">Fetch &amp; score local Georgian &amp; remote B2B roles.</p>
              </button>

              <button
                type="button"
                onClick={() => onNavigate('b2b')}
                className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-cyan-500/60 text-left space-y-1 transition-all"
              >
                <div className="text-xs font-bold text-white flex items-center gap-1.5">
                  <TrendingUp className="w-3.5 h-3.5 text-cyan-400" aria-hidden="true" />
                  <span>1% B2B &amp; Timezones</span>
                </div>
                <p className="text-[11px] text-slate-300">Calculate net GEL/USD &amp; UTC+4 remote overlap.</p>
              </button>

              <button
                type="button"
                onClick={() => onNavigate('variants')}
                className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-emerald-500/60 text-left space-y-1 transition-all"
              >
                <div className="text-xs font-bold text-white flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />
                  <span>Open CV Studio</span>
                </div>
                <p className="text-[11px] text-slate-300">Edit sections live and export ATS Word (.docx) + PDF.</p>
              </button>
            </div>
          )}
        </div>

        {/* Upcoming Interviews */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Calendar className="w-4 h-4 text-indigo-400" />
              <span>Upcoming Interviews</span>
            </h2>
            <button
              type="button"
              onClick={() => onNavigate('tracker')}
              className="text-xs text-emerald-400 hover:text-emerald-300 font-semibold"
            >
              Open Tracker →
            </button>
          </div>

          {upcomingInterviews.length === 0 ? (
            <div className="p-6 rounded-xl bg-slate-950/80 border border-slate-800/80 text-center space-y-1.5">
              <p className="text-xs font-semibold text-slate-300">No upcoming interview rounds scheduled</p>
              <p className="text-[11px] text-slate-500">
                Schedule an interview round from any card in the Kanban Tracker to unlock AI Interview Copilot prep.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {upcomingInterviews.map((iv) => (
                <div
                  key={iv.id}
                  className="p-3 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between gap-3"
                >
                  <div>
                    <div className="text-xs font-bold text-white">{iv.round_type}</div>
                    <div className="text-[11px] text-indigo-300">
                      {iv.interviewer ? `Interviewer: ${iv.interviewer}` : `Application #${iv.application_id}`}
                    </div>
                  </div>
                  <div className="text-[11px] text-slate-400 font-mono">
                    {iv.scheduled_at ? new Date(iv.scheduled_at).toLocaleDateString() : 'TBD'}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
