import React, { useState, useEffect, useRef } from 'react';
import {
  Sparkles,
  Search,
  AlertOctagon,
  Play,
  BookmarkPlus,
  RefreshCw,
  ExternalLink,
  FileText,
  Upload,
  Download,
  Star,
  Globe,
  Edit3,
  Languages,
  Briefcase,
  Building2,
  CheckCircle2,
  Eye,
  Database,
  ShieldAlert,
  DollarSign,
  Mail
} from 'lucide-react';
import {
  auditJob,
  generateAnswers,
  createApplication,
  fetchVacancies,
  fetchSkillsMd,
  uploadSkillsMdFile,
  saveSkillsMdText,
  applySkillsPreset,
  fetchScrapedJobs,
  fetchDbProfile,
  triggerMultiPortalScrape,
  prepareJobEmailPackage,
  BACKEND_ORIGIN
} from '../services/api';
import { JobAuditResponse, ScreeningAnswer, PortalVacancyItem, DbJobPosting } from '../types';
import { StageModal } from './StageModal';

const INDUSTRY_PRESETS = [
  { id: 'qa_tech', label: '💻 QA & Software Tech', badge: 'Tech / SDET' },
  { id: 'receptionist_hospitality', label: '🏨 Receptionist & Hospitality', badge: 'Hotels & Front Desk' },
  { id: 'customer_service', label: '🎧 Customer Service & Care', badge: 'Support / CRM' },
  { id: 'healthcare_hospital', label: '🏥 Hospital & Medical Admin', badge: 'Clinic / Patient Care' },
];

