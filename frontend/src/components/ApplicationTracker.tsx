import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  Plus,
  ExternalLink,
  Trash2,
  Calendar,
  CalendarPlus,
  Building2,
  Download,
  ChevronRight,
  ChevronLeft,
  X,
  Clock,
  DollarSign,
  FileText,
  Edit3,
  Sparkles,
  Mail,
  Send,
  GripVertical,
  CheckCircle2,
} from 'lucide-react';
import {
  fetchApplications,
  createApplication,
  updateApplication,
  deleteApplication,
  getExportApplicationsUrl,
  fetchGoogleCalendarStatus,
  fetchGoogleOAuthConsentUrl,
  createApplicationCalendarEvent,
  BACKEND_ORIGIN,
} from '../services/api';
import { ApplicationItem, GoogleCalendarEventResponse, GoogleCalendarStatus } from '../types';
import { InterviewPrepModal } from './InterviewPrepModal';
import { EmailDispatchModal } from './EmailDispatchModal';

export const KANBAN_STAGES = [
  'Discovered',
  'Applied',
  'HR Screening',
  'Technical Interview',
  'Offer',
  'Rejected',
] as const;

const INTERVIEW_STAGES: ReadonlySet<KanbanStage> = new Set([
  'HR Screening',
  'Technical Interview',
]);

export type KanbanStage = typeof KANBAN_STAGES[number];

