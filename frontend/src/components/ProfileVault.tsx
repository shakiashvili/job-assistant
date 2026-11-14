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
  AlertCircle,
  UploadCloud,
  FileText
} from 'lucide-react';
import { fetchGroundTruth, saveGroundTruth, uploadSkillsMdFile } from '../services/api';
import { GroundTruth } from '../types';

export const ProfileVault: React.FC = () => {
  const [data, setData] = useState<GroundTruth | null>(null);
  const [activeTab, setActiveTab] = useState<'personal' | 'auth' | 'skills' | 'history' | 'faq'>('personal');
  const [isSaving, setIsSaving] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // New skill & FAQ inputs
  const [newSkill, setNewSkill] = useState('');
  const [newFaqTrigger, setNewFaqTrigger] = useState('');
  const [newFaqAnswer, setNewFaqAnswer] = useState('');
  const [newFaqTags, setNewFaqTags] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [isUploadingSkills, setIsUploadingSkills] = useState(false);
  const dropInputRef = React.useRef<HTMLInputElement | null>(null);

  const handleSkillsFileDrop = async (file: File) => {
    if (!file) return;
    setIsUploadingSkills(true);
    setErrorMsg(null);
    try {
      const res = await uploadSkillsMdFile(file);
      await loadData();
      setSuccessMsg(`Successfully parsed ${file.name} into CandidateProfile with ${res.extracted_skills.length} clean skills!`);
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to upload and parse skills file');
    } finally {
      setIsUploadingSkills(false);
    }
  };

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
    const currentCore = data.skills?.core || [];
    setData({
      ...data,
      skills: {
        ...(data.skills || { secondary: [] }),
        core: Array.from(new Set([...currentCore, newSkill.trim()])),
      },
    });
    setNewSkill('');
  };

  const removeCoreSkill = (skillToRemove: string) => {
    if (!data) return;
    const currentCore = data.skills?.core || [];
    setData({
      ...data,
      skills: {
        ...(data.skills || { secondary: [] }),
        core: currentCore.filter((s) => s !== skillToRemove),
      },
    });
  };

  const addFaqItem = () => {
    if (!data || !newFaqTrigger.trim() || !newFaqAnswer.trim()) return;
    const tags = newFaqTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    const nextFaq = [
      ...(data.faq_bank || []),
      {
        question_trigger: newFaqTrigger.trim(),
        tags: tags.length > 0 ? tags : ['general'],
        answer: newFaqAnswer.trim(),
      },
    ];
    setData({ ...data, faq_bank: nextFaq });
    setNewFaqTrigger('');
    setNewFaqAnswer('');
    setNewFaqTags('');
  };

  const removeFaqItem = (idxToRemove: number) => {
    if (!data) return;
    setData({
      ...data,
      faq_bank: (data.faq_bank || []).filter((_, i) => i !== idxToRemove),
    });
  };

  if (!data) {
    return (
      <div className="p-12 text-center text-slate-400">
        Loading Candidate Profile Vault...
      </div>
    );
  }

  const candidate = data.candidate || ({} as GroundTruth['candidate']);
  const links = candidate.links || { linkedin: '', github: '', portfolio: '' };
  const workAuth = candidate.work_authorization || {
    citizenship: [],
    eu_work_permit: false,
    requires_eu_visa: false,
    us_work_authorization: '',
    requires_us_visa_sponsorship: false,
    uk_work_authorization: '',
    security_clearance: false,
  };
  const compensation = candidate.compensation || {
    expected_salary_eur: 0,
    min_salary_eur: 0,
    expected_salary_usd: 0,
    notice_period: '',
  };
  const skillsCore = data.skills?.core || [];
  const work_history = Array.isArray(data.work_history) ? data.work_history : [];
  const faq_bank = Array.isArray(data.faq_bank) ? data.faq_bank : [];

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
      <div className="flex overflow-x-auto gap-2 border-b border-slate-800 pb-3">
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
              className={`min-h-[44px] flex-shrink-0 flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-all ${
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
                value={candidate.first_name || ''}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, first_name: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Last Name</label>
              <input
                type="text"
                value={candidate.last_name || ''}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, last_name: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Email</label>
              <input
                type="email"
                value={candidate.email || ''}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, email: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Phone</label>
              <input
                type="text"
                value={candidate.phone || ''}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, phone: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Professional Headline</label>
              <input
                type="text"
                value={candidate.headline || ''}
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
                value={links.linkedin || ''}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, links: { ...links, linkedin: e.target.value } } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">GitHub</label>
              <input
                type="text"
                value={links.github || ''}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, links: { ...links, github: e.target.value } } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Portfolio</label>
              <input
                type="text"
                value={links.portfolio || ''}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, links: { ...links, portfolio: e.target.value } } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
              />
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Visas & Work Auth */}
      {activeTab === 'auth' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <div>
            <h3 className="text-base font-semibold text-white">Work Authorization & Remote Eligibility</h3>
            <p className="text-xs text-slate-400 mt-1">
              Matching prioritizes verified technical skills and English remote / Georgian eligibility instead of blocking on foreign work permits.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
              <span className="text-xs font-semibold text-slate-300 block">Citizenship &amp; EU Work Status</span>
              <input
                type="text"
                placeholder="Citizenship (comma-separated, e.g. Georgia)"
                value={(workAuth.citizenship || []).join(', ')}
                onChange={(e) =>
                  setData({
                    ...data,
                    candidate: {
                      ...candidate,
                      work_authorization: {
                        ...workAuth,
                        citizenship: e.target.value
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean),
                      },
                    },
                  })
                }
                className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(workAuth.eu_work_permit)}
                  onChange={(e) =>
                    setData({
                      ...data,
                      candidate: {
                        ...candidate,
                        work_authorization: {
                          ...workAuth,
                          eu_work_permit: e.target.checked,
                          requires_eu_visa: !e.target.checked,
                        },
                      },
                    })
                  }
                  className="rounded border-slate-700 bg-slate-900 text-sky-500"
                />
                <span>Hold direct EU work permit / citizenship</span>
              </label>
            </div>

            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
              <span className="text-xs font-semibold text-slate-300 block">International / Work Authorization</span>
              <input
                type="text"
                placeholder="e.g. Remote B2B Contractor or Work Authorized"
                value={workAuth.us_work_authorization || ''}
                onChange={(e) =>
                  setData({
                    ...data,
                    candidate: {
                      ...candidate,
                      work_authorization: { ...workAuth, us_work_authorization: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
              <p className="text-[11px] text-slate-400">
                Audits prioritize verified skills and only flag roles requiring explicit citizenship or security clearance.
              </p>
            </div>

            <div className="md:col-span-2">
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-2">Compensation & Notice Preferences</label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase block mb-1">Expected Salary (EUR)</span>
                  <input
                    type="number"
                    min={0}
                    value={Number(compensation.expected_salary_eur ?? 0)}
                    onChange={(e) =>
                      setData({
                        ...data,
                        candidate: {
                          ...candidate,
                          compensation: { ...compensation, expected_salary_eur: Number(e.target.value) || 0 },
                        },
                      })
                    }
                    className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-sm font-bold text-white"
                  />
                </div>
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase block mb-1">Expected Salary (USD)</span>
                  <input
                    type="number"
                    min={0}
                    value={Number(compensation.expected_salary_usd ?? 0)}
                    onChange={(e) =>
                      setData({
                        ...data,
                        candidate: {
                          ...candidate,
                          compensation: { ...compensation, expected_salary_usd: Number(e.target.value) || 0 },
                        },
                      })
                    }
                    className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-sm font-bold text-white"
                  />
                </div>
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase block mb-1">Notice Period</span>
                  <input
                    type="text"
                    placeholder="e.g. 1 week after offer"
                    value={compensation.notice_period || ''}
                    onChange={(e) =>
                      setData({
                        ...data,
                        candidate: {
                          ...candidate,
                          compensation: { ...compensation, notice_period: e.target.value },
                        },
                      })
                    }
                    className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-sm font-bold text-white"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Skills */}
      {activeTab === 'skills' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          {/* Drag & Drop Zone for skills.md */}
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragging(false);
              const file = e.dataTransfer.files?.[0];
              if (file) handleSkillsFileDrop(file);
            }}
            onClick={() => dropInputRef.current?.click()}
            className={`border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-all ${
              isDragging
                ? 'border-sky-400 bg-sky-950/40 shadow-lg shadow-sky-500/20'
                : 'border-slate-800 hover:border-slate-700 bg-slate-950/50'
            }`}
          >
            <input
              ref={dropInputRef}
              type="file"
              accept=".md,.txt,.markdown"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleSkillsFileDrop(file);
              }}
            />
            <div className="flex flex-col items-center justify-center space-y-2">
              <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
                <UploadCloud className={`w-5 h-5 ${isUploadingSkills ? 'animate-bounce' : ''}`} />
              </div>
              <div className="text-xs font-semibold text-slate-200">
                {isUploadingSkills ? 'Parsing skills.md...' : 'Drag & drop skills.md here, or click to browse'}
              </div>
              <p className="text-[11px] text-slate-500 max-w-sm">
                Uploads and extracts clean technical competencies into the encrypted database and refreshes verified skills instantly.
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between flex-wrap gap-2">
            <h3 className="text-base font-semibold text-white">Verified Technical Skills ({skillsCore.length})</h3>
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
            {skillsCore.map((skill) => (
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
          {work_history.length === 0 ? (
            <div className="text-xs text-slate-400 py-6 text-center bg-slate-950 rounded-xl border border-slate-800">
              No work history entries parsed yet. Upload your skills.md with a Work Experience section.
            </div>
          ) : (
            <div className="space-y-4">
              {work_history.map((job, idx) => (
                <div key={idx} className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <h4 className="text-sm font-semibold text-white">{job.role || 'Role'}</h4>
                      <span className="text-xs text-sky-400 font-medium">{job.company || 'Organization'}</span>
                      {job.location && <span className="text-xs text-slate-500"> • {job.location}</span>}
                    </div>
                    {(job.start_date || job.end_date) && (
                      <span className="text-xs text-slate-400 font-mono bg-slate-900 px-2 py-0.5 rounded">
                        {[job.start_date, job.end_date].filter(Boolean).join(' – ')}
                      </span>
                    )}
                  </div>
                  <ul className="list-disc list-inside text-xs text-slate-400 space-y-1 pt-1">
                    {(job.highlights || [])
                      .filter((h) => h && h.trim() && !/^[-*_•–—.\s]+$/.test(h.trim()))
                      .map((h, i) => (
                        <li key={i}>{h}</li>
                      ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 5: FAQ Bank */}
      {activeTab === 'faq' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-base font-semibold text-white">Pre-vetted Screening Question Answers Bank</h3>
              <p className="text-xs text-slate-400">Used to auto-fill screening questions cleanly. Click Save Ground Truth above after changes.</p>
            </div>
          </div>

          <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <input
                type="text"
                value={newFaqTrigger}
                onChange={(e) => setNewFaqTrigger(e.target.value)}
                placeholder="Question keyword trigger (e.g. work authorization / notice period)"
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
              <input
                type="text"
                value={newFaqTags}
                onChange={(e) => setNewFaqTags(e.target.value)}
                placeholder="Tags (comma-separated, e.g. remote, b2b)"
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newFaqAnswer}
                onChange={(e) => setNewFaqAnswer(e.target.value)}
                placeholder="Standard candidate answer..."
                className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              />
              <button
                type="button"
                onClick={addFaqItem}
                className="min-h-[44px] px-3.5 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add FAQ</span>
              </button>
            </div>
          </div>

          <div className="space-y-3 overflow-x-auto">
            {faq_bank.map((item, idx) => (
              <div key={idx} className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-slate-300">Trigger: "{item.question_trigger}"</span>
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1 flex-wrap">
                      {(item.tags || []).map((t) => (
                        <span key={t} className="text-[10px] bg-slate-900 text-slate-400 px-2 py-0.5 rounded font-mono">
                          #{t}
                        </span>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFaqItem(idx)}
                      className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] flex items-center justify-center text-slate-500 hover:text-rose-400"
                      title="Delete FAQ entry"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
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
