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
import { prepareInterview, fetchApplicationInterviews, updateInterviewNotes } from '../services/api';
import { InterviewBrief, PredictedQuestion } from '../types';

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
  const [brief, setBrief] = useState<InterviewBrief | null>(null);
  const [expandedQuestion, setExpandedQuestion] = useState<number | null>(null);
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
      alert(err.message || 'Failed to save reflections');
    } finally {
      setSavingNotes(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-3 sm:p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-3xl w-full max-h-[92vh] flex flex-col shadow-2xl overflow-hidden my-auto">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/80 gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center text-white flex-shrink-0 shadow-md shadow-sky-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base sm:text-lg font-bold text-white truncate">
                Interview Copilot: {companyName}
              </h2>
              <p className="text-xs text-slate-400 truncate">
                Role: <span className="text-slate-200">{jobTitle}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 flex-shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Round Selector Tabs */}
        <div className="p-3 bg-slate-950 border-b border-slate-800/80 flex items-center gap-1.5 overflow-x-auto">
          {[
            { id: 'HR_SCREEN', label: '📞 HR Screening' },
            { id: 'TECH_INTERVIEW', label: '💻 Technical QA / SDET' },
            { id: 'FINAL_ROUND', label: '🏆 Final Leadership' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setRoundType(tab.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                roundType === tab.id
                  ? 'bg-sky-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white hover:bg-slate-900'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
          {loading && (
            <div className="py-16 text-center space-y-3">
              <Sparkles className="w-8 h-8 text-sky-400 animate-spin mx-auto" />
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

          {!loading && brief && (
            <>
              {/* Company Intel Overview */}
              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                <div className="flex items-center gap-2 text-xs font-bold text-sky-400 uppercase tracking-wider">
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
                            <span className="text-[11px] font-bold text-sky-400 font-mono pt-0.5">
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
                                <span className="font-bold text-sky-400 uppercase text-[10px] block mb-0.5">
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
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white focus:outline-none focus:border-sky-500 leading-relaxed"
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
        <div className="p-4 bg-slate-950/80 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