export const AuditPanel: React.FC = () => {
  const [vacancies, setVacancies] = useState<PortalVacancyItem[]>([]);
  const [selectedPortalFilter, setSelectedPortalFilter] = useState<string>('ALL');
  const [selectedIndustryFilter, setSelectedIndustryFilter] = useState<string>('ALL');

  // Relational DB Scraped JobPostings State
  const [scrapedJobs, setScrapedJobs] = useState<DbJobPosting[]>([]);
  const [dbStatusFilter, setDbStatusFilter] = useState<string>('ALL');
  const [isScraping, setIsScraping] = useState(false);
  const [scrapeStats, setScrapeStats] = useState<{
    total: number;
    staged: number;
    filteredOut: number;
  } | null>(null);

  const [jobUrl, setJobUrl] = useState('');
  const [profileUploaded, setProfileUploaded] = useState<boolean>(false);
  const [jobText, setJobText] = useState('');
  const [selectedVariant, setSelectedVariant] = useState('qa_automation');
  const [cvLanguage, setCvLanguage] = useState<'en' | 'ka'>('en');
  const [activePresetId, setActivePresetId] = useState<string>('qa_tech');
  const [candidateProfile, setCandidateProfile] = useState<{
    full_name?: string;
    experience_years?: number;
    seniority_level?: string;
    target_industry?: string;
    headline?: string;
  } | null>(null);

  const [isAuditing, setIsAuditing] = useState(false);
  const [auditResult, setAuditResult] = useState<JobAuditResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Skills.md Attachment State
  const [skillsMdContent, setSkillsMdContent] = useState('');
  const [skillsFilename, setSkillsFilename] = useState('candidate_skills.md');
  const [extractedSkillsCount, setExtractedSkillsCount] = useState(0);
  const [showSkillsEditor, setShowSkillsEditor] = useState(false);
  const [skillsStatusMsg, setSkillsStatusMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Screening Answers
  const [answers, setAnswers] = useState<ScreeningAnswer[]>([]);
  const [isGeneratingAnswers, setIsGeneratingAnswers] = useState(false);

  // Ready Gmail Draft + Tailored .docx Package State
  const [draftingJobId, setDraftingJobId] = useState<number | null>(null);
  const [preparedEmailPkg, setPreparedEmailPkg] = useState<{
    company: string;
    title: string;
    recipient_email: string;
    subject: string;
    cover_letter: string;
    docx_filename: string;
    docx_url: string;
    pdf_filename: string;
    pdf_url: string;
    gmailUrl: string;
  } | null>(null);

  const handleDraftInGmail = async (job: DbJobPosting) => {
    setDraftingJobId(job.id);
    setError(null);
    try {
      const pkg = await prepareJobEmailPackage(job.id, 'auto');
      const toEmail = pkg.recipient_email || job.target_email || '';
      const gmailUrl =
        `https://mail.google.com/mail/?view=cm&fs=1` +
        `&to=${encodeURIComponent(toEmail)}` +
        `&su=${encodeURIComponent(pkg.subject)}` +
        `&body=${encodeURIComponent(pkg.cover_letter)}`;

      setPreparedEmailPkg({ ...pkg, gmailUrl });

      // Automatically trigger download of the ready tailored Word (.docx) CV
      const dlLink = document.createElement('a');
      dlLink.href = `${BACKEND_ORIGIN}${pkg.docx_url}`;
      dlLink.download = pkg.docx_filename;
      document.body.appendChild(dlLink);
      dlLink.click();
      document.body.removeChild(dlLink);

      // Open Gmail Compose with full Cover Letter & clean Subject
      window.open(gmailUrl, '_blank', 'noopener,noreferrer');
    } catch (err: any) {
      setError(err.message || 'Failed to prepare Gmail cover letter and Word CV.');
    } finally {
      setDraftingJobId(null);
    }
  };

  // Staging Modal
  const [isStageModalOpen, setIsStageModalOpen] = useState(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    loadInitialData();
  }, []);

  const refreshProfileData = async (): Promise<boolean> => {
    try {
      const p: any = await fetchDbProfile();
      if (p) {
        const uploaded = Boolean(p.profile_uploaded);
        setProfileUploaded(uploaded);
        setCandidateProfile({
          full_name: p.full_name || 'Candidate',
          experience_years: p.experience_years ?? 1.5,
          seniority_level: p.parsed_skills?.seniority_level || 'JUNIOR',
          target_industry: p.parsed_skills?.target_industry || 'qa_tech',
          headline: p.parsed_skills?.headline || 'QA Engineer',
        });
        return uploaded;
      }
    } catch {}
    return false;
  };

  const loadInitialData = async () => {
    const uploaded = await refreshProfileData();
    try {
      const mdData = await fetchSkillsMd();
      setSkillsMdContent(mdData.content);
      setSkillsFilename(mdData.filename);

      if (!uploaded) {
        setVacancies([]);
        setScrapedJobs([]);
        setExtractedSkillsCount(0);
        setJobUrl('');
        setJobText('');
        return;
      }

      const [vacs, dbJobs] = await Promise.all([
        fetchVacancies(),
        fetchScrapedJobs(),
      ]);
      const validJobs = dbJobs.filter((j) => j.status !== 'FILTERED_OUT');
      setVacancies(vacs);
      setScrapedJobs(validJobs);
      if (validJobs.length > 0) {
        setJobUrl(validJobs[0].url);
        setJobText(validJobs[0].description_raw);
      }
      setExtractedSkillsCount(mdData.extracted_skills.length);
    } catch (e) {
      console.error(e);
    }
  };

  const handleRunMultiPortalScrapers = async () => {
    setIsScraping(true);
    setError(null);
    try {
      const res = await triggerMultiPortalScrape(true);
      const validJobs = res.jobs.filter((j) => j.status !== 'FILTERED_OUT');
      setScrapedJobs(validJobs);
      const vacs = await fetchVacancies();
      setVacancies(vacs);
      if (validJobs.length > 0 && !jobUrl) {
        setJobUrl(validJobs[0].url);
        setJobText(validJobs[0].description_raw);
      }
      setScrapeStats({
        total: res.total_processed,
        staged: res.staged_ready_count,
        filteredOut: res.filtered_out_count,
      });
    } catch (err: any) {
      setError(err.message || 'Live multi-portal scrape failed');
    } finally {
      setIsScraping(false);
    }
  };

  const handleSelectScrapedDbJob = (job: DbJobPosting) => {
    setJobUrl(job.url);
    setJobText(job.description_raw);
    setError(null);
  };

  const handleApplyPreset = async (presetId: string) => {
    setIsScraping(true);
    try {
      setError(null);
      const res = await applySkillsPreset(presetId);
      setProfileUploaded(true);
      setActivePresetId(presetId);
      setSkillsMdContent(res.content);
      setExtractedSkillsCount(res.extracted_skills.length);
      setSelectedVariant(presetId === 'qa_tech' ? 'qa_automation' : presetId);

      // Run live role-based scrape matching this preset
      const scrapeRes = await triggerMultiPortalScrape(true);
      const validJobs = scrapeRes.jobs.filter((j) => j.status !== 'FILTERED_OUT');
      setScrapedJobs(validJobs);
      const vacs = await fetchVacancies();
      setVacancies(vacs);
      if (validJobs.length > 0) {
        setJobUrl(validJobs[0].url);
        setJobText(validJobs[0].description_raw);
      }
      await refreshProfileData();

      setSkillsStatusMsg(`✅ Loaded "${presetId}" (${res.extracted_skills.length} skills) & scanned ${validJobs.length} live matching vacancies!`);
      setTimeout(() => setSkillsStatusMsg(null), 5000);
    } catch (err: any) {
      setError(err.message || 'Failed to load profession template');
    } finally {
      setIsScraping(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsScraping(true);
    setError(null);
    try {
      const res = await uploadSkillsMdFile(file);
      setProfileUploaded(true);
      setSkillsMdContent(res.content);
      setSkillsFilename(res.filename);
      setExtractedSkillsCount(res.extracted_skills.length);
      const [refreshedJobs, vacs] = await Promise.all([
        fetchScrapedJobs(),
        fetchVacancies(),
      ]);
      const validJobs = refreshedJobs.filter((j) => j.status !== 'FILTERED_OUT');
      setScrapedJobs(validJobs);
      setVacancies(vacs);
      if (validJobs.length > 0) {
        setJobUrl(validJobs[0].url);
        setJobText(validJobs[0].description_raw);
      }
      await refreshProfileData();
      setSkillsStatusMsg(`✅ ${res.message} Found ${validJobs.length} live verified vacancies.`);
      setTimeout(() => setSkillsStatusMsg(null), 5000);
    } catch (err: any) {
      setError(err.message || 'Failed to upload .md file');
    } finally {
      setIsScraping(false);
    }
  };

  const handleSaveSkillsMdText = async () => {
    setIsScraping(true);
    try {
      const res = await saveSkillsMdText(skillsMdContent);
      setProfileUploaded(true);
      setExtractedSkillsCount(res.extracted_skills.length);
      const scrapeRes = await triggerMultiPortalScrape(true);
      const validJobs = scrapeRes.jobs.filter((j) => j.status !== 'FILTERED_OUT');
      setScrapedJobs(validJobs);
      const vacs = await fetchVacancies();
      setVacancies(vacs);
      await refreshProfileData();
      setSkillsStatusMsg(`✅ Synced CandidateProfile (${res.extracted_skills.length} skills) & scanned ${validJobs.length} live vacancies!`);
      setShowSkillsEditor(false);
      setTimeout(() => setSkillsStatusMsg(null), 5000);
    } catch (err: any) {
      setError(err.message || 'Failed to save skills.md');
    } finally {
      setIsScraping(false);
    }
  };

  const handleSelectVacancy = (vac: PortalVacancyItem) => {
    setJobUrl(vac.url || vac.mock_url);
    setJobText(vac.description);
    setError(null);
  };

  const handleRunAudit = async (overrideLang?: 'en' | 'ka') => {
    const langToUse = overrideLang || cvLanguage;
    if (overrideLang) setCvLanguage(overrideLang);

    if (!jobText && !jobUrl) {
      setError('Please provide either a Job URL or paste the Job Description text.');
      return;
    }
    setError(null);
    setIsAuditing(true);
    setAnswers([]);
    setSaveSuccessMsg(null);

    try {
      const res = await auditJob({
        raw_text: jobText || undefined,
        job_url: jobUrl || undefined,
        variant: selectedVariant,
        skills_md_override: skillsMdContent || undefined,
        cv_language: langToUse,
      });
      setAuditResult(res);
      if (res.recommended_variant) {
        setSelectedVariant(res.recommended_variant);
      }
    } catch (err: any) {
      setError(err.message || 'Audit failed');
    } finally {
      setIsAuditing(false);
    }
  };

  const handleGenerateAnswers = async () => {
    if (!auditResult) return;
    setIsGeneratingAnswers(true);
    try {
      const sampleQuestions =
        cvLanguage === 'ka'
          ? [
              { question: 'კანდიდატის მოკლე მიმოხილვა (Applicant Summary)', field_type: 'textarea' },
              { question: 'რატომ გსურთ ჩვენს გუნდში მუშაობა? (სამოტივაციო წერილი)', field_type: 'textarea' },
              { question: 'როდის შეგიძლიათ მუშაობის დაწყება? (Notice Period)', field_type: 'text' },
              { question: 'რა არის თქვენი სახელფასო მოლოდინი? (Salary Expectation)', field_type: 'text' },
              { question: 'აღწერეთ თქვენი პრაქტიკული გამოცდილება ამ სფეროში', field_type: 'textarea' },
            ]
          : [
              { question: 'Applicant Summary (Introduce yourself)', field_type: 'textarea' },
              { question: 'Why are you interested in joining our team? (Motivational Letter)', field_type: 'textarea' },
              { question: 'When can you start after receiving an offer? (Notice period)', field_type: 'text' },
              { question: 'What are your salary expectations?', field_type: 'text' },
              { question: 'Describe your hands-on experience relevant to this role.', field_type: 'textarea' },
            ];

      const res = await generateAnswers({
        questions: sampleQuestions,
        job_title: auditResult.job_details.title,
        company: auditResult.job_details.company,
        job_description: auditResult.job_details.summary,
        portal: auditResult.job_details.portal,
        variant: selectedVariant,
        cv_language: cvLanguage,
      });

      setAnswers(res.answers);
    } catch (err: any) {
      console.error(err);
    } finally {
      setIsGeneratingAnswers(false);
    }
  };

  const handleSaveToTracker = async () => {
    if (!auditResult) return;
    try {
      await createApplication({
        company: auditResult.job_details.company || 'Unknown Company',
        role: auditResult.job_details.title || 'Specialist',
        portal: auditResult.job_details.portal || 'generic',
        url: jobUrl,
        status: 'Saved',
        match_score: auditResult.match_score,
        ats_score: auditResult.score_breakdown.ats_match,
        recruiter_score: auditResult.score_breakdown.recruiter_match,
        company_reviews: auditResult.company_validation.review_count,
        cv_pdf_url: auditResult.tailored_cv.pdf_url,
        variant_used: selectedVariant,
        notes: `Tailored CV (${cvLanguage.toUpperCase()}): ${auditResult.tailored_cv.pdf_filename} | Salary: ${auditResult.job_details.salary_range || auditResult.tailored_cv.expected_salary} | Start: ${auditResult.tailored_cv.start_date_default}`,
      });
      setSaveSuccessMsg('Saved ApplicationRecord + JobPosting to Relational SQL Database!');
      setTimeout(() => setSaveSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err.message || 'Could not save application');
    }
  };

  const portalsList = ['ALL', 'jobs.ge', 'hr.ge', 'headhunter.ge', 'dou.ua', 'djinni.co', 'justjoin.it', 'greenhouse', 'lever'];
  const industryFilters = [
    { id: 'ALL', label: '🌐 All Industries' },
    { id: 'receptionist_hospitality', label: '🏨 Receptionist & Hospitality' },
    { id: 'healthcare_hospital', label: '🏥 Hospital & Healthcare' },
    { id: 'customer_service', label: '🎧 Customer Service' },
    { id: 'qa_tech', label: '💻 QA & Tech' },
  ];

  const filteredVacancies = vacancies.filter((v) => {
    const matchesPortal = selectedPortalFilter === 'ALL' || v.portal === selectedPortalFilter;
    const matchesInd = selectedIndustryFilter === 'ALL' || v.industry === selectedIndustryFilter;
    return matchesPortal && matchesInd;
  });

  // Only genuinely suitable jobs (>= 60% match and passing all gates) are displayed.
  const visibleJobs = scrapedJobs.filter(
    (j) => j.status !== 'FILTERED_OUT' && (j.suitability_score ?? 0) >= 60
  );
  const filteredDbJobs = visibleJobs.filter((j) => {
    const matchStatus = dbStatusFilter === 'ALL' || j.status === dbStatusFilter;
    const matchPortal = selectedPortalFilter === 'ALL' || j.portal === selectedPortalFilter;
    return matchStatus && matchPortal;
  });

  return (
    <div className="space-y-6">
      {/* Top 1% B2B SaaS Hero Banner */}
      <div className="relative overflow-hidden rounded-2xl border border-sky-500/30 bg-gradient-to-r from-slate-900 via-slate-900 to-indigo-950/80 p-6 shadow-xl">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5">
          <div className="space-y-2 max-w-3xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sky-500/10 border border-sky-500/30 text-sky-300 text-xs font-semibold">
              <Building2 className="w-3.5 h-3.5" />
              <span>SQLModel Relational DB • Automated Portal Scrapers • AI Salary Estimator • EN / KA ქართული</span>
            </div>
            <h1 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight">
              Automated Job Discovery, Strict Language Filtering & Bilingual CV Generation
            </h1>
            <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
              Scrapes <strong>Jobs.ge, HR.ge, DOU.ua, and Djinni.co</strong> into a relational SQL database, shows only the vacancies that match your requirements, estimates unstated salaries via AI, and promotes `&gt;= 75%` matches to the <strong>STAGED</strong> queue.
            </p>
          </div>

          {/* Prominent Bilingual CV Language Switcher */}
          <div className="bg-slate-950/90 border border-slate-800 p-3.5 rounded-2xl flex flex-col gap-2 min-w-[260px]">
            <div className="flex items-center justify-between text-xs font-bold text-slate-300">
              <span className="flex items-center gap-1.5">
                <Languages className="w-4 h-4 text-sky-400" />
                <span>Target CV Output Language</span>
              </span>
              <span className="text-[10px] uppercase px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                Active: {cvLanguage === 'ka' ? 'ქართული' : 'English'}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setCvLanguage('en')}
                className={`py-2 px-3 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 border transition-all ${
                  cvLanguage === 'en'
                    ? 'bg-sky-600 text-white border-sky-400 shadow-md shadow-sky-600/25'
                    : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                }`}
              >
                <span>🇬🇧 English CV</span>
              </button>
              <button
                onClick={() => setCvLanguage('ka')}
                className={`py-2 px-3 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 border transition-all ${
                  cvLanguage === 'ka'
                    ? 'bg-emerald-600 text-white border-emerald-400 shadow-md shadow-emerald-600/25'
                    : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                }`}
              >
                <span>🇬🇪 ქართული CV</span>
              </button>
            </div>
            <span className="text-[10px] text-slate-400 text-center">
              Accepts English or Georgian skills & outputs in your chosen language
            </span>
          </div>
        </div>
      </div>

      {/* 1. Skills.md Upload & CandidateProfile Relational DB Ingestion */}
      <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-4 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 flex-shrink-0">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-bold text-white">
                  SQL CandidateProfile (`POST /api/profile/upload-skills`): <code className="text-emerald-400">{skillsFilename}</code>
                </h3>
                <span className="text-[11px] px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800 font-semibold">
                  {extractedSkillsCount} Skills Indexed in DB
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Upload your <code className="text-slate-300">skills.md</code> or switch between ready-made industry profiles below — automatically re-scores all scraped DB jobs:
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt,.markdown"
              onChange={handleFileUpload}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold transition-colors shadow-sm"
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Upload skills.md to DB</span>
            </button>
            <button
              onClick={() => setShowSkillsEditor(!showSkillsEditor)}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition-colors"
            >
              <Edit3 className="w-3.5 h-3.5" />
              <span>{showSkillsEditor ? 'Hide .md Editor' : 'View / Edit skills.md'}</span>
            </button>
          </div>
        </div>

        {/* Dynamic Candidate Seniority & Industry Profile Gate Badges */}
        <div className="flex items-center gap-2 flex-wrap pt-2 border-t border-slate-800/60">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Active Profile Gate:</span>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-sky-950 text-sky-300 border border-sky-800 font-semibold flex items-center gap-1">
            <span>👤 {candidateProfile?.full_name || 'Candidate'}</span>
          </span>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-indigo-950 text-indigo-300 border border-indigo-800 font-semibold flex items-center gap-1">
            <span>Industry: {candidateProfile?.target_industry === 'qa_tech' ? '💻 Software QA & Tech' : candidateProfile?.target_industry || '💻 Software QA'}</span>
          </span>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-emerald-950 text-emerald-300 border border-emerald-800 font-semibold flex items-center gap-1">
            <span>Experience: {candidateProfile?.experience_years ?? 1.5} Years</span>
          </span>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-amber-950 text-amber-300 border border-amber-800 font-semibold flex items-center gap-1">
            <span>Target: {candidateProfile?.seniority_level === 'JUNIOR' ? 'Junior - Mid' : candidateProfile?.seniority_level || 'Junior - Mid'}</span>
          </span>
          {candidateProfile?.headline && (
            <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">
              {candidateProfile.headline}
            </span>
          )}
        </div>

        {/* 1-Click Industry Profile Preset Selector */}
        <div className="pt-2 border-t border-slate-800/80">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
            <Briefcase className="w-3.5 h-3.5 text-sky-400" />
            <span>1-Click Profession Profile Templates (QA/Tech, Receptionist, Customer Service, Hospital):</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            {INDUSTRY_PRESETS.map((preset) => {
              const isCurrent = activePresetId === preset.id;
              return (
                <button
                  key={preset.id}
                  onClick={() => handleApplyPreset(preset.id)}
                  className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between ${
                    isCurrent
                      ? 'bg-sky-950/60 border-sky-500 text-white shadow-sm'
                      : 'bg-slate-950/70 border-slate-800 text-slate-300 hover:border-slate-700 hover:text-white'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="text-xs font-bold truncate">{preset.label}</div>
                    <div className="text-[10px] text-slate-400">{preset.badge}</div>
                  </div>
                  {isCurrent && <CheckCircle2 className="w-4 h-4 text-sky-400 flex-shrink-0" />}
                </button>
              );
            })}
          </div>
        </div>

        {skillsStatusMsg && (
          <div className="text-xs text-emerald-300 font-medium bg-emerald-950/40 border border-emerald-800/60 px-3.5 py-2 rounded-xl">
            {skillsStatusMsg}
          </div>
        )}

        {showSkillsEditor && (
          <div className="pt-2 space-y-2">
            <textarea
              rows={9}
              value={skillsMdContent}
              onChange={(e) => setSkillsMdContent(e.target.value)}
              placeholder="Write or paste candidate skills in English or Georgian (ქართულად)..."
              className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3.5 text-xs text-slate-200 font-mono leading-relaxed focus:outline-none focus:border-sky-500"
            />
            <div className="flex justify-end">
              <button
                onClick={handleSaveSkillsMdText}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold"
              >
                Save & Sync skills.md to SQL DB
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 2. Automated Multi-Portal Scraper Engine + Strict Language Gate + AI Salary Estimator */}
      <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-4">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Database className="w-4 h-4 text-emerald-400" />
              Automated Portal Scrapers & Intelligent Market Filter (`JobPosting` SQL Table)
            </h3>
            <p className="text-xs text-slate-400">
              Scrapes <strong>Jobs.ge</strong>, <strong>HR.ge</strong>, <strong>DOU.ua</strong>, and <strong>Djinni.co</strong>. Only jobs matching your requirements are shown, salaries are estimated via AI, and `&gt;= 75%` matches are promoted to <strong>STAGED</strong>.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleRunMultiPortalScrapers}
              disabled={isScraping || !profileUploaded}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-bold shadow-md shadow-emerald-600/20 transition-all disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isScraping ? 'animate-spin' : ''}`} />
              <span>{isScraping ? 'Scanning Live Portals...' : 'Run Live Role Scrapers'}</span>
            </button>

            {['ALL', 'STAGED', 'AUDITED'].map((st) => (
              <button
                key={st}
                onClick={() => setDbStatusFilter(st)}
                className={`text-[11px] px-2.5 py-1.5 rounded-lg font-semibold transition-colors ${
                  dbStatusFilter === st
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
                }`}
              >
                {st === 'ALL' ? `Suitable Matches (${visibleJobs.length})` : st === 'STAGED' ? 'Ready >=75%' : 'Match 60-74%'}
              </button>
            ))}
          </div>
        </div>

        {visibleJobs.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-800/60">
            <span className="text-[10px] font-bold uppercase text-slate-500 mr-1">Portals:</span>
            {['ALL', 'jobs.ge', 'hr.ge', 'djinni.co', 'dou.ua', 'justjoin.it'].map((p) => (
              <button
                key={p}
                onClick={() => setSelectedPortalFilter(p)}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition-colors ${
                  selectedPortalFilter === p
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        )}

        {preparedEmailPkg && (
          <div className="p-4 rounded-xl bg-sky-950/35 border border-sky-700/60 text-xs space-y-2.5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <span className="text-[10px] font-bold uppercase text-sky-400 block">
                  Gmail Draft + Tailored Word CV Ready
                </span>
                <span className="text-white font-semibold">
                  {preparedEmailPkg.title} ({preparedEmailPkg.company}) &mdash; Subject: <code className="text-sky-300">{preparedEmailPkg.subject}</code>
                </span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <a
                  href={`${BACKEND_ORIGIN}${preparedEmailPkg.docx_url}`}
                  download={preparedEmailPkg.docx_filename}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Word (.docx)</span>
                </a>
                <a
                  href={`${BACKEND_ORIGIN}${preparedEmailPkg.pdf_url}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-semibold"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>PDF CV</span>
                </a>
                <a
                  href={preparedEmailPkg.gmailUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold"
                >
                  <Mail className="w-3.5 h-3.5" />
                  <span>Re-open Gmail</span>
                </a>
                <button
                  type="button"
                  onClick={() => setPreparedEmailPkg(null)}
                  className="px-2 py-1 text-slate-400 hover:text-white"
                >
                  Dismiss
                </button>
              </div>
            </div>
            <div className="bg-slate-950/80 border border-slate-800 rounded-lg p-2.5 text-[11px] text-slate-300 whitespace-pre-wrap">
              {preparedEmailPkg.cover_letter}
            </div>
          </div>
        )}

        {scrapeStats && (
          <div className="text-xs bg-emerald-950/30 border border-emerald-800/60 text-emerald-300 px-3.5 py-2 rounded-xl flex items-center justify-between flex-wrap gap-2">
            <span>
              ✅ Found <strong>{scrapeStats.total - scrapeStats.filteredOut}</strong> jobs matching your requirements
            </span>
            <span className="text-emerald-400 font-bold">
              {scrapeStats.staged} ready to apply (&gt;= 75% match)
            </span>
          </div>
        )}

        {filteredDbJobs.length === 0 && (
          <div className="text-xs text-slate-400 text-center py-8 border border-dashed border-slate-700 bg-slate-950/60 rounded-xl space-y-3">
            {!profileUploaded ? (
              <>
                <h4 className="text-sm font-bold text-white">Upload your skills.md file to scan tailored live vacancies</h4>
                <p className="text-xs text-slate-400 max-w-md mx-auto">
                  Your discovery feed stays 100% empty until your profile is uploaded. Upload <code className="text-sky-300">skills.md</code> to search live Jobs.ge, HR.ge, DOU.ua, Djinni.co &amp; JustJoin.it roles matched to your exact stack.
                </p>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-bold shadow-md transition-colors"
                >
                  <Upload className="w-3.5 h-3.5" />
                  <span>Upload skills.md Now</span>
                </button>
              </>
            ) : (
              <div className="space-y-1">
                <h4 className="text-sm font-bold text-white">No matching live vacancies found in this view</h4>
                <p className="text-xs text-slate-400">
                  Click <strong>Run Live Role Scrapers</strong> above to scan active portals with HTTP 200 content verification.
                </p>
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {filteredDbJobs.map((job) => {
            const isStaged = job.status === 'STAGED';
            return (
              <div
                key={`${job.portal}-${job.external_id}`}
                onClick={() => handleSelectScrapedDbJob(job)}
                className={`p-3.5 rounded-xl border cursor-pointer transition-all flex flex-col justify-between ${
                  isStaged
                    ? 'bg-slate-950 border-emerald-700/60 hover:border-emerald-500'
                    : 'bg-slate-950/70 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-1 flex-wrap">
                    <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-slate-900 text-sky-400 border border-slate-700">
                      {job.portal} • {job.market}
                    </span>
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                        isStaged
                          ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                          : 'bg-amber-950 text-amber-300 border border-amber-800'
                      }`}
                    >
                      {job.status} ({job.suitability_score}%)
                    </span>
                  </div>

                  <h4 className="text-xs font-bold text-white line-clamp-2 leading-snug">{job.title}</h4>
                  <div className="text-[11px] text-slate-400">{job.company}</div>

                  {/* Honest Salary Display: ONLY show numbers if explicitly stated in job description */}
                  {job.salary_min && job.salary_max ? (
                    <div className="flex items-center gap-1.5 text-[11px] pt-0.5">
                      <DollarSign className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                      <span className="text-emerald-300 font-semibold">
                        {job.salary_min.toLocaleString()}–{job.salary_max.toLocaleString()} {job.salary_currency}
                      </span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-700">
                        📄 Stated
                      </span>
                    </div>
                  ) : (
                    <div className="text-[10px] text-slate-500 pt-0.5">
                      {(job.description_raw || '').includes('არ ითვალისწინებს ანაზღაურებას') ||
                      (job.description_raw || '').toLowerCase().includes('unpaid')
                        ? 'Salary: Unpaid Internship'
                        : 'Salary not specified'}
                    </div>
                  )}

                  {job.deadline_text && (
                    <div className="text-[10px] text-amber-300 bg-amber-950/40 border border-amber-800/60 px-2 py-0.5 rounded-md inline-block">
                      📅 Deadline: {job.deadline_text}
                    </div>
                  )}

                  <div className="text-[10px] text-slate-400 line-clamp-2 pt-1 border-t border-slate-800/60">
                    <span>{job.match_rationale}</span>
                  </div>
                </div>

                <div className="pt-2 mt-2 border-t border-slate-800/60 space-y-2 text-[10px]">
                  <div className="flex items-center justify-between">
                    <span className="text-sky-400 font-semibold">Load into Auditor</span>
                    <span className="text-slate-500">Lang: {job.language_requirements.join(', ')}</span>
                  </div>

                  <div className="flex items-center gap-1.5 pt-1">
                    {(job.delivery_channel === 'EMAIL' || Boolean(job.target_email)) ? (
                      <button
                        type="button"
                        disabled={draftingJobId === job.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDraftInGmail(job);
                        }}
                        className="flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg bg-rose-600/90 hover:bg-rose-500 text-white font-semibold transition-colors disabled:opacity-50"
                        title="Generate Tailored Word CV (.docx) + Cover Letter and open Gmail Draft"
                      >
                        <Mail className="w-3 h-3" />
                        <span>{draftingJobId === job.id ? 'Preparing...' : 'Draft in Gmail'}</span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSelectScrapedDbJob(job);
                          setIsStageModalOpen(true);
                        }}
                        className="flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold transition-colors"
                        title="Open Semantic Autofill / HITL Stager"
                      >
                        <Play className="w-3 h-3" />
                        <span>Open & Fill Form</span>
                      </button>
                    )}
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800 transition-colors"
                      title="Open Original Job Link"
                    >
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 4. Main Audit Input & Output Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Job URL & Description Input */}
        <div className="lg:col-span-6 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-semibold uppercase text-slate-400">
                  Vacancy Application URL (Jobs.ge, HR.ge, DOU.ua, Djinni, etc.)
                </label>
                {jobUrl && (
                  <a
                    href={jobUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-sky-400 hover:underline flex items-center gap-1"
                  >
                    <span>Open Portal Page</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
              <input
                type="text"
                value={jobUrl}
                onChange={(e) => setJobUrl(e.target.value)}
                placeholder="https://jobs.ge/... or https://hr.ge/... or https://jobs.dou.ua/..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-semibold uppercase text-slate-400">
                  Job Description (English or Georgian / ქართულად)
                </label>
                <span className="text-[11px] text-slate-500">Auto-estimates salary if unstated</span>
              </div>
              <textarea
                rows={8}
                value={jobText}
                onChange={(e) => setJobText(e.target.value)}
                placeholder="Paste any job description in English or Georgian..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-300 focus:outline-none focus:border-sky-500 leading-relaxed"
              />
            </div>

            {/* Dual Action Buttons for English or Georgian CV Generation */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
              <button
                onClick={() => handleRunAudit('en')}
                disabled={isAuditing}
                className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs text-white bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 shadow-lg shadow-sky-600/20 transition-all disabled:opacity-50"
              >
                {isAuditing && cvLanguage === 'en' ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Generating English CV...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    <span>🇬🇧 Audit & Generate English CV</span>
                  </>
                )}
              </button>

              <button
                onClick={() => handleRunAudit('ka')}
                disabled={isAuditing}
                className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs text-white bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-lg shadow-emerald-600/20 transition-all disabled:opacity-50"
              >
                {isAuditing && cvLanguage === 'ka' ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>მიმდინარეობს ქართული CV-ის შექმნა...</span>
                  </>
                ) : (
                  <>
                    <Languages className="w-4 h-4" />
                    <span>🇬🇪 Audit & Generate ქართული CV</span>
                  </>
                )}
              </button>
            </div>

            <button
              onClick={() => setIsStageModalOpen(true)}
              className="w-full flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-xs text-indigo-300 bg-indigo-950/60 hover:bg-indigo-900/70 border border-indigo-700/60 transition-all"
            >
              <Play className="w-4 h-4 fill-current" />
              <span>Launch Playwright Live Form Stager (Fills Form, AI Salary, 1-Week Start & CAPTCHA)</span>
            </button>

            {error && (
              <div className="p-3 bg-rose-950/30 border border-rose-900/60 rounded-xl text-xs text-rose-300 flex items-center gap-2">
                <AlertOctagon className="w-4 h-4 text-rose-400 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Match Breakdown, AI Salary Estimate, Company 3+ Reviews Gate, Tailored EN/KA PDF CV & Gaps */}
        <div className="lg:col-span-6 space-y-4">
          {auditResult ? (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
              {/* Top Row: Role & Overall Score */}
              <div className="flex items-center justify-between border-b border-slate-800 pb-4 gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-sky-950 text-sky-400 border border-sky-800">
                      {auditResult.job_details.portal || 'Portal'}
                    </span>
                    <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                      {auditResult.tailored_cv.cv_language === 'ka' ? '🇬🇪 ქართული CV' : '🇬🇧 English CV'}
                    </span>
                    <span className="text-xs text-slate-400 truncate">{auditResult.job_details.company}</span>
                  </div>
                  <h3 className="text-base sm:text-lg font-bold text-white mt-1">{auditResult.job_details.title}</h3>
                  {auditResult.job_details.salary_range && (
                    <div className="text-xs text-emerald-400 font-semibold mt-1 flex items-center gap-1.5">
                      <DollarSign className="w-3.5 h-3.5" />
                      <span>Market Compensation: {auditResult.job_details.salary_range}</span>
                    </div>
                  )}
                </div>

                <div className="w-16 h-16 rounded-2xl flex flex-col items-center justify-center border font-bold text-lg bg-emerald-950/60 text-emerald-400 border-emerald-500/40 flex-shrink-0">
                  <span>{auditResult.match_score}%</span>
                  <span className="text-[9px] font-normal uppercase text-slate-400">Overall</span>
                </div>
              </div>

              {/* 3 Core Metrics: Skills Match, ATS Match, Recruiter Match */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-center">
                  <span className="text-[10px] uppercase text-slate-400 font-semibold block">Skills Match</span>
                  <span className="text-lg font-bold text-sky-400">{auditResult.score_breakdown.skills_match}%</span>
                </div>
                <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-center">
                  <span className="text-[10px] uppercase text-slate-400 font-semibold block">ATS Match</span>
                  <span className="text-lg font-bold text-emerald-400">{auditResult.score_breakdown.ats_match}%</span>
                </div>
                <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-center">
                  <span className="text-[10px] uppercase text-slate-400 font-semibold block">Recruiter Match</span>
                  <span className="text-lg font-bold text-indigo-400">{auditResult.score_breakdown.recruiter_match}%</span>
                </div>
              </div>

              {/* Company 3+ Reviews Validation Gate */}
              <div
                className={`p-3.5 rounded-xl border text-xs space-y-1.5 ${
                  auditResult.company_validation.passed_gate
                    ? 'bg-emerald-950/25 border-emerald-800/60 text-emerald-300'
                    : 'bg-rose-950/30 border-rose-800 text-rose-300'
                }`}
              >
                <div className="flex items-center justify-between font-semibold flex-wrap gap-1">
                  <span className="flex items-center gap-1.5">
                    <Star className="w-4 h-4 fill-current text-amber-400" />
                    Company Review Validation (3+ Reviews Gate)
                  </span>
                  <span>
                    {auditResult.company_validation.review_count} Reviews • {auditResult.company_validation.rating !== null ? `${auditResult.company_validation.rating}★` : (auditResult.company_validation.reputation || 'UNVERIFIED')}
                  </span>
                </div>
                <p className="text-[11px] text-slate-300">{auditResult.company_validation.verdict}</p>
              </div>

              {/* Generated Per-Vacancy Human-Tone PDF & HTML CV Card */}
              <div className="p-4 bg-sky-950/25 border border-sky-800/60 rounded-xl space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-sky-400 block">
                      Generated Per-Vacancy CV ({auditResult.tailored_cv.cv_language === 'ka' ? 'ქართული ენა / Georgian' : 'English'})
                    </span>
                    <span className="text-sm font-bold text-white truncate block">
                      {auditResult.tailored_cv.pdf_filename}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {auditResult.tailored_cv.docx_url && (
                      <a
                        href={`${BACKEND_ORIGIN}${auditResult.tailored_cv.docx_url}`}
                        download={auditResult.tailored_cv.docx_filename}
                        className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-sm transition-colors"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <span>Download Word (.docx)</span>
                      </a>
                    )}
                    <a
                      href={`${BACKEND_ORIGIN}${auditResult.tailored_cv.pdf_url}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold shadow-sm transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Download PDF CV</span>
                    </a>
                    {auditResult.tailored_cv.html_preview_url && (
                      <a
                        href={`${BACKEND_ORIGIN}${auditResult.tailored_cv.html_preview_url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-semibold shadow-sm transition-colors"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        <span>Printable View</span>
                      </a>
                    )}
                  </div>
                </div>

                <div className="text-xs text-slate-300 bg-slate-950/80 p-3 rounded-lg border border-slate-800 space-y-1.5">
                  <div>
                    <strong className="text-sky-300">
                      {auditResult.tailored_cv.cv_language === 'ka' ? 'პროფესიული მიმოხილვა (Human Tone):' : 'Applicant Summary (Human Tone):'}
                    </strong>{' '}
                    {auditResult.tailored_cv.applicant_summary}
                  </div>
                  <div>
                    <strong className="text-emerald-400">
                      {auditResult.tailored_cv.cv_language === 'ka' ? 'მუშაობის დაწყების დრო:' : 'Default Start Date:'}
                    </strong>{' '}
                    {auditResult.tailored_cv.start_date_default}
                  </div>
                </div>

                {/* Motivational Letter Preview */}
                <div className="text-xs text-slate-300 bg-slate-950/80 p-3 rounded-lg border border-slate-800">
                  <strong className="text-rose-400 block mb-1">
                    {auditResult.tailored_cv.cv_language === 'ka'
                      ? 'სამოტივაციო წერილი (Motivational Letter — ქართულად):'
                      : 'Tailored Motivational Letter (Ready for DOU.ua / Recruiter):'}
                  </strong>
                  <p className="whitespace-pre-line text-[11px] text-slate-300 leading-relaxed">
                    {auditResult.tailored_cv.dou_motivational_letter}
                  </p>
                </div>
              </div>

              {/* Skills & Gaps Breakdown */}
              <div className="space-y-2.5">
                <div>
                  <span className="text-xs font-semibold text-emerald-400 block mb-1">
                    ✓ Matched Skills ({auditResult.matched_skills.length})
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {auditResult.matched_skills.map((s) => (
                      <span key={s} className="text-[11px] bg-emerald-950/50 text-emerald-300 border border-emerald-800/60 px-2.5 py-0.5 rounded-full">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>

                {auditResult.gaps && auditResult.gaps.length > 0 && (
                  <div className="space-y-1.5 pt-1">
                    <span className="text-xs font-semibold text-amber-400 block">
                      🔍 Identified Gaps & Bridge Strategy ({auditResult.gaps.length})
                    </span>
                    {auditResult.gaps.map((g, i) => (
                      <div key={i} className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg text-xs space-y-1">
                        <div className="font-semibold text-amber-300">
                          Gap: {g.skill_or_area} <span className="text-[10px] uppercase text-slate-500">({g.severity})</span>
                        </div>
                        <div className="text-[11px] text-slate-400">{g.gap_description}</div>
                        <div className="text-[11px] text-emerald-400">
                          <strong>Bridge Strategy:</strong> {g.bridge_strategy}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Bottom Action Buttons */}
              <div className="flex items-center gap-2 pt-2 border-t border-slate-800">
                <button
                  onClick={handleSaveToTracker}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
                >
                  <BookmarkPlus className="w-4 h-4 text-sky-400" />
                  <span>Save to SQL Tracker</span>
                </button>

                <button
                  onClick={() => setIsStageModalOpen(true)}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2.5 px-3 rounded-xl bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 text-xs font-semibold text-white shadow-md shadow-sky-600/20 transition-all"
                >
                  <Play className="w-4 h-4 fill-current" />
                  <span>Apply / Stage with Playwright</span>
                </button>
              </div>

              {saveSuccessMsg && (
                <div className="text-center text-xs text-emerald-400 font-medium py-1">
                  ✓ {saveSuccessMsg}
                </div>
              )}
            </div>
          ) : (
            <div className="bg-slate-900/50 border border-dashed border-slate-800 rounded-2xl p-10 flex flex-col items-center justify-center text-center space-y-3 min-h-[420px]">
              <div className="w-12 h-12 rounded-2xl bg-slate-800/80 flex items-center justify-center text-sky-400">
                <Search className="w-6 h-6" />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-200">
                  Ready to Audit & Generate Your English or Georgian (ქართული) PDF CV
                </h4>
                <p className="text-xs text-slate-400 max-w-md mt-1">
                  Select any scraped vacancy from the <strong>SQLite JobPosting table</strong> above or choose an industry template, then click <strong>🇬🇧 Generate English CV</strong> or <strong>🇬🇪 Generate ქართული CV</strong>.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Screening Answers Generator */}
      {auditResult && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <FileText className="w-4 h-4 text-sky-400" />
                Grounded Screening Answers ({cvLanguage === 'ka' ? 'ქართულ ენაზე' : 'English'} — Summary, Motivation, AI Salary, 1-Week Start)
              </h3>
              <p className="text-xs text-slate-400">
                All answers use a natural human tone and default to starting <strong>1 week after offer (1 კვირა შეთავაზებიდან)</strong>.
              </p>
            </div>

            <button
              onClick={handleGenerateAnswers}
              disabled={isGeneratingAnswers}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-slate-800 hover:bg-slate-700 transition-colors disabled:opacity-50"
            >
              {isGeneratingAnswers ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Synthesizing...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5 text-sky-400" />
                  <span>Generate Form Answers ({cvLanguage.toUpperCase()})</span>
                </>
              )}
            </button>
          </div>

          {answers.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
              {answers.map((ans, idx) => (
                <div key={idx} className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs font-semibold text-slate-300">{ans.question}</span>
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-sky-950 text-sky-400 border border-sky-900">
                      {cvLanguage === 'ka' ? 'ქართული' : 'Human Tone'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed bg-slate-900/50 p-2.5 rounded-lg border border-slate-800 whitespace-pre-line">
                    {ans.answer}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Stage Modal */}
      <StageModal
        isOpen={isStageModalOpen}
        onClose={() => setIsStageModalOpen(false)}
        jobUrl={jobUrl}
        variant={selectedVariant}
        jobTitle={auditResult?.job_details.title}
        company={auditResult?.job_details.company}
        companyValidation={auditResult?.company_validation}
        tailoredCv={auditResult?.tailored_cv}
      />
    </div>
  );
};
