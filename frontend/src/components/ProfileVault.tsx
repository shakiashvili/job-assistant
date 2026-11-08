import React, { useState, useEffect } from 'react';
import {
  User,
  Shield,
  Briefcase,
  Code,
  DollarSign,
  MessageSquare,
  Save,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { fetchGroundTruth, saveGroundTruth } from '../services/api';
import { GroundTruth } from '../types';

export const ProfileVault: React.FC = () => {
  const [data, setData] = useState<GroundTruth | null>(null);
  const [activeTab, setActiveTab] = useState<'personal' | 'auth' | 'skills' | 'history' | 'faq'>('personal');
  const [isSaving, setIsSaving] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // New skill input
  const [newSkill, setNewSkill] = useState('');

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const gt = await fetchGroundTruth();
      setData(gt);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to load ground truth');
    }
  };

  const handleSave = async () => {
    if (!data) return;
    setIsSaving(true);
    setSuccessMsg(null);
    setErrorMsg(null);

    try {
      const updated = await saveGroundTruth(data);
      setData(updated);
      setSuccessMsg('Candidate Ground Truth saved successfully to disk!');
      setTimeout(() => setSuccessMsg(null), 3500);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  };

  const addCoreSkill = () => {
    if (!newSkill.trim() || !data) return;
    setData({
      ...data,
      skills: {
        ...data.skills,
        core: [...data.skills.core, newSkill.trim()]
      }
    });
    setNewSkill('');
  };

  const removeCoreSkill = (skillToRemove: string) => {
    if (!data) return;
    setData({
      ...data,
      skills: {
        ...data.skills,
        core: data.skills.core.filter(s => s !== skillToRemove)
      }
    });
  };

  if (!data) {
    return (
      <div className="p-12 text-center text-slate-400">
        Loading Candidate Profile Vault...
      </div>
    );
  }

  const { candidate, skills, work_history, faq_bank } = data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 p-6 rounded-2xl">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <User className="w-5 h-5 text-sky-400" />
            Candidate Profile Vault (Ground Truth)
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Single Source of Truth for all automated screening answers and resume tailoring.
          </p>
        </div>

        <button
          onClick={handleSave}
          disabled={isSaving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-xs text-white bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 shadow-lg shadow-sky-600/25 transition-all disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          <span>{isSaving ? 'Saving...' : 'Save Ground Truth'}</span>
        </button>
      </div>

      {successMsg && (
        <div className="p-3 bg-emerald-950/40 border border-emerald-800 text-xs text-emerald-300 rounded-xl flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{successMsg}</span>
        </div>
      )}

      {errorMsg && (
        <div className="p-3 bg-rose-950/40 border border-rose-800 text-xs text-rose-300 rounded-xl flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-400" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Vault Sub-navigation */}
      <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
        {[
          { id: 'personal', label: 'Personal & Contact', icon: User },
          { id: 'auth', label: 'Visas & Work Auth', icon: Shield },
          { id: 'skills', label: 'Verified Skills', icon: Code },
          { id: 'history', label: 'Work History', icon: Briefcase },
          { id: 'faq', label: 'FAQ Bank', icon: MessageSquare },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all ${
                activeTab === tab.id
                  ? 'bg-slate-800 text-sky-400 border border-slate-700'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab 1: Personal & Contact */}
      {activeTab === 'personal' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <h3 className="text-base font-semibold text-white">Candidate Information</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">First Name</label>
              <input
                type="text"
                value={candidate.first_name}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, first_name: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Last Name</label>
              <input
                type="text"
                value={candidate.last_name}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, last_name: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Email</label>
              <input
                type="email"
                value={candidate.email}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, email: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Phone</label>
              <input
                type="text"
                value={candidate.phone}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, phone: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Professional Headline</label>
              <input
                type="text"
                value={candidate.headline}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, headline: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
          </div>

          <h3 className="text-base font-semibold text-white pt-4 border-t border-slate-800">URLs & Social Profiles</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">LinkedIn</label>
              <input
                type="text"
                value={candidate.links.linkedin}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, links: { ...candidate.links, linkedin: e.target.value } } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">GitHub</label>
              <input
                type="text"
                value={candidate.links.github}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, links: { ...candidate.links, github: e.target.value } } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Portfolio</label>
              <input
                type="text"
                value={candidate.links.portfolio}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, links: { ...candidate.links, portfolio: e.target.value } } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
              />
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Visas & Work Auth */}
      {activeTab === 'auth' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <h3 className="text-base font-semibold text-white">Work Authorization & Visas</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
              <span className="text-xs font-semibold text-slate-300 block">EU / European Union Status</span>
              <div className="text-xs text-emerald-400 flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="w-4 h-4" />
                <span>EU Citizen / Permanent Work Rights</span>
              </div>
              <p className="text-[11px] text-slate-400">
                Authorized to work across all 27 EU member states without requiring visa sponsorship.
              </p>
            </div>

            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
              <span className="text-xs font-semibold text-slate-300 block">United States Status</span>
              <div className="text-xs text-amber-400 flex items-center gap-1.5 font-medium">
                <AlertCircle className="w-4 h-4" />
                <span>Requires H-1B / O-1 or B2B Contractor</span>
              </div>
              <p className="text-[11px] text-slate-400">
                Does not hold US citizenship or active green card. Open to independent B2B contractor engagements.
              </p>
            </div>

            <div className="md:col-span-2">
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Compensation Expectations</label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase block">Expected Salary (EUR)</span>
                  <span className="text-sm font-bold text-white">€{candidate.compensation.expected_salary_eur.toLocaleString()}</span>
                </div>
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase block">Expected Salary (USD)</span>
                  <span className="text-sm font-bold text-white">${candidate.compensation.expected_salary_usd.toLocaleString()}</span>
                </div>
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase block">Notice Period</span>
                  <span className="text-sm font-bold text-white">{candidate.compensation.notice_period}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Skills */}
      {activeTab === 'skills' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-white">Core Technical Skills</h3>
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Add new skill..."
                value={newSkill}
                onChange={(e) => setNewSkill(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addCoreSkill()}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
              <button
                onClick={addCoreSkill}
                className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-medium"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {skills.core.map((skill) => (
              <span
                key={skill}
                className="flex items-center gap-1.5 bg-slate-950 text-sky-300 border border-slate-800 px-3 py-1.5 rounded-xl text-xs font-medium"
              >
                <span>{skill}</span>
                <button
                  onClick={() => removeCoreSkill(skill)}
                  className="text-slate-500 hover:text-rose-400 transition-colors"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tab 4: Work History */}
      {activeTab === 'history' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <h3 className="text-base font-semibold text-white">Verified Career Experience</h3>
          <div className="space-y-4">
            {work_history.map((job, idx) => (
              <div key={idx} className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
                <div className="flex items-start justify-between">
                  <div>
                    <h4 className="text-sm font-semibold text-white">{job.role}</h4>
                    <span className="text-xs text-sky-400 font-medium">{job.company}</span>
                    <span className="text-xs text-slate-500"> • {job.location}</span>
                  </div>
                  <span className="text-xs text-slate-400 font-mono bg-slate-900 px-2 py-0.5 rounded">
                    {job.start_date} – {job.end_date}
                  </span>
                </div>
                <ul className="list-disc list-inside text-xs text-slate-400 space-y-1 pt-1">
                  {job.highlights.map((h, i) => (
                    <li key={i}>{h}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 5: FAQ Bank */}
      {activeTab === 'faq' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <h3 className="text-base font-semibold text-white">Pre-vetted Screening Question Answers Bank</h3>
          <div className="space-y-3">
            {faq_bank.map((item, idx) => (
              <div key={idx} className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-300">Trigger: "{item.question_trigger}"</span>
                  <div className="flex gap-1">
                    {item.tags.map((t) => (
                      <span key={t} className="text-[10px] bg-slate-900 text-slate-400 px-2 py-0.5 rounded font-mono">
                        #{t}
                      </span>
                    ))}
                  </div>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed bg-slate-900/60 p-3 rounded-lg border border-slate-800/80">
                  {item.answer}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
