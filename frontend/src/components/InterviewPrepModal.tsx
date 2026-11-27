import React, { useState, useEffect } from 'react';
import {
  X,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Building2,
  CheckCircle,
  HelpCircle,
  Save,
  Briefcase,
  AlertCircle,
  BookOpen,
} from 'lucide-react';
import {
  prepareInterview,
  updateInterviewNotes,
  submitMockInterviewAnswer,
  deleteInterviewRound,
} from '../services/api';
import { InterviewBrief, MockAnswerEvaluation } from '../types';

interface InterviewPrepModalProps {
  isOpen: boolean;
  onClose: () => void;
  appId: string;
  companyName: string;
  jobTitle: string;
}

export const InterviewPrepModal: React.FC<InterviewPrepModalProps> = ({
  isOpen,
  onClose,
  appId,
  companyName,
  jobTitle,
}) => {
  const [roundType, setRoundType] = useState<string>('HR_SCREEN');
  const [modeTab, setModeTab] = useState<'brief' | 'mock'>('brief');
  const [brief, setBrief] = useState<InterviewBrief | null>(null);
  const [expandedQuestion, setExpandedQuestion] = useState<number | null>(null);
  const [mockIndex, setMockIndex] = useState<number>(0);
  const [mockAnswerText, setMockAnswerText] = useState<string>('');
  const [mockSubmitting, setMockSubmitting] = useState<boolean>(false);
  const [latestMockEval, setLatestMockEval] = useState<MockAnswerEvaluation | null>(null);
  const [notes, setNotes] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [savingNotes, setSavingNotes] = useState<boolean>(false);
  const [notesSaved, setNotesSaved] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && appId) {
      loadInterviewBrief(roundType);
    }
  }, [isOpen, appId, roundType]);

  const loadInterviewBrief = async (round: string) => {
    setLoading(true);
    setError(null);
    setNotesSaved(false);
    try {
      const data = await prepareInterview(appId, round);
      setBrief(data);
      setNotes(data.candidate_notes || '');
      setMockIndex(0);
      setMockAnswerText('');
      setLatestMockEval(null);
      if (data.predicted_questions && data.predicted_questions.length > 0) {
        setExpandedQuestion(data.predicted_questions[0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to prepare interview intelligence.');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveNotes = async () => {
    if (!brief) return;
    setSavingNotes(true);
    try {
      await updateInterviewNotes(appId, brief.round_id, notes, brief.status);
      setNotesSaved(true);
      setTimeout(() => setNotesSaved(false), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to save reflections');
    } finally {
      setSavingNotes(false);
    }
  };

  const handleSubmitMockAnswer = async () => {
    if (!brief || !mockAnswerText.trim()) return;
    const currentQ = brief.predicted_questions[mockIndex];
    if (!currentQ) return;
    setMockSubmitting(true);
    setError(null);
    try {
      const res = await submitMockInterviewAnswer(appId, brief.round_id, currentQ.id, mockAnswerText.trim());
      setLatestMockEval(res.evaluation);
      setBrief({ ...brief, mock_progress: res.mock_progress });
    } catch (err: any) {
      setError(err.message || 'Failed to evaluate mock answer');
    } finally {
      setMockSubmitting(false);
    }
  };

  const handleDeleteSession = async () => {
    if (!brief) return;
    try {
      await deleteInterviewRound(appId, brief.round_id);
      setBrief(null);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to delete interview session');
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-3 sm:p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="interview-prep-dialog-title"
    >
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-3xl w-full max-h-[92vh] flex flex-col shadow-2xl overflow-hidden my-auto">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/80 gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-700 to-teal-700 flex items-center justify-center text-white flex-shrink-0 shadow-md shadow-emerald-500/20">
              <Sparkles className="w-5 h-5" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 id="interview-prep-dialog-title" className="text-base sm:text-lg font-bold text-white truncate">
                Interview Copilot: {companyName}
              </h2>
              <p className="text-xs text-slate-300 truncate">
                Role: <span className="text-slate-100">{jobTitle}</span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close interview preparation dialog"
            className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 flex-shrink-0"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {/* Round Selector Tabs + Brief / Mock Mode Switcher */}
        <div className="p-3 bg-slate-950 border-b border-slate-800/80 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 overflow-x-auto">
            {[
              { id: 'HR_SCREEN', label: 'HR Screening' },
              { id: 'TECH_INTERVIEW', label: 'Technical / Role' },
              { id: 'ANALYTICAL', label: 'Analytical / Case' },
              { id: 'MANAGERIAL', label: 'Managerial' },
              { id: 'FINAL_ROUND', label: 'Final Round' },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setRoundType(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                  roundType === tab.id
                    ? 'bg-emerald-700 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white hover:bg-slate-900'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800">
            <button
              type="button"
              onClick={() => setModeTab('brief')}
              className={`px-2.5 py-1 rounded text-[11px] font-semibold ${
                modeTab === 'brief' ? 'bg-slate-800 text-emerald-300' : 'text-slate-400 hover:text-white'
              }`}
            >
              Prep Brief
            </button>
            <button
              type="button"
              onClick={() => setModeTab('mock')}
              className={`px-2.5 py-1 rounded text-[11px] font-semibold ${
                modeTab === 'mock' ? 'bg-slate-800 text-cyan-300' : 'text-slate-400 hover:text-white'
              }`}
            >
              Interactive Mock ({brief?.mock_progress?.answered_count ?? 0}/{brief?.predicted_questions?.length ?? 0})
            </button>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
          {loading && (
            <div className="py-16 text-center space-y-3">
              <Sparkles className="w-8 h-8 text-emerald-400 animate-spin mx-auto" />
              <div className="text-sm font-semibold text-white">Synthesizing Company Intel & 10 Questions...</div>
              <p className="text-xs text-slate-400">Analyzing engineering stack clues and generating STAR frameworks</p>
            </div>
          )}

          {error && (
            <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-900/60 text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {!loading && brief && modeTab === 'mock' && (() => {
            const currentQ = brief.predicted_questions[mockIndex];
            const savedEval =
              latestMockEval && currentQ && latestMockEval.question_id === currentQ.id
                ? latestMockEval
                : (brief.mock_progress?.evaluations || []).find((ev) => currentQ && ev.question_id === currentQ.id) || null;
            return (
              <div className="space-y-4">
                <div className="flex items-center justify-between text-xs text-slate-300">
                  <span>
                    Question <strong>{mockIndex + 1}</strong> of <strong>{brief.predicted_questions.length}</strong>
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={mockIndex === 0}
                      onClick={() => { setMockIndex((i) => Math.max(0, i - 1)); setMockAnswerText(''); setLatestMockEval(null); }}
                      className="px-2.5 py-1 rounded-lg bg-slate-800 text-slate-200 disabled:opacity-40"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      disabled={mockIndex >= brief.predicted_questions.length - 1}
                      onClick={() => { setMockIndex((i) => Math.min(brief.predicted_questions.length - 1, i + 1)); setMockAnswerText(''); setLatestMockEval(null); }}
                      className="px-2.5 py-1 rounded-lg bg-slate-800 text-slate-200 disabled:opacity-40"
                    >
                      Next Question
                    </button>
                  </div>
                </div>
                {currentQ && (
                  <div className="p-4 rounded-xl bg-slate-950 border border-cyan-800/60 space-y-2">
                    <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                      {currentQ.category}
                    </span>
                    <div className="text-sm font-semibold text-white">{currentQ.question}</div>
                  </div>
                )}
                <textarea
                  rows={5}
                  value={mockAnswerText}
                  onChange={(e) => setMockAnswerText(e.target.value)}
                  placeholder="Write your own answer using real examples from your experience (Situation, Task, Action, Result)..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white focus:outline-none focus:border-cyan-500"
                />
                <div className="flex justify-end">
                  <button
                    type="button"
                    disabled={mockSubmitting || mockAnswerText.trim().length < 5}
                    onClick={handleSubmitMockAnswer}
                    className="px-4 py-2 rounded-xl bg-cyan-700 hover:bg-cyan-600 text-white text-xs font-semibold disabled:opacity-50"
                  >
                    {mockSubmitting ? 'Evaluating...' : 'Evaluate My Answer'}
                  </button>
                </div>
                {savedEval && (
                  <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-white">Grounded Answer Evaluation</span>
                      <span className="font-mono font-bold text-emerald-300">{savedEval.relevance_score}/100</span>
                    </div>
                    <div className="flex flex-wrap gap-2 text-[11px]">
                      {(['situation', 'task', 'action', 'result'] as const).map((k) => (
                        <span
                          key={k}
                          className={`px-2 py-0.5 rounded uppercase font-semibold ${
                            savedEval.star_coverage[k]
                              ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                              : 'bg-amber-950 text-amber-300 border border-amber-800'
                          }`}
                        >
                          {k}: {savedEval.star_coverage[k] ? 'covered' : 'missing'}
                        </span>
                      ))}
                    </div>
                    {savedEval.missing_points.length > 0 && (
                      <div className="text-amber-300 space-y-0.5">
                        <div className="font-semibold">Missing points:</div>
                        <ul className="list-disc pl-4">
                          {savedEval.missing_points.map((mp, idx) => <li key={idx}>{mp}</li>)}
                        </ul>
                      </div>
                    )}
                    <div className="text-slate-300 space-y-0.5">
                      <div className="font-semibold text-cyan-300">Coaching suggestions (without inventing experience):</div>
                      <ul className="list-disc pl-4">
                        {savedEval.improvement_suggestions.map((sg, idx) => <li key={idx}>{sg}</li>)}
                      </ul>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          {!loading && brief && modeTab === 'brief' && (
            <>
              {(brief.prep_plan && brief.prep_plan.length > 0) && (
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2 text-xs">
                  <div className="font-bold text-cyan-300 uppercase tracking-wider text-[11px]">
                    Vacancy-Specific Preparation Plan
                  </div>
                  <ul className="space-y-1 text-slate-300">
                    {brief.prep_plan.map((step, sIdx) => (
                      <li key={sIdx}>{step}</li>
                    ))}
                  </ul>
                  {brief.experience_gaps && brief.experience_gaps.length > 0 && (
                    <div className="pt-1 text-[11px] text-amber-300">
                      Potential JD Gap Topics to Prepare Honestly: <strong>{brief.experience_gaps.join(', ')}</strong>
                    </div>
                  )}
                </div>
              )}
              {/* Company Intel Overview */}
              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                <div className="flex items-center gap-2 text-xs font-bold text-emerald-400 uppercase tracking-wider">
                  <Building2 className="w-4 h-4" />
                  <span>Company Intelligence & Engineering Culture</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {brief.company_intel}
                </p>
              </div>

              {/* 10 Predicted Questions Accordion */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                    <BookOpen className="w-4 h-4 text-indigo-400" />
                    <span>10 Targeted Questions & Winning STAR Strategies</span>
                  </h3>
                  <span className="text-[11px] text-slate-400">
                    {brief.predicted_questions.length} questions prepared
                  </span>
                </div>

                <div className="space-y-2">
                  {brief.predicted_questions.map((q) => {
                    const isExpanded = expandedQuestion === q.id;
                    return (
                      <div
                        key={q.id}
                        className="rounded-xl border border-slate-800 bg-slate-950/60 overflow-hidden transition-all"
                      >
                        <button
                          type="button"
                          onClick={() => setExpandedQuestion(isExpanded ? null : q.id)}
                          className="w-full text-left p-3.5 flex items-start justify-between gap-3 hover:bg-slate-800/40"
                        >
                          <div className="flex items-start gap-2.5 min-w-0">
                            <span className="text-[11px] font-bold text-emerald-400 font-mono pt-0.5">
                              #{q.id}
                            </span>
                            <div className="min-w-0">
                              <span
                                className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded mr-2 ${
                                  q.category === 'Technical'
                                    ? 'bg-blue-950 text-blue-300 border border-blue-800'
                                    : q.category === 'Behavioral'
                                    ? 'bg-purple-950 text-purple-300 border border-purple-800'
                                    : 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                                }`}
                              >
                                {q.category}
                              </span>
                              <span className="text-xs font-semibold text-white leading-snug">
                                {q.question}
                              </span>
                            </div>
                          </div>
                          {isExpanded ? (
                            <ChevronUp className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                          ) : (
                            <ChevronDown className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                          )}
                        </button>

                        {isExpanded && q.star_strategy && (
                          <div className="p-3.5 pt-0 border-t border-slate-800/60 space-y-2 bg-slate-900/40 text-xs">
                            <div className="text-[11px] font-bold text-emerald-400 uppercase tracking-wider mb-1 pt-2">
                              STAR Framework Answer Strategy
                            </div>

                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                              <div className="p-2.5 rounded-lg bg-slate-950/80 border border-slate-800">
                                <span className="font-bold text-amber-400 uppercase text-[10px] block mb-0.5">
                                  Situation (Context)
                                </span>
                                <span className="text-slate-300 leading-relaxed">
                                  {q.star_strategy.situation}
                                </span>
                              </div>

                              <div className="p-2.5 rounded-lg bg-slate-950/80 border border-slate-800">
                                <span className="font-bold text-emerald-400 uppercase text-[10px] block mb-0.5">
                                  Task (Objective)
                                </span>
                                <span className="text-slate-300 leading-relaxed">
                                  {q.star_strategy.task}
                                </span>
                              </div>

                              <div className="p-2.5 rounded-lg bg-slate-950/80 border border-slate-800">
                                <span className="font-bold text-indigo-400 uppercase text-[10px] block mb-0.5">
                                  Action (Technical Decisions)
                                </span>
                                <span className="text-slate-300 leading-relaxed">
                                  {q.star_strategy.action}
                                </span>
                              </div>

                              <div className="p-2.5 rounded-lg bg-slate-950/80 border border-slate-800">
                                <span className="font-bold text-emerald-400 uppercase text-[10px] block mb-0.5">
                                  Result (Measurable Outcome)
                                </span>
                                <span className="text-slate-300 leading-relaxed">
                                  {q.star_strategy.result}
                                </span>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Candidate Interview Reflections Notes */}
              <div className="space-y-2 pt-2 border-t border-slate-800">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold uppercase tracking-wider text-slate-400">
                    Candidate Reflection Notes & Key Takeaways
                  </label>
                  {notesSaved && (
                    <span className="text-xs text-emerald-400 flex items-center gap-1 font-semibold">
                      <CheckCircle className="w-3.5 h-3.5" />
                      Saved
                    </span>
                  )}
                </div>
                <textarea
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Draft questions to ask the interviewer, notes on tech stack, salary negotiation points..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white focus:outline-none focus:border-emerald-500 leading-relaxed"
                />
                <div className="flex justify-end">
                  <button
                    onClick={handleSaveNotes}
                    disabled={savingNotes}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 border border-slate-700 disabled:opacity-50"
                  >
                    <Save className="w-3.5 h-3.5" />
                    <span>{savingNotes ? 'Saving...' : 'Save Reflections'}</span>
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 bg-slate-950/80 border-t border-slate-800 flex items-center justify-between gap-2">
          {brief ? (
            <button
              type="button"
              onClick={handleDeleteSession}
              className="px-3 py-2 rounded-xl bg-rose-950/60 hover:bg-rose-900/70 text-rose-300 border border-rose-800/60 font-semibold text-xs"
            >
              Delete Prep Session
            </button>
          ) : <span />}
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white font-semibold text-xs"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