export const ApplicationTracker: React.FC = () => {
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);

  // Modal states for Copilot & Email
  const [prepModalApp, setPrepModalApp] = useState<ApplicationItem | null>(null);
  const [emailModalApp, setEmailModalApp] = useState<ApplicationItem | null>(null);

  // Interview Notes & Google Calendar Modal State
  const [editingApp, setEditingApp] = useState<ApplicationItem | null>(null);
  const [modalInterviewDate, setModalInterviewDate] = useState('');
  const [modalDurationMins, setModalDurationMins] = useState(45);
  const [modalNotes, setModalNotes] = useState('');
  const [calendarPrompted, setCalendarPrompted] = useState(false);
  const [calendarStatus, setCalendarStatus] = useState<GoogleCalendarStatus | null>(null);
  const [calendarResult, setCalendarResult] = useState<GoogleCalendarEventResponse | null>(null);
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [calendarErr, setCalendarErr] = useState('');

  // Drag-and-Drop State
  const [draggingAppId, setDraggingAppId] = useState<string | null>(null);
  const [dragOverStage, setDragOverStage] = useState<KanbanStage | null>(null);

  // New form state
  const [newCompany, setNewCompany] = useState('');
  const [newRole, setNewRole] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newPortal, setNewPortal] = useState('Jobs.ge');
  const [newStatus, setNewStatus] = useState<KanbanStage>('Discovered');
  const [newScore, setNewScore] = useState<number>(85);
  const [newSalary, setNewSalary] = useState('');
  const [newNotes, setNewNotes] = useState('');

  useEffect(() => {
    loadApps();
    fetchGoogleCalendarStatus()
      .then((st) => setCalendarStatus(st))
      .catch(() => setCalendarStatus(null));
  }, []);

  const loadApps = async () => {
    try {
      setIsLoading(true);
      const apps = await fetchApplications();
      setApplications(apps);
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  const normalizeStage = (status: string): KanbanStage => {
    if (status === 'Saved' || status === 'STAGED' || status === 'Discovered') return 'Discovered';
    if (status === 'Applied' || status === 'SUBMITTED') return 'Applied';
    if (status === 'HR Screening' || status === 'HR_SCREEN' || status === 'Interviewing' || status === 'INTERVIEW') return 'HR Screening';
    if (status === 'Technical Interview' || status === 'TECH_INTERVIEW' || status === 'FINAL_INTERVIEW' || status === 'Final Interview') return 'Technical Interview';
    if (status === 'Rejected' || status === 'REJECTED') return 'Rejected';
    if (status === 'Offer' || status === 'OFFER' || status === 'Offer / Rejected') return 'Offer';
    return 'Discovered';
  };

  const getDefaultTomorrowDateTimeLocal = () => {
    const dt = new Date(Date.now() + 24 * 60 * 60 * 1000);
    dt.setHours(10, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  };

  const toDateTimeLocalValue = (raw?: string | null) => {
    if (!raw) return '';
    return raw.trim().replace(' ', 'T').slice(0, 16);
  };

  const openInterviewModal = (app: ApplicationItem, suggestedFromStageMove = false) => {
    setEditingApp(app);
    const formatted = toDateTimeLocalValue(app.interview_date) || (suggestedFromStageMove ? getDefaultTomorrowDateTimeLocal() : '');
    setModalInterviewDate(formatted);
    setModalNotes(app.notes || '');
    setCalendarPrompted(suggestedFromStageMove);
    setCalendarResult(null);
    setCalendarErr('');
  };

  const moveApplicationToStage = async (appId: string, targetStage: KanbanStage) => {
    const currentApp = applications.find((a) => a.id === appId);
    if (!currentApp) return;
    const prevStage = normalizeStage(currentApp.status);
    if (prevStage === targetStage) return;

    const prevSnapshot = [...applications];
    setApplications((prev) =>
      prev.map((a) => (a.id === appId ? { ...a, status: targetStage } : a))
    );

    try {
      const updated = await updateApplication(appId, { status: targetStage });
      setApplications((prev) => prev.map((a) => (a.id === appId ? updated : a)));
      if (INTERVIEW_STAGES.has(targetStage) && !INTERVIEW_STAGES.has(prevStage)) {
        openInterviewModal(updated, true);
      }
    } catch (err) {
      console.error(err);
      setApplications(prevSnapshot);
    }
  };

  const handleStageShift = async (appId: string, currentStage: KanbanStage, direction: 'forward' | 'backward') => {
    const idx = KANBAN_STAGES.indexOf(currentStage);
    const targetIdx = direction === 'forward' ? idx + 1 : idx - 1;
    if (targetIdx < 0 || targetIdx >= KANBAN_STAGES.length) return;
    await moveApplicationToStage(appId, KANBAN_STAGES[targetIdx]);
  };

  const handleDragStartCard = (e: React.DragEvent, appId: string) => {
    setDraggingAppId(appId);
    e.dataTransfer.setData('text/plain', appId);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragEndCard = () => {
    setDraggingAppId(null);
    setDragOverStage(null);
  };

  const handleColumnDragOver = (e: React.DragEvent, stage: KanbanStage) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragOverStage !== stage) {
      setDragOverStage(stage);
    }
  };

  const handleColumnDrop = async (e: React.DragEvent, targetStage: KanbanStage) => {
    e.preventDefault();
    const droppedId = e.dataTransfer.getData('text/plain') || draggingAppId;
    setDraggingAppId(null);
    setDragOverStage(null);
    if (droppedId) {
      await moveApplicationToStage(droppedId, targetStage);
    }
  };

  const handleDelete = async (appId: string) => {
    if (!window.confirm('Are you sure you want to delete this tracked application?')) return;
    try {
      await deleteApplication(appId);
      setApplications(applications.filter((a) => a.id !== appId));
    } catch (err) {
      console.error(err);
    }
  };

  const handleSaveInterviewModal = async () => {
    if (!editingApp) return;
    try {
      const updated = await updateApplication(editingApp.id, {
        interview_date: modalInterviewDate,
        notes: modalNotes,
      });
      setApplications((prev) => prev.map((a) => (a.id === editingApp.id ? updated : a)));
      setEditingApp(null);
    } catch (err) {
      console.error(err);
    }
  };

  const handleSyncToGoogleCalendar = async () => {
    if (!editingApp) return;
    setCalendarBusy(true);
    setCalendarErr('');
    try {
      const dtToUse = modalInterviewDate || getDefaultTomorrowDateTimeLocal();
      if (!modalInterviewDate) setModalInterviewDate(dtToUse);
      const updated = await updateApplication(editingApp.id, {
        interview_date: dtToUse,
        notes: modalNotes,
      });
      setApplications((prev) => prev.map((a) => (a.id === editingApp.id ? updated : a)));

      const resp = await createApplicationCalendarEvent(editingApp.id, {
        interview_date: dtToUse,
        duration_minutes: modalDurationMins,
        summary: `Interview (${editingApp.status}): ${editingApp.role} at ${editingApp.company}`,
        description: modalNotes || `Track stage: ${editingApp.status}\nRole: ${editingApp.role}\nCompany: ${editingApp.company}`,
      });
      setCalendarResult(resp);
    } catch (err: any) {
      setCalendarErr(err?.message || 'Could not schedule Google Calendar event.');
    } finally {
      setCalendarBusy(false);
    }
  };

  const handleConnectGoogleAccount = async () => {
    try {
      const res = await fetchGoogleOAuthConsentUrl();
      if (res?.authorization_url) {
        window.open(res.authorization_url, '_blank', 'noopener,noreferrer');
      }
    } catch (err: any) {
      setCalendarErr(err?.message || 'Failed to launch Google OAuth consent flow.');
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCompany || !newRole) return;

    try {
      const created = await createApplication({
        company: newCompany,
        role: newRole,
        url: newUrl || 'https://jobs.ge',
        portal: newPortal,
        status: newStatus,
        match_score: newScore,
        salary_estimate: newSalary || undefined,
        notes: newNotes,
        applied_date: newStatus === 'Applied' ? new Date().toISOString().split('T')[0] : null,
      });

      setApplications([created, ...applications]);
      setIsAddModalOpen(false);
      setNewCompany('');
      setNewRole('');
      setNewUrl('');
      setNewSalary('');
      setNewNotes('');
    } catch (err) {
      console.error(err);
    }
  };

  const stageBadgeStyles: Record<KanbanStage, string> = {
    'Discovered': 'border-cyan-500/35 text-cyan-300 bg-cyan-950/30',
    'Applied': 'border-indigo-500/35 text-indigo-300 bg-indigo-950/30',
    'HR Screening': 'border-amber-500/35 text-amber-300 bg-amber-950/30',
    'Technical Interview': 'border-violet-500/35 text-violet-300 bg-violet-950/30',
    'Offer': 'border-emerald-500/40 text-emerald-300 bg-emerald-950/35',
    'Rejected': 'border-rose-500/40 text-rose-300 bg-rose-950/35',
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900/90 border border-slate-800 p-6 rounded-2xl shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg sm:text-xl font-bold text-white flex items-center gap-2">
              <LayoutDashboard className="w-5 h-5 text-emerald-400" />
              Visual Kanban Application Pipeline
            </h2>
            <span className="hidden sm:inline-block text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-emerald-950/70 text-emerald-300 border border-emerald-700/50">
              Drag &amp; Drop + Google Calendar
            </span>
          </div>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            Drag cards across <strong>Discovered &rarr; Applied &rarr; HR Screening &rarr; Technical Interview &rarr; Offer</strong> or <strong>Rejected</strong>. Moving to an interview stage suggests syncing with Google Calendar.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
          <a
            href={getExportApplicationsUrl('csv')}
            target="_blank"
            rel="noreferrer"
            className="min-h-[44px] flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-slate-300 bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-all"
            title="Export application pipeline to CSV"
          >
            <Download className="w-3.5 h-3.5 text-emerald-400" />
            <span>Export CSV</span>
          </a>
          <button
            onClick={() => setIsAddModalOpen(true)}
            className="min-h-[44px] flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold text-white bg-gradient-to-r from-emerald-700 to-teal-700 hover:from-emerald-700 hover:to-teal-500 shadow-lg shadow-emerald-600/20 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Add Application</span>
          </button>
        </div>
      </div>

      {/* Mobile Swipe Peek Hint (visible only on mobile viewports) */}
      <div className="xl:hidden text-center text-[11px] text-slate-400 font-medium">
        &larr; Swipe horizontally or drag cards between stages &rarr;
      </div>

      {/* 6-Column Kanban Board with Drag-and-Drop + Mobile Horizontal Snap Scrolling */}
      <div className="snap-x snap-mandatory flex overflow-x-auto space-x-3.5 pb-4 xl:grid xl:grid-cols-6 xl:gap-3 xl:space-x-0">
        {KANBAN_STAGES.map((stage, stageIdx) => {
          const colApps = applications.filter((a) => normalizeStage(a.status) === stage);
          const isDropTarget = dragOverStage === stage;

          return (
            <div
              key={stage}
              data-testid={`kanban-column-${stage}`}
              data-stage={stage}
              onDragOver={(e) => handleColumnDragOver(e, stage)}
              onDragEnter={(e) => handleColumnDragOver(e, stage)}
              onDragLeave={() => {
                if (dragOverStage === stage) setDragOverStage(null);
              }}
              onDrop={(e) => handleColumnDrop(e, stage)}
              className={`snap-center w-[82vw] sm:w-72 xl:w-auto flex-shrink-0 rounded-2xl p-3 flex flex-col min-h-[540px] transition-all border ${
                isDropTarget
                  ? 'bg-emerald-950/25 border-emerald-400 ring-2 ring-emerald-500/40 shadow-lg shadow-emerald-500/10'
                  : stage === 'Rejected'
                  ? 'bg-rose-950/15 border-rose-900/40'
                  : 'bg-slate-900/65 border-slate-800/80'
              }`}
            >
              {/* Column Header */}
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-1.5">
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full border ${stageBadgeStyles[stage]}`}>
                    {stage}
                  </span>
                </div>
                <span className="text-xs font-semibold text-slate-400 bg-slate-950 px-2 py-0.5 rounded border border-slate-800">
                  {colApps.length}
                </span>
              </div>

              {/* Cards */}
              <div className="space-y-3 flex-1 overflow-y-auto pr-0.5">
                {colApps.map((app) => {
                  const pdfUrl = app.cv_pdf_url
                    ? app.cv_pdf_url.startsWith('http')
                      ? app.cv_pdf_url
                      : `${BACKEND_ORIGIN}${app.cv_pdf_url}`
                    : null;

                  const isDraggingThis = draggingAppId === app.id;

                  return (
                    <div
                      key={app.id}
                      draggable
                      data-testid={`kanban-card-${app.id}`}
                      data-app-id={app.id}
                      onDragStart={(e) => handleDragStartCard(e, app.id)}
                      onDragEnd={handleDragEndCard}
                      className={`bg-slate-950 p-3.5 rounded-xl border transition-all space-y-2.5 shadow-sm cursor-grab active:cursor-grabbing ${
                        isDraggingThis
                          ? 'opacity-45 border-emerald-400 scale-[0.98]'
                          : 'border-slate-800/90 hover:border-slate-600'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-1">
                        <div className="flex items-start gap-1.5 min-w-0">
                          <GripVertical className="w-3.5 h-3.5 text-slate-600 flex-shrink-0 mt-0.5" />
                          <div className="min-w-0">
                            <h4 className="text-xs font-bold text-white line-clamp-2 leading-snug">{app.role}</h4>
                            <span className="text-[11px] text-emerald-400 font-medium block truncate mt-0.5">{app.company}</span>
                          </div>
                        </div>

                        {app.match_score !== undefined && (
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded-full border flex-shrink-0 ${
                              app.match_score >= 80
                                ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800'
                                : 'bg-amber-950/60 text-amber-400 border-amber-800'
                            }`}
                          >
                            {app.match_score}%
                          </span>
                        )}
                      </div>

                      {/* Portal & Salary estimate */}
                      <div className="flex items-center justify-between gap-1 text-[10px] text-slate-400">
                        <span className="uppercase font-semibold px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800">
                          {app.portal || 'portal'}
                        </span>
                        {app.salary_estimate && (
                          <span className="text-emerald-400 font-medium truncate flex items-center gap-0.5">
                            <DollarSign className="w-3 h-3" />
                            {app.salary_estimate}
                          </span>
                        )}
                      </div>

                      {/* Interview Date badge if present */}
                      {app.interview_date && (
                        <div className="flex items-center gap-1.5 text-[10px] text-purple-300 bg-purple-950/40 border border-purple-800/50 px-2 py-1 rounded-lg">
                          <Clock className="w-3 h-3 text-purple-400 flex-shrink-0" />
                          <span className="truncate">Interview: {app.interview_date}</span>
                        </div>
                      )}

                      {/* Notes snippet */}
                      {app.notes && (
                        <p className="text-[10px] text-slate-400 line-clamp-2 bg-slate-900/40 p-1.5 rounded border border-slate-800/60 leading-relaxed">
                          {app.notes}
                        </p>
                      )}

                      {/* Card Actions: Interview Prep, Gmail Dispatch, PDF Download, Stage Shift */}
                      <div className="flex flex-wrap items-center justify-between gap-1 pt-2 border-t border-slate-800/70 text-[10px]">
                        <div className="flex items-center gap-0.5">
                          {/* Interview Copilot Button */}
                          <button
                            onClick={() => setPrepModalApp(app)}
                            title="Interview Copilot (10 Questions & STAR Frameworks)"
                            className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] p-1.5 rounded-lg hover:bg-slate-800 text-indigo-400 hover:text-indigo-300 transition-colors flex items-center justify-center"
                          >
                            <Sparkles className="w-3.5 h-3.5" />
                          </button>

                          {/* Gmail Dispatch Button */}
                          <button
                            onClick={() => setEmailModalApp(app)}
                            title="Save as Gmail Draft or Send via Email"
                            className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] p-1.5 rounded-lg hover:bg-slate-800 text-rose-400 hover:text-rose-300 transition-colors flex items-center justify-center"
                          >
                            <Mail className="w-3.5 h-3.5" />
                          </button>

                          {/* Resume Download */}
                          {pdfUrl && (
                            <a
                              href={pdfUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              title="Download Tailored ATS PDF Resume"
                              className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] p-1.5 rounded-lg hover:bg-slate-800 text-sky-400 transition-colors flex items-center justify-center"
                            >
                              <Download className="w-3.5 h-3.5" />
                            </a>
                          )}

                          {/* Notes / Date Edit */}
                          <button
                            onClick={() => openInterviewModal(app)}
                            title="Edit Notes & Interview Date"
                            className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors flex items-center justify-center"
                          >
                            <Calendar className="w-3.5 h-3.5" />
                          </button>

                          {/* Delete */}
                          <button
                            onClick={() => handleDelete(app.id)}
                            title="Remove from board"
                            className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-rose-400 transition-colors flex items-center justify-center"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>

                        {/* 1-Click Stage Shift Arrows */}
                        <div className="flex items-center gap-0.5">
                          {stageIdx > 0 && (
                            <button
                              onClick={() => handleStageShift(app.id, stage, 'backward')}
                              title={`Move back to ${KANBAN_STAGES[stageIdx - 1]}`}
                              className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors flex items-center justify-center"
                            >
                              <ChevronLeft className="w-3.5 h-3.5" />
                            </button>
                          )}
                          {stageIdx < KANBAN_STAGES.length - 1 && (
                            <button
                              onClick={() => handleStageShift(app.id, stage, 'forward')}
                              title={`Advance to ${KANBAN_STAGES[stageIdx + 1]}`}
                              className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] p-1.5 rounded-lg hover:bg-slate-800 text-sky-400 hover:text-sky-300 transition-colors flex items-center justify-center"
                            >
                              <ChevronRight className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {colApps.length === 0 && (
                  <div className="text-center py-12 text-xs text-slate-600 italic">
                    No vacancies in {stage}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Interview Prep Modal */}
      {prepModalApp && (
        <InterviewPrepModal
          isOpen={Boolean(prepModalApp)}
          onClose={() => setPrepModalApp(null)}
          appId={prepModalApp.id}
          companyName={prepModalApp.company}
          jobTitle={prepModalApp.role}
        />
      )}

      {/* Gmail Email Dispatch Modal */}
      {emailModalApp && (
        <EmailDispatchModal
          isOpen={Boolean(emailModalApp)}
          onClose={() => setEmailModalApp(null)}
          appId={emailModalApp.id}
          companyName={emailModalApp.company}
          jobTitle={emailModalApp.role}
          cvPdfPath={emailModalApp.cv_pdf_url}
          onEmailSent={loadApps}
        />
      )}

      {/* Interview Date, Notes & Google Calendar Modal */}
      {editingApp && (
        <div
          data-testid="interview-calendar-modal"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in"
        >
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-sm font-bold text-white">Interview Details &amp; Google Calendar</h3>
                <span className="text-xs text-slate-400">{editingApp.role} • {editingApp.company}</span>
              </div>
              <button onClick={() => setEditingApp(null)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            {calendarPrompted && (
              <div className="bg-emerald-950/35 border border-emerald-700/50 rounded-xl p-3 flex items-start gap-2.5 text-xs text-emerald-200">
                <CalendarPlus className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-emerald-300">Moved to Interview Stage — Add to Google Calendar?</div>
                  <p className="text-[11px] text-emerald-200/80 mt-0.5">
                    Pick your interview date/time below and sync directly to Google Calendar so you never miss a screen or technical round.
                  </p>
                </div>
              </div>
            )}

            <div className="space-y-3.5 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                <div className="sm:col-span-2">
                  <label className="block text-slate-400 uppercase font-semibold mb-1">Interview Date &amp; Time</label>
                  <input
                    type="datetime-local"
                    value={modalInterviewDate}
                    onChange={(e) => setModalInterviewDate(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 uppercase font-semibold mb-1">Duration</label>
                  <select
                    value={modalDurationMins}
                    onChange={(e) => setModalDurationMins(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-emerald-500"
                  >
                    <option value={30}>30 min</option>
                    <option value={45}>45 min</option>
                    <option value={60}>60 min</option>
                    <option value={90}>90 min</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Technical Notes / Feedback</label>
                <textarea
                  rows={4}
                  value={modalNotes}
                  onChange={(e) => setModalNotes(e.target.value)}
                  placeholder="Record interviewer names, questions asked, coding round feedback..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-emerald-500"
                />
              </div>

              {/* Google Calendar Integration Bar */}
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-3 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-[11px]">
                    <span className={`w-2 h-2 rounded-full ${calendarStatus?.connected ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                    <span className="text-slate-300 font-medium">
                      {calendarStatus?.connected
                        ? `Google Calendar connected (${calendarStatus.email})`
                        : 'Google Calendar: Ready via one-click link or connect OAuth'}
                    </span>
                  </div>
                  {!calendarStatus?.connected && (
                    <button
                      type="button"
                      onClick={handleConnectGoogleAccount}
                      className="text-[11px] font-semibold text-emerald-400 hover:text-emerald-300 underline"
                    >
                      Connect Google Account
                    </button>
                  )}
                </div>

                {calendarErr && <p className="text-[11px] text-rose-400">{calendarErr}</p>}

                {calendarResult && (
                  <div className="text-[11px] text-emerald-300 bg-emerald-950/30 border border-emerald-800/50 rounded-lg p-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                      {calendarResult.message}
                    </span>
                    <a
                      href={calendarResult.html_link || calendarResult.google_calendar_template_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-semibold text-emerald-300 underline"
                    >
                      <span>Open Google Calendar</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={handleSyncToGoogleCalendar}
                  disabled={calendarBusy}
                  data-testid="btn-add-google-calendar"
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-700/20 hover:bg-emerald-700/30 border border-emerald-500/40 text-emerald-300 font-semibold transition-all disabled:opacity-50"
                >
                  <CalendarPlus className="w-4 h-4" />
                  <span>{calendarBusy ? 'Syncing...' : 'Add to Google Calendar'}</span>
                </button>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingApp(null)}
                    className="px-4 py-2 rounded-lg text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleSaveInterviewModal}
                    className="px-5 py-2 rounded-lg bg-gradient-to-r from-emerald-700 to-teal-700 hover:from-emerald-700 hover:to-teal-500 text-white font-semibold"
                  >
                    Save Notes
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Add Application Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Building2 className="w-5 h-5 text-sky-400" />
                Add New Tracked Application
              </h3>
              <button onClick={() => setIsAddModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Company Name</label>
                <input
                  type="text"
                  required
                  value={newCompany}
                  onChange={(e) => setNewCompany(e.target.value)}
                  placeholder="e.g. MacPaw, Rooms Hotel, TBC"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Role Title</label>
                <input
                  type="text"
                  required
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  placeholder="e.g. Senior QA Automation Engineer (Playwright)"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Job URL</label>
                <input
                  type="text"
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                  placeholder="https://..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-emerald-500 font-mono text-[11px]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 uppercase font-semibold mb-1">Pipeline Stage</label>
                  <select
                    value={newStatus}
                    onChange={(e) => setNewStatus(e.target.value as KanbanStage)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none"
                  >
                    {KANBAN_STAGES.map((st) => (
                      <option key={st} value={st}>
                        {st}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 uppercase font-semibold mb-1">Portal Source</label>
                  <input
                    type="text"
                    value={newPortal}
                    onChange={(e) => setNewPortal(e.target.value)}
                    placeholder="Jobs.ge, Djinni, etc."
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 uppercase font-semibold mb-1">Match Score %</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={newScore}
                    onChange={(e) => setNewScore(parseInt(e.target.value) || 0)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-slate-400 uppercase font-semibold mb-1">Estimated Salary</label>
                  <input
                    type="text"
                    value={newSalary}
                    onChange={(e) => setNewSalary(e.target.value)}
                    placeholder="e.g. 5,000-7,000 GEL"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Initial Notes</label>
                <textarea
                  rows={2}
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  placeholder="Notes, hiring manager name, or referral..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="px-4 py-2 rounded-lg text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-500 text-white font-semibold"
                >
                  Save to Pipeline
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
