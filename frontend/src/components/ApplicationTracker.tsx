import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  Plus,
  ExternalLink,
  Trash2,
  Calendar,
  Building2,
  CheckCircle2,
  X,
  Sparkles,
  MoreVertical
} from 'lucide-react';
import { fetchApplications, createApplication, updateApplication, deleteApplication } from '../services/api';
import { ApplicationItem } from '../types';

export const ApplicationTracker: React.FC = () => {
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);

  // New form state
  const [newCompany, setNewCompany] = useState('');
  const [newRole, setNewRole] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newPortal, setNewPortal] = useState('greenhouse');
  const [newStatus, setNewStatus] = useState<'Saved' | 'Applied' | 'Interviewing' | 'Rejected'>('Saved');
  const [newScore, setNewScore] = useState<number>(85);
  const [newNotes, setNewNotes] = useState('');

  const statuses: Array<'Saved' | 'Applied' | 'Interviewing' | 'Rejected'> = [
    'Saved',
    'Applied',
    'Interviewing',
    'Rejected'
  ];

  useEffect(() => {
    loadApps();
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

  const handleStatusChange = async (appId: string, status: 'Saved' | 'Applied' | 'Interviewing' | 'Rejected') => {
    try {
      const updated = await updateApplication(appId, { status });
      setApplications(applications.map(a => a.id === appId ? updated : a));
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (appId: string) => {
    if (!confirm('Remove this application from tracker?')) return;
    try {
      await deleteApplication(appId);
      setApplications(applications.filter(a => a.id !== appId));
    } catch (err) {
      console.error(err);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCompany || !newRole) return;

    try {
      const created = await createApplication({
        company: newCompany,
        role: newRole,
        url: newUrl || 'https://boards.greenhouse.io',
        portal: newPortal,
        status: newStatus,
        match_score: newScore,
        notes: newNotes,
        applied_date: newStatus === 'Applied' || newStatus === 'Interviewing' ? new Date().toISOString().split('T')[0] : null
      });

      setApplications([created, ...applications]);
      setIsAddModalOpen(false);
      setNewCompany('');
      setNewRole('');
      setNewUrl('');
      setNewNotes('');
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 p-6 rounded-2xl">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <LayoutDashboard className="w-5 h-5 text-sky-400" />
            Application Tracker Board
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Track staged, submitted, and active interview rounds across Greenhouse, Lever, and custom portals.
          </p>
        </div>

        <button
          onClick={() => setIsAddModalOpen(true)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold text-white bg-sky-600 hover:bg-sky-500 shadow-lg shadow-sky-600/20 transition-all"
        >
          <Plus className="w-4 h-4" />
          <span>Add Application</span>
        </button>
      </div>

      {/* Board Columns */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {statuses.map((status) => {
          const colApps = applications.filter((a) => a.status === status);
          const statusColors = {
            Saved: 'border-blue-500/30 text-blue-400 bg-blue-950/20',
            Applied: 'border-amber-500/30 text-amber-400 bg-amber-950/20',
            Interviewing: 'border-emerald-500/30 text-emerald-400 bg-emerald-950/20',
            Rejected: 'border-slate-700 text-slate-400 bg-slate-900/40',
          };

          return (
            <div key={status} className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-4 flex flex-col min-h-[500px]">
              {/* Column Header */}
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-bold px-2.5 py-0.5 rounded-full border ${statusColors[status]}`}>
                    {status}
                  </span>
                </div>
                <span className="text-xs font-semibold text-slate-500">{colApps.length}</span>
              </div>

              {/* Cards */}
              <div className="space-y-3 flex-1 overflow-y-auto">
                {colApps.map((app) => (
                  <div
                    key={app.id}
                    className="bg-slate-950 p-4 rounded-xl border border-slate-800/90 hover:border-slate-700 transition-all space-y-3 shadow-sm"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <h4 className="text-sm font-bold text-white line-clamp-1">{app.role}</h4>
                        <span className="text-xs text-sky-400 font-medium">{app.company}</span>
                      </div>

                      {app.match_score && (
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                            app.match_score >= 85
                              ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800'
                              : 'bg-amber-950/60 text-amber-400 border-amber-800'
                          }`}
                        >
                          {app.match_score}%
                        </span>
                      )}
                    </div>

                    {app.notes && (
                      <p className="text-[11px] text-slate-400 leading-relaxed bg-slate-900/40 p-2 rounded-lg border border-slate-800/60">
                        {app.notes}
                      </p>
                    )}

                    <div className="flex items-center justify-between pt-2 border-t border-slate-850 text-[11px] text-slate-500">
                      <span className="capitalize font-mono text-[10px] bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                        {app.portal || 'portal'}
                      </span>

                      <div className="flex items-center gap-2">
                        {app.url && (
                          <a
                            href={app.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-slate-400 hover:text-sky-400 transition-colors"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}

                        <select
                          value={app.status}
                          onChange={(e) => handleStatusChange(app.id, e.target.value as any)}
                          className="bg-slate-900 border border-slate-800 rounded px-1.5 py-0.5 text-[10px] text-slate-300 focus:outline-none"
                        >
                          {statuses.map(s => <option key={s} value={s}>{s}</option>)}
                        </select>

                        <button
                          onClick={() => handleDelete(app.id)}
                          className="text-slate-600 hover:text-rose-400 transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}

                {colApps.length === 0 && (
                  <div className="text-center py-10 text-xs text-slate-600 italic">
                    No roles in {status}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Add Application Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white">Add Application to Tracker</h3>
              <button onClick={() => setIsAddModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Company</label>
                <input
                  type="text"
                  required
                  value={newCompany}
                  onChange={(e) => setNewCompany(e.target.value)}
                  placeholder="e.g. Stripe, Figma"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-sky-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Role Title</label>
                <input
                  type="text"
                  required
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  placeholder="e.g. Senior QA Automation Engineer"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-sky-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Job URL</label>
                <input
                  type="text"
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                  placeholder="https://..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 uppercase font-semibold mb-1">Status</label>
                  <select
                    value={newStatus}
                    onChange={(e) => setNewStatus(e.target.value as any)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none"
                  >
                    {statuses.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>

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
              </div>

              <div>
                <label className="block text-slate-400 uppercase font-semibold mb-1">Notes</label>
                <textarea
                  rows={3}
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  placeholder="Add interview notes or details..."
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
                  className="px-5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold"
                >
                  Save Application
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
