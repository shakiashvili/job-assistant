import React, { useState, useEffect } from 'react';
import {
  User,
  Shield,
  Briefcase,
  Code,
  MessageSquare,
  Save,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle,
  UploadCloud,
  GraduationCap,
  RefreshCw,
} from 'lucide-react';
import {
  fetchGroundTruth,
  saveGroundTruth,
  fetchCandidateAnalytics,
  fetchProfileIntelligence,
  previewProfileImport,
  applyProfileImport,
} from '../services/api';
import { GroundTruth, ProfileImportPreviewResponse, ProfileIntelligenceResponse } from '../types';

const DEFAULT_GROUND_TRUTH: GroundTruth = {
  candidate: {
    first_name: '',
    last_name: '',
    full_name: '',
    email: '',
    phone: '',
    headline: '',
    location: { city: '', country: '', open_to_relocation: false, remote_preference: 'Remote' },
    links: { linkedin: '', github: '', portfolio: '' },
    work_authorization: {
      citizenship: [],
      eu_work_permit: false,
      requires_eu_visa: false,
      us_work_authorization: '',
      requires_us_visa_sponsorship: false,
      uk_work_authorization: '',
      security_clearance: false,
    },
    languages: [],
    compensation: {
      expected_salary_eur: 0,
      min_salary_eur: 0,
      expected_salary_usd: 0,
      notice_period: '',
    },
  },
  skills: { core: [], secondary: [] },
  work_history: [],
  education: [],
  cv_variants: {},
  faq_bank: [],
};

