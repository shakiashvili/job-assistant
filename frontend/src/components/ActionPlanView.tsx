import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  CheckCircle2,
  Circle,
  ExternalLink,
  Trash2,
  GraduationCap,
  RefreshCw,
  Trophy,
  Flame,
  ArrowRight,
} from 'lucide-react';
import { fetchActionPlans, generateActionPlans, toggleMilestone, deleteActionPlan } from '../services/api';
import { SkillActionPlan } from '../types';

function isSafeHttpUrl(rawUrl?: string | null): boolean {
  if (!rawUrl) return false;
  try {
    const parsed = new URL(rawUrl.trim());
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

export const ActionPlanView: React.FC = () => {
  const [plans, setPlans] = useState<SkillActionPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadPlans();
  }, []);

  const loadPlans = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchActionPlans();
      setPlans(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load skill roadmaps.');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const data = await generateActionPlans();
      setPlans(data);
    } catch (err: any) {
      setError(err.message || 'Failed to generate new action plans.');
    } finally {
      setGenerating(false);
    }
  };

  const handleToggleMilestone = async (planId: number, index: number) => {
    // Optimistic UI update
    setPlans((prev) =>
      prev.map((p) => {
        if (p.id !== planId) return p;
        const newMilestones = [...p.milestones];
        newMilestones[index] = { ...newMilestones[index], completed: !newMilestones[index].completed };
        const completedCount = newMilestones.filter((m) => m.completed).length;
        const percent = Math.round((completedCount / newMilestones.length) * 100);
        return {
          ...p,
          milestones: newMilestones,
          progress_percent: percent,
          is_completed: percent === 100,
        };
      })
    );

    try {
      const updated = await toggleMilestone(planId, index);
      setPlans((prev) => prev.map((p) => (p.id === planId ? updated : p)));
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to update milestone status');
      loadPlans();
    }
  };

  const handleDelete = async (planId: number) => {
    setConfirmDeleteId(null);
    try {
      await deleteActionPlan(planId);
      setPlans((prev) => prev.filter((p) => p.id !== planId));
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to remove plan');
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-gradient-to-r from-slate-900 via-slate-900 to-indigo-950/70 border border-slate-800 p-6 rounded-2xl shadow-xl">
        <div className="flex items-start sm:items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 flex-shrink-0">
            <GraduationCap className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg sm:text-xl font-bold text-white">AI Skill Gap & Interactive Roadmaps</h2>
              <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">
                14-Day Accelerator
              </span>
            </div>
            <p className="text-xs text-slate-300 mt-0.5">
              Identifies missing trainable skills from market postings. Complete milestones to dynamically ingest skills into your profile.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            onClick={loadPlans}
            disabled={loading}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-sky-600 hover:from-indigo-500 hover:to-sky-500 text-white text-xs font-semibold shadow-lg shadow-indigo-600/20 transition-all disabled:opacity-50"
          >
            <Sparkles className={`w-3.5 h-3.5 ${generating ? 'animate-spin' : ''}`} />
            <span>{generating ? 'Analyzing Market...' : 'Generate AI Roadmaps'}</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-900/60 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {/* Grid of Action Plans */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {plans.map((plan) => (
          <div
            key={plan.id}
            className={`p-5 rounded-2xl border transition-all flex flex-col justify-between ${
              plan.is_completed
                ? 'bg-slate-900/90 border-emerald-500/40 shadow-lg shadow-emerald-500/10'
                : 'bg-slate-900/70 border-slate-800 hover:border-slate-700'
            }`}
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-3">
                <span className="text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-slate-950 text-indigo-400 border border-indigo-900/60">
                  {plan.category}
                </span>

                <div className="flex items-center gap-2">
                  {plan.is_completed ? (
                    <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-950/80 border border-emerald-800/80 px-2 py-0.5 rounded-full">
                      <Trophy className="w-3 h-3" />
                      Mastered & Ingested
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] text-amber-400 bg-amber-950/60 border border-amber-800/60 px-2 py-0.5 rounded-full">
                      <Flame className="w-3 h-3" />
                      {plan.days_to_learn} Days Plan
                    </span>
                  )}
                  {confirmDeleteId === plan.id ? (
                    <span className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => handleDelete(plan.id)}
                        className="px-2 py-0.5 rounded bg-rose-700 hover:bg-rose-600 text-[10px] font-bold text-white"
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(null)}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-[10px] text-slate-300"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteId(plan.id)}
                      aria-label={`Delete roadmap for ${plan.skill_name}`}
                      className="text-slate-400 hover:text-rose-400 p-1"
                      title="Delete Roadmap"
                    >
                      <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                    </button>
                  )}
                </div>
              </div>

              <h3 className="text-base font-bold text-white mb-2 leading-snug">{plan.skill_name}</h3>

              {/* Progress Bar */}
              <div className="space-y-1 mb-4">
                <div className="flex items-center justify-between text-[11px] text-slate-400 font-medium">
                  <span>Progress</span>
                  <span className={plan.is_completed ? 'text-emerald-400 font-bold' : 'text-slate-200'}>
                    {plan.progress_percent}%
                  </span>
                </div>
                <div className="w-full h-2 rounded-full bg-slate-950 overflow-hidden border border-slate-800">
                  <div
                    className={`h-full transition-all duration-500 rounded-full ${
                      plan.is_completed
                        ? 'bg-gradient-to-r from-emerald-700 to-teal-400'
                        : 'bg-gradient-to-r from-indigo-500 to-sky-400'
                    }`}
                    style={{ width: `${plan.progress_percent}%` }}
                  />
                </div>
              </div>

              {/* Milestones Checklist */}
              <div className="space-y-2 mt-4">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
                  Daily Learning Milestones
                </div>
                {plan.milestones.map((m, idx) => (
                  <div
                    key={idx}
                    className={`p-2.5 rounded-xl border transition-all flex items-start gap-2.5 text-xs ${
                      m.completed
                        ? 'bg-emerald-950/20 border-emerald-900/40 text-slate-300'
                        : 'bg-slate-950/80 border-slate-800 hover:border-slate-700 text-slate-300'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <button
                        type="button"
                        onClick={() => handleToggleMilestone(plan.id, idx)}
                        aria-pressed={Boolean(m.completed)}
                        className="w-full text-left flex items-start gap-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 rounded-md"
                      >
                        <span className="pt-0.5 flex-shrink-0">
                          {m.completed ? (
                            <CheckCircle2 className="w-4 h-4 text-emerald-400" aria-hidden="true" />
                          ) : (
                            <Circle className="w-4 h-4 text-slate-500 hover:text-slate-300" aria-hidden="true" />
                          )}
                        </span>
                        <span className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-bold text-[10px] text-indigo-400 uppercase">
                            Day {m.day}:
                          </span>
                          <span className={m.completed ? 'line-through text-slate-400' : 'text-slate-200'}>
                            {m.task}
                          </span>
                        </span>
                      </button>
                      <div className="flex flex-wrap items-center gap-2 mt-1.5 pl-6">
                        {isSafeHttpUrl(m.resource_url) && (
                          <a
                            href={m.resource_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-950/70 border border-emerald-800/70 text-[10px] text-emerald-300 hover:text-emerald-200"
                          >
                            <span>Official Docs</span>
                            <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        )}
                        {(m.youtube_videos || []).slice(0, 2).filter((yt) => isSafeHttpUrl(yt.url)).map((yt, yIdx) => (
                          <a
                            key={`yt-${yIdx}`}
                            href={yt.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-rose-950/70 border border-rose-800/70 text-[10px] text-rose-300 hover:text-rose-200"
                            title={yt.channel || 'YouTube Tutorial'}
                          >
                            <span>YouTube: {yt.title.slice(0, 28)}</span>
                            <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        ))}
                        {(m.blog_posts || []).slice(0, 2).filter((bp) => isSafeHttpUrl(bp.url)).map((bp, bIdx) => (
                          <a
                            key={`blog-${bIdx}`}
                            href={bp.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-950/70 border border-emerald-800/70 text-[10px] text-emerald-300 hover:text-emerald-200"
                            title={bp.source || 'Engineering Blog'}
                          >
                            <span>Blog: {bp.title.slice(0, 26)}</span>
                            <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        ))}
                        {!m.youtube_videos?.length && !m.blog_posts?.length && isSafeHttpUrl(m.tutorial_url) && (
                          <a
                            href={m.tutorial_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 text-[10px] text-emerald-400 hover:text-emerald-300 hover:underline"
                          >
                            <span>Tutorial</span>
                            <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {plan.is_completed && (
              <div className="mt-4 p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/60 text-emerald-300 text-xs flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                <span className="text-[11px] leading-snug">
                  Skill automatically synchronized with your active profile. All future CVs will showcase this capability.
                </span>
              </div>
            )}
          </div>
        ))}
      </div>

      {plans.length === 0 && !loading && (
        <div className="text-center py-12 border border-dashed border-slate-800 rounded-2xl space-y-3">
          <GraduationCap className="w-10 h-10 text-slate-600 mx-auto" />
          <h3 className="text-sm font-semibold text-white">No active skill gap plans</h3>
          <p className="text-xs text-slate-400 max-w-sm mx-auto">
            Click "Generate AI Roadmaps" to scan the latest market vacancies and generate custom 7-day learning roadmaps.
          </p>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-xs font-semibold text-white inline-flex items-center gap-1.5"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Generate Roadmaps</span>
          </button>
        </div>
      )}
    </div>
  );
};