export const ProfileVault: React.FC = () => {
  const [data, setData] = useState<GroundTruth>(DEFAULT_GROUND_TRUTH);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<'personal' | 'auth' | 'skills' | 'history' | 'education' | 'faq'>('personal');
  const [isSaving, setIsSaving] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // New skill, FAQ, work history, education & certification inputs
  const [newSkill, setNewSkill] = useState('');
  const [newFaqTrigger, setNewFaqTrigger] = useState('');
  const [newFaqAnswer, setNewFaqAnswer] = useState('');
  const [newFaqTags, setNewFaqTags] = useState('');
  const [newRoleTitle, setNewRoleTitle] = useState('');
  const [newRoleCompany, setNewRoleCompany] = useState('');
  const [newRoleLocation, setNewRoleLocation] = useState('');
  const [newRoleStart, setNewRoleStart] = useState('');
  const [newRoleEnd, setNewRoleEnd] = useState('');
  const [newRoleCurrent, setNewRoleCurrent] = useState(false);
  const [newRoleHighlights, setNewRoleHighlights] = useState('');
  const [newEduDegree, setNewEduDegree] = useState('');
  const [newEduInstitution, setNewEduInstitution] = useState('');
  const [newEduDates, setNewEduDates] = useState('');
  const [newEduGpa, setNewEduGpa] = useState('');
  const [newEduModules, setNewEduModules] = useState('');
  const [newCert, setNewCert] = useState('');
  const [newLangName, setNewLangName] = useState('');
  const [newLangProf, setNewLangProf] = useState('Fluent (C1)');
  const [newProjTitle, setNewProjTitle] = useState('');
  const [newProjOrg, setNewProjOrg] = useState('');
  const [newProjDates, setNewProjDates] = useState('');
  const [newProjBullets, setNewProjBullets] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [isUploadingSkills, setIsUploadingSkills] = useState(false);
  const [importPreview, setImportPreview] = useState<ProfileImportPreviewResponse | null>(null);
  const [importModes, setImportModes] = useState<Record<string, 'merge' | 'replace' | 'skip'>>({});
  const [isApplyingImport, setIsApplyingImport] = useState(false);
  const [intelligence, setIntelligence] = useState<ProfileIntelligenceResponse | null>(null);
  const [completeness, setCompleteness] = useState<{ score: number; missing: string[] } | null>(null);
  const dropInputRef = React.useRef<HTMLInputElement | null>(null);

  const handleSkillsFileDrop = async (file: File) => {
    if (!file) return;
    setIsUploadingSkills(true);
    setErrorMsg(null);
    try {
      const preview = await previewProfileImport(file);
      setImportPreview(preview);
      setImportModes(preview.recommended_modes || {
        candidate: 'merge',
        skills: 'merge',
        work_history: 'merge',
        education: 'merge',
        projects: 'merge',
        certifications: 'merge',
        languages: 'merge',
      });
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to parse uploaded CV / skills file');
    } finally {
      setIsUploadingSkills(false);
    }
  };

  const handleConfirmImportMerge = async () => {
    if (!importPreview) return;
    setIsApplyingImport(true);
    setErrorMsg(null);
    try {
      const res = await applyProfileImport({
        filename: importPreview.filename,
        extracted: importPreview.extracted,
        section_modes: importModes,
      });
      setData({ ...DEFAULT_GROUND_TRUTH, ...res.data });
      if (res.intelligence) {
        setIntelligence(res.intelligence);
        setCompleteness({
          score: res.intelligence.completeness_score,
          missing: res.intelligence.missing_fields || [],
        });
      }
      setImportPreview(null);
      window.dispatchEvent(new CustomEvent('talentflow:profile-updated'));
      setSuccessMsg(`Imported "${importPreview.filename}" with your chosen merge rules and synced saved CVs!`);
      setTimeout(() => setSuccessMsg(null), 4500);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to apply reviewed import');
    } finally {
      setIsApplyingImport(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const [gt, analytics, intel] = await Promise.all([
        fetchGroundTruth(),
        fetchCandidateAnalytics().catch(() => null),
        fetchProfileIntelligence().catch(() => null),
      ]);
      if (gt && typeof gt === 'object') {
        setData({ ...DEFAULT_GROUND_TRUTH, ...gt });
      }
      if (intel) {
        setIntelligence(intel);
        setCompleteness({
          score: intel.completeness_score,
          missing: intel.missing_fields || [],
        });
      } else if (analytics) {
        setCompleteness({
          score: analytics.completeness_score,
          missing: analytics.missing_fields || [],
        });
      }
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to load ground truth');
    } finally {
      setIsLoading(false);
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
      window.dispatchEvent(new CustomEvent('talentflow:profile-updated'));
      const analytics = await fetchCandidateAnalytics().catch(() => null);
      if (analytics) {
        setCompleteness({
          score: analytics.completeness_score,
          missing: analytics.missing_fields || [],
        });
      }
      setSuccessMsg('Profile saved & synced automatically across all generated Word/PDF CVs!');
      setTimeout(() => setSuccessMsg(null), 4000);
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

  const addWorkHistoryItem = () => {
    if (!data || (!newRoleTitle.trim() && !newRoleCompany.trim())) return;
    const bullets = newRoleHighlights
      .split('\n')
      .map((l) => l.replace(/^[-•*]\s*/, '').trim())
      .filter(Boolean);
    const nextEntry = {
      role: newRoleTitle.trim() || 'Specialist',
      company: newRoleCompany.trim() || 'Organization',
      location: newRoleLocation.trim(),
      start_date: newRoleStart.trim(),
      end_date: newRoleCurrent ? 'Present' : newRoleEnd.trim(),
      is_current: newRoleCurrent,
      highlights: bullets,
    };
    setData({
      ...data,
      work_history: [nextEntry, ...(data.work_history || [])],
    });
    setNewRoleTitle('');
    setNewRoleCompany('');
    setNewRoleLocation('');
    setNewRoleStart('');
    setNewRoleEnd('');
    setNewRoleCurrent(false);
    setNewRoleHighlights('');
  };

  const removeWorkHistoryItem = (idxToRemove: number) => {
    if (!data) return;
    setData({
      ...data,
      work_history: (data.work_history || []).filter((_, i) => i !== idxToRemove),
    });
  };

  const addEducationItem = () => {
    if (!data || (!newEduDegree.trim() && !newEduInstitution.trim())) return;
    const mods = newEduModules
      .split(/[,;]+/)
      .map((m) => m.trim())
      .filter(Boolean);
    const nextEdu = {
      degree: newEduDegree.trim() || 'Degree',
      institution: newEduInstitution.trim(),
      dates: newEduDates.trim(),
      gpa: newEduGpa.trim() || undefined,
      modules: mods,
    };
    setData({
      ...data,
      education: [nextEdu, ...(data.education || [])],
    });
    setNewEduDegree('');
    setNewEduInstitution('');
    setNewEduDates('');
    setNewEduGpa('');
    setNewEduModules('');
  };

  const removeEducationItem = (idxToRemove: number) => {
    if (!data) return;
    setData({
      ...data,
      education: (data.education || []).filter((_, i) => i !== idxToRemove),
    });
  };

  const addCertification = () => {
    if (!data || !newCert.trim()) return;
    const currentCerts = Array.isArray(data.certifications)
      ? data.certifications
      : Array.isArray((data as any).parsed_skills_taxonomy?.courses_and_certifications)
      ? (data as any).parsed_skills_taxonomy.courses_and_certifications
      : [];
    const nextCerts = Array.from(new Set([...currentCerts, newCert.trim()]));
    setData({
      ...data,
      certifications: nextCerts,
    });
    setNewCert('');
  };

  const removeCertification = (certToRemove: string) => {
    if (!data) return;
    const currentCerts = Array.isArray(data.certifications)
      ? data.certifications
      : Array.isArray((data as any).parsed_skills_taxonomy?.courses_and_certifications)
      ? (data as any).parsed_skills_taxonomy.courses_and_certifications
      : [];
    setData({
      ...data,
      certifications: currentCerts.filter((c: string) => c !== certToRemove),
    });
  };

  const addLanguageItem = () => {
    if (!data || !newLangName.trim()) return;
    const currentLangs = Array.isArray(data.candidate?.languages) ? data.candidate.languages : [];
    setData({
      ...data,
      candidate: {
        ...data.candidate,
        languages: [...currentLangs, { language: newLangName.trim(), proficiency: newLangProf }],
      },
    });
    setNewLangName('');
  };

  const removeLanguageItem = (idx: number) => {
    if (!data) return;
    const currentLangs = Array.isArray(data.candidate?.languages) ? data.candidate.languages : [];
    setData({
      ...data,
      candidate: {
        ...data.candidate,
        languages: currentLangs.filter((_, i) => i !== idx),
      },
    });
  };

  const addProjectItem = () => {
    if (!data || !newProjTitle.trim()) return;
    const bullets = newProjBullets
      .split('\n')
      .map((b) => b.replace(/^[-•*]\s*/, '').trim())
      .filter(Boolean);
    setData({
      ...data,
      projects: [
        {
          title: newProjTitle.trim(),
          organization: newProjOrg.trim() || undefined,
          dates: newProjDates.trim() || undefined,
          highlights: bullets,
        },
        ...(data.projects || []),
      ],
    });
    setNewProjTitle('');
    setNewProjOrg('');
    setNewProjDates('');
    setNewProjBullets('');
  };

  const removeProjectItem = (idx: number) => {
    if (!data) return;
    setData({
      ...data,
      projects: (data.projects || []).filter((_, i) => i !== idx),
    });
  };

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
  const educationList = Array.isArray(data.education) ? data.education : [];
  const certifications = Array.isArray(data.certifications)
    ? data.certifications
    : Array.isArray((data as any).parsed_skills_taxonomy?.courses_and_certifications)
    ? (data as any).parsed_skills_taxonomy.courses_and_certifications
    : [];
  const faq_bank = Array.isArray(data.faq_bank) ? data.faq_bank : [];

  return (
    <div className="space-y-6">
      <input
        ref={dropInputRef}
        type="file"
        accept=".pdf,.docx,.md,.txt,.markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (file) handleSkillsFileDrop(file);
        }}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 p-6 rounded-2xl">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <User className="w-5 h-5 text-emerald-400" />
            Candidate Profile Vault (Ground Truth)
            {isLoading && (
              <span className="inline-flex items-center gap-1 text-xs font-normal text-emerald-400 ml-2">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Syncing...
              </span>
            )}
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Single Source of Truth for all automated screening answers and resume tailoring.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => dropInputRef.current?.click()}
            disabled={isUploadingSkills}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-xs text-emerald-300 bg-emerald-950/60 hover:bg-sky-900/60 border border-emerald-700/60 transition-all disabled:opacity-50"
          >
            <UploadCloud className={`w-4 h-4 ${isUploadingSkills ? 'animate-bounce' : ''}`} />
            <span>{isUploadingSkills ? 'Parsing CV...' : 'Upload CV (.pdf / .docx / .md)'}</span>
          </button>

          <button
            type="button"
            onClick={loadData}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl font-semibold text-xs text-slate-300 bg-slate-950 hover:bg-slate-800 border border-slate-800 transition-all disabled:opacity-50"
            title="Reload Ground Truth from database"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Reload</span>
          </button>

          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-xs text-white bg-gradient-to-r from-emerald-700 to-teal-700 hover:from-emerald-400 hover:to-teal-500 shadow-lg shadow-emerald-600/25 transition-all disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            <span>{isSaving ? 'Saving...' : 'Save Ground Truth'}</span>
          </button>
        </div>
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

      {completeness && (
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs font-bold text-white">
                <span>Vault Completeness: {completeness.score}%</span>
                <select
                  aria-label="Profile review status"
                  value={data.profile_status || intelligence?.profile_status || 'draft'}
                  onChange={(e) => setData({ ...data, profile_status: e.target.value })}
                  className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full bg-slate-950 text-emerald-300 border border-emerald-800/70 focus:outline-none"
                >
                  <option value="draft">Draft</option>
                  <option value="reviewed">Reviewed</option>
                  <option value="ready">Ready</option>
                </select>
                {intelligence?.provenance?.source_filename && (
                  <span className="text-[10px] font-normal px-2 py-0.5 rounded-full bg-slate-950 text-slate-300 border border-slate-700">
                    Imported: {intelligence.provenance.source_filename}
                  </span>
                )}
              </div>
              {completeness.missing.length > 0 ? (
                <p className="text-[11px] text-amber-300">
                  Missing fields (never guessed or fabricated): {completeness.missing.join(', ')}
                </p>
              ) : (
                <p className="text-[11px] text-slate-400">
                  All core identity, skills, history, and education fields are verified in your vault.
                </p>
              )}
            </div>
            <div className="w-full sm:w-44 h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className={`h-full ${completeness.score >= 80 ? 'bg-emerald-500' : 'bg-amber-500'}`}
                style={{ width: `${Math.min(100, Math.max(5, completeness.score))}%` }}
              />
            </div>
          </div>

          {intelligence && (intelligence.duplicate_skills.length > 0 || intelligence.timeline_warnings.length > 0) && (
            <div className="pt-2 border-t border-slate-800/80 space-y-1.5 text-[11px]">
              {intelligence.duplicate_skills.map((dup, i) => (
                <div key={`dup-${i}`} className="text-amber-300">
                  Duplicate skill group detected ({dup.canonical}): {dup.variants.join(' / ')}
                </div>
              ))}
              {intelligence.timeline_warnings.map((w, i) => (
                <div key={`tw-${i}`} className={w.severity === 'warning' ? 'text-rose-300' : 'text-slate-300'}>
                  Timeline check: {w.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Safe Import Preview & Selective Merge Modal */}
      {importPreview && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Review Imported Profile"
          className="bg-slate-900 border-2 border-emerald-500/60 rounded-2xl p-5 space-y-4 shadow-2xl"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-white">Review Extracted Profile: {importPreview.filename}</h3>
              <p className="text-xs text-slate-400">
                Choose how each section should be applied. Existing confirmed data is never silently overwritten when Merge or Skip is selected.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setImportPreview(null)}
              className="text-xs text-slate-400 hover:text-white px-2.5 py-1 rounded-lg border border-slate-700"
            >
              Cancel
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {([
              { key: 'candidate', label: 'Identity & Summary', count: importPreview.extracted?.candidate?.full_name || 'Header fields' },
              { key: 'skills', label: 'Core Skills', count: `${importPreview.diff_summary?.extracted_skills_count ?? 0} extracted (${importPreview.diff_summary?.new_skills_count ?? 0} new)` },
              { key: 'work_history', label: 'Work History', count: `${importPreview.diff_summary?.extracted_work_count ?? 0} roles extracted` },
              { key: 'education', label: 'Education', count: `${importPreview.diff_summary?.extracted_education_count ?? 0} degrees extracted` },
              { key: 'projects', label: 'Projects', count: `${importPreview.diff_summary?.extracted_projects_count ?? 0} projects extracted` },
              { key: 'certifications', label: 'Certifications', count: `${importPreview.diff_summary?.extracted_certifications_count ?? 0} certs extracted` },
            ]).map((sec) => (
              <div key={sec.key} className="bg-slate-950 border border-slate-800 rounded-xl p-3 space-y-1.5">
                <div className="text-xs font-semibold text-white">{sec.label}</div>
                <div className="text-[11px] text-slate-400">{sec.count}</div>
                <select
                  aria-label={`Import mode for ${sec.label}`}
                  value={importModes[sec.key] || 'merge'}
                  onChange={(e) => setImportModes({ ...importModes, [sec.key]: e.target.value as 'merge' | 'replace' | 'skip' })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-xs text-emerald-300"
                >
                  <option value="merge">Merge (keep existing + add new)</option>
                  <option value="replace">Replace with extracted</option>
                  <option value="skip">Skip (do not modify)</option>
                </select>
              </div>
            ))}
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setImportPreview(null)}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-300 bg-slate-800 hover:bg-slate-700"
            >
              Discard
            </button>
            <button
              type="button"
              disabled={isApplyingImport}
              onClick={handleConfirmImportMerge}
              className="px-5 py-2 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50"
            >
              {isApplyingImport ? 'Applying Merge...' : 'Apply Reviewed Import'}
            </button>
          </div>
        </div>
      )}

      {/* Vault Sub-navigation */}
      <div className="flex overflow-x-auto gap-2 border-b border-slate-800 pb-3">
        {[
          { id: 'personal', label: 'Personal & Contact', icon: User },
          { id: 'auth', label: 'Visas & Work Auth', icon: Shield },
          { id: 'skills', label: `Verified Skills (${skillsCore.length})`, icon: Code },
          { id: 'history', label: `Work History (${work_history.length})`, icon: Briefcase },
          { id: 'education', label: `Education & Certs (${educationList.length + certifications.length})`, icon: GraduationCap },
          { id: 'faq', label: `FAQ Bank (${faq_bank.length})`, icon: MessageSquare },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`min-h-[44px] flex-shrink-0 flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-all ${
                activeTab === tab.id
                  ? 'bg-slate-800 text-emerald-400 border border-slate-700'
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
            {([
              { key: 'first_name' as const, label: 'First Name', type: 'text' },
              { key: 'last_name' as const, label: 'Last Name', type: 'text' },
              { key: 'email' as const, label: 'Email', type: 'email' },
              { key: 'phone' as const, label: 'Phone', type: 'text' },
              { key: 'headline' as const, label: 'Professional Headline', type: 'text', wide: true },
            ]).map((f) => (
              <div key={f.key} className={f.wide ? 'md:col-span-2' : undefined}>
                <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">{f.label}</label>
                <input
                  type={f.type}
                  value={String(candidate[f.key] || '')}
                  onChange={(e) => setData({ ...data, candidate: { ...candidate, [f.key]: e.target.value } })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                />
              </div>
            ))}
            <div className="md:col-span-2">
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Professional Summary</label>
              <textarea
                rows={3}
                placeholder="Brief summary of your verified background, domain strengths, and target roles..."
                value={String(candidate.summary || '')}
                onChange={(e) => setData({ ...data, candidate: { ...candidate, summary: e.target.value } })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <h3 className="text-base font-semibold text-white pt-4 border-t border-slate-800">URLs &amp; Social Profiles</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {([
              ['linkedin', 'LinkedIn'],
              ['github', 'GitHub'],
              ['portfolio', 'Portfolio'],
            ] as const).map(([key, label]) => (
              <div key={key}>
                <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">{label}</label>
                <input
                  type="text"
                  value={links[key] || ''}
                  onChange={(e) => setData({ ...data, candidate: { ...candidate, links: { ...links, [key]: e.target.value } } })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono text-[11px]"
                />
              </div>
            ))}
          </div>

          <div className="pt-4 border-t border-slate-800 space-y-3">
            <h3 className="text-base font-semibold text-white">Languages &amp; Proficiency</h3>
            <div className="flex flex-wrap gap-2">
              <input
                type="text"
                placeholder="Language (e.g. Georgian, English, German)"
                value={newLangName}
                onChange={(e) => setNewLangName(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <select
                value={newLangProf}
                onChange={(e) => setNewLangProf(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                <option value="Native">Native</option>
                <option value="Fluent (C2)">Fluent (C2)</option>
                <option value="Fluent (C1)">Fluent (C1)</option>
                <option value="Upper-Intermediate (B2)">Upper-Intermediate (B2)</option>
                <option value="Intermediate (B1)">Intermediate (B1)</option>
                <option value="Elementary (A2)">Elementary (A2)</option>
              </select>
              <button
                type="button"
                onClick={addLanguageItem}
                className="px-3.5 py-2 bg-emerald-700 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Language</span>
              </button>
            </div>
            {(candidate.languages || []).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {(candidate.languages || []).map((lang, lIdx) => (
                  <span
                    key={lIdx}
                    className="inline-flex items-center gap-1.5 bg-slate-950 border border-slate-800 px-3 py-1.5 rounded-xl text-xs text-slate-200"
                  >
                    <span>
                      <strong>{lang.language}</strong> ({lang.proficiency})
                    </span>
                    <button
                      type="button"
                      onClick={() => removeLanguageItem(lIdx)}
                      aria-label={`Remove ${lang.language}`}
                      className="text-slate-400 hover:text-rose-400"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
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
                className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
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
                className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <p className="text-[11px] text-slate-400">
                Audits prioritize verified skills and only flag roles requiring explicit citizenship or security clearance.
              </p>
            </div>

            <div className="md:col-span-2">
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-2">Compensation & Notice Preferences</label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {([
                  { key: 'expected_salary_eur' as const, label: 'Expected Salary (EUR)', numeric: true },
                  { key: 'expected_salary_usd' as const, label: 'Expected Salary (USD)', numeric: true },
                  { key: 'notice_period' as const, label: 'Notice Period', numeric: false, placeholder: 'e.g. Immediate / 2 weeks notice' },
                ]).map((f) => (
                  <div key={f.key} className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-[10px] text-slate-400 uppercase block mb-1">{f.label}</span>
                    <input
                      type={f.numeric ? 'number' : 'text'}
                      min={f.numeric ? 0 : undefined}
                      placeholder={f.placeholder}
                      value={f.numeric ? Number(compensation[f.key] ?? 0) : String(compensation[f.key] || '')}
                      onChange={(e) =>
                        setData({
                          ...data,
                          candidate: {
                            ...candidate,
                            compensation: { ...compensation, [f.key]: f.numeric ? Number(e.target.value) || 0 : e.target.value },
                          },
                        })
                      }
                      className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-sm font-bold text-white"
                    />
                  </div>
                ))}
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
                ? 'border-emerald-400 bg-emerald-950/40 shadow-lg shadow-emerald-500/20'
                : 'border-slate-800 hover:border-slate-700 bg-slate-950/50'
            }`}
          >
            <div className="flex flex-col items-center justify-center space-y-2">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                <UploadCloud className={`w-5 h-5 ${isUploadingSkills ? 'animate-bounce' : ''}`} />
              </div>
              <div className="text-xs font-semibold text-slate-200">
                {isUploadingSkills ? 'Parsing skills.md...' : 'Drag & drop skills.md here, or click to browse'}
              </div>
              <p className="text-[11px] text-slate-400 max-w-sm">
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
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <button
                type="button"
                aria-label="Add skill"
                onClick={addCoreSkill}
                className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium"
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {skillsCore.map((skill) => (
              <span
                key={skill}
                className="flex items-center gap-1.5 bg-slate-950 text-emerald-300 border border-slate-800 px-3 py-1.5 rounded-xl text-xs font-medium"
              >
                <span>{skill}</span>
                <button
                  type="button"
                  onClick={() => removeCoreSkill(skill)}
                  aria-label={`Remove ${skill}`}
                  className="text-slate-400 hover:text-rose-400 transition-colors"
                >
                  <Trash2 className="w-3 h-3" aria-hidden="true" />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tab 4: Work History */}
      {activeTab === 'history' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <div>
            <h3 className="text-base font-semibold text-white">Verified Career Experience</h3>
            <p className="text-xs text-slate-400 mt-1">
              Add or edit roles manually (no CV upload required), then click Save Ground Truth above.
            </p>
          </div>

          <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                type="text"
                placeholder="Role / Title (e.g. Junior QA Engineer)"
                value={newRoleTitle}
                onChange={(e) => setNewRoleTitle(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <input
                type="text"
                placeholder="Company / Organization"
                value={newRoleCompany}
                onChange={(e) => setNewRoleCompany(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <input
                type="text"
                placeholder="Location (e.g. Tbilisi, Remote)"
                value={newRoleLocation}
                onChange={(e) => setNewRoleLocation(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-center">
              <input
                type="text"
                placeholder="Start Date (e.g. Jan 2025)"
                value={newRoleStart}
                onChange={(e) => setNewRoleStart(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <input
                type="text"
                placeholder="End Date (e.g. Jun 2026)"
                disabled={newRoleCurrent}
                value={newRoleCurrent ? 'Present' : newRoleEnd}
                onChange={(e) => setNewRoleEnd(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 disabled:opacity-50"
              />
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={newRoleCurrent}
                  onChange={(e) => setNewRoleCurrent(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-900 text-emerald-500"
                />
                <span>Currently working here</span>
              </label>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <textarea
                rows={2}
                placeholder="Achievements / bullets (one per line)..."
                value={newRoleHighlights}
                onChange={(e) => setNewRoleHighlights(e.target.value)}
                className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <button
                type="button"
                onClick={addWorkHistoryItem}
                className="min-h-[44px] px-4 py-2 bg-emerald-700 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1 self-end"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Role</span>
              </button>
            </div>
          </div>

          {work_history.length === 0 ? (
            <div className="text-xs text-slate-400 py-6 text-center bg-slate-950 rounded-xl border border-slate-800">
              No work history entries yet. Add roles above or upload a CV / skills file.
            </div>
          ) : (
            <div className="space-y-4">
              {work_history.map((job, idx) => (
                <div key={idx} className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h4 className="text-sm font-semibold text-white">{job.role || 'Role'}</h4>
                      <span className="text-xs text-emerald-400 font-medium">{job.company || 'Organization'}</span>
                      {job.location && <span className="text-xs text-slate-400"> • {job.location}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      {(job.start_date || job.end_date) && (
                        <span className="text-xs text-slate-400 font-mono bg-slate-900 px-2 py-0.5 rounded">
                          {[job.start_date, job.is_current ? 'Present' : job.end_date].filter(Boolean).join(' – ')}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => removeWorkHistoryItem(idx)}
                        aria-label={`Remove role ${job.role || idx}`}
                        className="text-slate-400 hover:text-rose-400 transition-colors p-1"
                      >
                        <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                      </button>
                    </div>
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

          {/* Projects & Portfolios CRUD */}
          <div className="pt-4 border-t border-slate-800 space-y-4">
            <div>
              <h4 className="text-sm font-semibold text-white">Projects &amp; Portfolios ({(data.projects || []).length})</h4>
              <p className="text-xs text-slate-400">Add academic, freelance, or personal portfolio projects manually.</p>
            </div>
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <input
                  type="text"
                  placeholder="Project Title"
                  value={newProjTitle}
                  onChange={(e) => setNewProjTitle(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                />
                <input
                  type="text"
                  placeholder="Organization / Link (optional)"
                  value={newProjOrg}
                  onChange={(e) => setNewProjOrg(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                />
                <input
                  type="text"
                  placeholder="Dates (e.g. 2026)"
                  value={newProjDates}
                  onChange={(e) => setNewProjDates(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div className="flex flex-col sm:flex-row gap-2">
                <textarea
                  rows={2}
                  placeholder="Project highlights / deliverables (one per line)..."
                  value={newProjBullets}
                  onChange={(e) => setNewProjBullets(e.target.value)}
                  className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                />
                <button
                  type="button"
                  onClick={addProjectItem}
                  className="min-h-[44px] px-4 py-2 bg-emerald-700 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1 self-end"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Add Project</span>
                </button>
              </div>
            </div>
            {(data.projects || []).length > 0 && (
              <div className="space-y-2.5">
                {(data.projects || []).map((proj, pIdx) => (
                  <div key={pIdx} className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 space-y-1.5">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <span className="text-xs font-semibold text-white">{proj.title}</span>
                        {proj.organization && <span className="text-xs text-emerald-400"> • {proj.organization}</span>}
                        {proj.dates && <span className="text-[11px] text-slate-400 ml-2 font-mono">{proj.dates}</span>}
                      </div>
                      <button
                        type="button"
                        onClick={() => removeProjectItem(pIdx)}
                        aria-label={`Remove project ${proj.title}`}
                        className="text-slate-400 hover:text-rose-400"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    {(proj.highlights || []).length > 0 && (
                      <ul className="list-disc list-inside text-xs text-slate-400 space-y-0.5">
                        {proj.highlights.map((h, hi) => (
                          <li key={hi}>{h}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 4.5: Education & Certifications */}
      {activeTab === 'education' && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <div>
            <h3 className="text-base font-semibold text-white">Academic Degrees &amp; Education</h3>
            <p className="text-xs text-slate-400 mt-1">
              Add degrees and certifications manually or parse them from your uploaded CV / <code>skills.md</code>.
            </p>
          </div>

          <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <input
                type="text"
                placeholder="Degree / Program (e.g. B.Sc. in Economics)"
                value={newEduDegree}
                onChange={(e) => setNewEduDegree(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <input
                type="text"
                placeholder="Institution / University"
                value={newEduInstitution}
                onChange={(e) => setNewEduInstitution(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                type="text"
                placeholder="Dates (e.g. 2022–2026)"
                value={newEduDates}
                onChange={(e) => setNewEduDates(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <input
                type="text"
                placeholder="GPA (optional)"
                value={newEduGpa}
                onChange={(e) => setNewEduGpa(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Core modules (comma-separated)"
                  value={newEduModules}
                  onChange={(e) => setNewEduModules(e.target.value)}
                  className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                />
                <button
                  type="button"
                  onClick={addEducationItem}
                  className="min-h-[44px] px-3.5 py-2 bg-emerald-700 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Add</span>
                </button>
              </div>
            </div>
          </div>

          {educationList.length === 0 ? (
            <div className="text-xs text-slate-400 py-6 text-center bg-slate-950 rounded-xl border border-slate-800">
              No education entries yet. Add your degree above or upload a CV / skills file.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {educationList.map((edu, idx) => {
                const dateBadge =
                  edu.dates ||
                  (edu.start_year || edu.end_year
                    ? [edu.start_year, edu.end_year].filter(Boolean).join(' – ')
                    : edu.graduation_year
                    ? String(edu.graduation_year)
                    : '');
                const degreeTitle = edu.degree || edu.field_of_study || edu.focus || 'Academic Program';
                const institutionLine =
                  edu.institution && edu.institution.toLowerCase() !== degreeTitle.toLowerCase()
                    ? edu.institution + (edu.location ? ` • ${edu.location}` : '')
                    : '';
                const modulesList = Array.isArray(edu.modules) && edu.modules.length > 0
                  ? edu.modules
                  : (edu.field_of_study || edu.focus) &&
                    (edu.field_of_study || edu.focus) !== degreeTitle &&
                    (edu.field_of_study || edu.focus) !== edu.institution
                  ? String(edu.field_of_study || edu.focus)
                      .split(/[;,]+/)
                      .map((m) => m.trim())
                      .filter(Boolean)
                  : [];

                return (
                  <div key={idx} className="bg-slate-950/80 p-4 rounded-xl border border-slate-800 space-y-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h4 className="text-sm font-semibold text-white leading-snug">{degreeTitle}</h4>
                        {institutionLine && (
                          <div className="text-xs text-emerald-400 font-medium mt-0.5">{institutionLine}</div>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        {dateBadge && (
                          <span className="text-[11px] text-slate-300 font-mono bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                            {dateBadge}
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => removeEducationItem(idx)}
                          aria-label={`Remove degree ${degreeTitle}`}
                          className="text-slate-400 hover:text-rose-400 transition-colors p-1"
                        >
                          <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                        </button>
                      </div>
                    </div>

                    {edu.gpa && (
                      <div className="inline-flex items-center gap-1.5 text-[11px] font-medium text-teal-300 bg-teal-950/40 border border-teal-800/50 px-2 py-0.5 rounded">
                        <span>Cumulative GPA:</span>
                        <span className="font-mono font-bold">{edu.gpa}</span>
                      </div>
                    )}

                    {modulesList.length > 0 && (
                      <div className="pt-1 border-t border-slate-800/70">
                        <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold mb-1.5">
                          Studying Subjects &amp; Core Modules
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {modulesList.map((mod, mIdx) => (
                            <span
                              key={mIdx}
                              className="text-[11px] text-slate-300 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded-md"
                            >
                              {mod}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="pt-4 border-t border-slate-800 space-y-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <h4 className="text-sm font-semibold text-white">Courses, Bootcamps &amp; Certifications</h4>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="Add certification or course..."
                  value={newCert}
                  onChange={(e) => setNewCert(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addCertification()}
                  className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                />
                <button
                  type="button"
                  onClick={addCertification}
                  aria-label="Add certification"
                  className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium"
                >
                  <Plus className="w-4 h-4" aria-hidden="true" />
                </button>
              </div>
            </div>
            {certifications.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {certifications.map((cert: string, i: number) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/60 border border-cyan-800/60 text-cyan-200 text-xs font-medium"
                  >
                    <span>🎓 {cert}</span>
                    <button
                      type="button"
                      onClick={() => removeCertification(cert)}
                      aria-label={`Remove ${cert}`}
                      className="text-cyan-300/70 hover:text-rose-400 transition-colors"
                    >
                      <Trash2 className="w-3 h-3" aria-hidden="true" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
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
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <input
                type="text"
                value={newFaqTags}
                onChange={(e) => setNewFaqTags(e.target.value)}
                placeholder="Tags (comma-separated, e.g. remote, b2b)"
                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newFaqAnswer}
                onChange={(e) => setNewFaqAnswer(e.target.value)}
                placeholder="Standard candidate answer..."
                className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              <button
                type="button"
                onClick={addFaqItem}
                className="min-h-[44px] px-3.5 py-2 bg-emerald-700 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
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
                      className="min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[32px] flex items-center justify-center text-slate-400 hover:text-rose-400"
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
