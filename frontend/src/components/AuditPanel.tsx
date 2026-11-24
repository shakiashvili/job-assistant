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
  fetchSkillsMd,
  uploadSkillsMdFile,
  saveSkillsMdText,
  fetchScrapedJobs,
  fetchDbProfile,
  triggerMultiPortalScrape,
  triggerAsyncScrape,
  fetchScrapeTaskStatus,
  prepareJobEmailPackage,
  saveJob,
  unsaveJob,
  fetchSavedJobs,
  fetchSavedSearches,
  createSavedSearch,
  deleteSavedSearch,
  fetchNotifications,
  markNotificationRead,
  BACKEND_ORIGIN
} from '../services/api';
import {
  JobAuditResponse,
  ScreeningAnswer,
  DbJobPosting,
  JobSearchParams,
  SavedSearchItem,
  NotificationItem,
} from '../types';
import { StageModal } from './StageModal';
import { DiscoveryFeed } from './DiscoveryFeed';

const DEFAULT_JOB_FILTERS: JobSearchParams = {
  page: 1,
  limit: 12,
  portal: 'ALL',
  status: 'ALL',
  tier: 'ALL',
  min_score: 60,
  search: '',
  remote_type: 'ALL',
  country: '',
  city: '',
  technology: '',
  language: 'ALL',
  experience_level: 'ALL',
  employment_type: 'ALL',
  sort_by: 'relevance',
  only_new: false,
  only_saved: false,
  b2b_only: false,
  geo_eligible_only: false,
};

export const AuditPanel: React.FC = () => {
  // Relational DB Scraped JobPostings State + Server-Side Pagination
  const [scrapedJobs, setScrapedJobs] = useState<DbJobPosting[]>([]);
  const [filters, setFilters] = useState<JobSearchParams>(DEFAULT_JOB_FILTERS);
  const filtersRef = useRef<JobSearchParams>(DEFAULT_JOB_FILTERS);
  const searchAbortRef = useRef<AbortController | null>(null);
  const searchSeqRef = useRef<number>(0);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isLoadingJobs, setIsLoadingJobs] = useState<boolean>(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [savedJobIds, setSavedJobIds] = useState<Set<number>>(new Set());
  const [savedSearches, setSavedSearches] = useState<SavedSearchItem[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [page, setPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [totalJobs, setTotalJobs] = useState<number>(0);
  const [isScraping, setIsScraping] = useState(false);
  const [scrapeStats, setScrapeStats] = useState<{
    total: number;
    staged: number;
    filteredOut: number;
  } | null>(null);
  const [scrapeTaskInfo, setScrapeTaskInfo] = useState<{
    status: string;
    progressPct: number;
    errorMessage?: string | null;
  } | null>(null);

  const [jobUrl, setJobUrl] = useState('');
  const [profileUploaded, setProfileUploaded] = useState<boolean>(false);
  const [jobText, setJobText] = useState('');
  const [selectedVariant, setSelectedVariant] = useState('qa_automation');
  const [cvLanguage, setCvLanguage] = useState<'en' | 'ka'>('en');
  const [candidateProfile, setCandidateProfile] = useState<{
    full_name?: string;
    experience_years?: number;
    max_allowed_years?: number;
    seniority_level?: string;
    target_industry?: string;
    detected_industry?: string;
    primary_role?: string;
    adjacent_roles?: string[];
    education?: Array<{ degree?: string; field_of_study?: string; institution?: string }>;
    courses_and_certifications?: string[];
    eligible_internships?: boolean;
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
    gmail_draft_saved?: boolean;
    gmail_drafts_url?: string | null;
    attached_files?: string[];
    draft_error?: string | null;
  } | null>(null);

  const handleDraftInGmail = async (job: DbJobPosting) => {
    setDraftingJobId(job.id);
    setError(null);
    try {
      const pkg = await prepareJobEmailPackage(job.id, 'auto');
      const toEmail = pkg.recipient_email || job.target_email || '';
      const composeUrl =
        `https://mail.google.com/mail/?view=cm&fs=1` +
        `&to=${encodeURIComponent(toEmail)}` +
        `&su=${encodeURIComponent(pkg.subject)}` +
        `&body=${encodeURIComponent(pkg.cover_letter)}`;
      const gmailUrl = pkg.gmail_draft_saved && pkg.gmail_drafts_url ? pkg.gmail_drafts_url : composeUrl;

      setPreparedEmailPkg({ ...pkg, gmailUrl });

      // Only force local browser download if Gmail IMAP/OAuth draft couldn't attach file automatically
      if (!pkg.gmail_draft_saved) {
        const dlLink = document.createElement('a');
        dlLink.href = `${BACKEND_ORIGIN}${pkg.docx_url}`;
        dlLink.download = pkg.docx_filename;
        document.body.appendChild(dlLink);
        dlLink.click();
        document.body.removeChild(dlLink);
      }

      // Open Gmail Drafts (file already attached!) or Compose fallback
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
          experience_years: p.experience_years ?? null,
          max_allowed_years:
            p.parsed_skills?.max_allowed_years ??
            (p.experience_years != null ? Math.min(p.experience_years + 0.5, 2.0) : 2.0),
          seniority_level: p.parsed_skills?.seniority_level || 'JUNIOR',
          target_industry: p.parsed_skills?.target_industry || 'general_professional',
          detected_industry: p.parsed_skills?.detected_industry || p.parsed_skills?.target_industry || 'Domain-Agnostic',
          primary_role: p.parsed_skills?.primary_role || p.parsed_skills?.headline || 'Specialist',
          adjacent_roles: p.parsed_skills?.adjacent_roles || [],
          education: p.parsed_skills?.education || [],
          courses_and_certifications: p.parsed_skills?.courses_and_certifications || [],
          eligible_internships: Boolean(p.parsed_skills?.eligible_internships),
          headline: p.parsed_skills?.headline || 'Specialist',
        });
        return uploaded;
      }
    } catch {}
    return false;
  };

  const [tierCounts, setTierCounts] = useState<{
    ALL: number;
    DIRECT: number;
    ADJACENT: number;
    PUBLIC_INTERNSHIP: number;
  }>({ ALL: 0, DIRECT: 0, ADJACENT: 0, PUBLIC_INTERNSHIP: 0 });

  const [statusCounts, setStatusCounts] = useState<{
    ALL: number;
    STAGED: number;
    AUDITED: number;
  }>({ ALL: 0, STAGED: 0, AUDITED: 0 });

  const loadPagedJobs = async (overrides?: Partial<JobSearchParams>) => {
    const merged: JobSearchParams = { ...filtersRef.current, ...overrides };
    filtersRef.current = merged;

    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
    }
    const controller = new AbortController();
    searchAbortRef.current = controller;
    const seq = ++searchSeqRef.current;

    setIsLoadingJobs(true);
    setJobsError(null);
    try {
      const tierParam = merged.tier === 'PUBLIC_INTERNSHIP' ? 'internship' : merged.tier;
      const res = await fetchScrapedJobs({ ...merged, tier: tierParam }, controller.signal);
      if (seq !== searchSeqRef.current) return res;
      setScrapedJobs(res.items || []);
      setPage(res.page || 1);
      setTotalPages(res.total_pages || 1);
      setTotalJobs(res.total || 0);
      if (res.tier_counts) setTierCounts(res.tier_counts);
      if (res.status_counts) setStatusCounts(res.status_counts);
      return res;
    } catch (err: any) {
      if (err?.name === 'AbortError' || seq !== searchSeqRef.current) {
        return { items: [], total: 0, page: merged.page || 1, limit: merged.limit || 12, total_pages: 1 };
      }
      setJobsError(err?.message || 'Failed to load vacancies. Please check your connection and try again.');
      return { items: [], total: 0, page: merged.page || 1, limit: merged.limit || 12, total_pages: 1 };
    } finally {
      if (seq === searchSeqRef.current) {
        setIsLoadingJobs(false);
      }
    }
  };

  const applyFilters = (patch: Partial<JobSearchParams>, debounceMs = 0) => {
    const next: JobSearchParams = { ...filtersRef.current, ...patch, page: patch.page ?? 1 };
    filtersRef.current = next;
    setFilters(next);
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    if (debounceMs > 0) {
      debounceTimerRef.current = setTimeout(() => {
        void loadPagedJobs(next);
      }, debounceMs);
    } else {
      void loadPagedJobs(next);
    }
  };

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (searchAbortRef.current) searchAbortRef.current.abort();
    };
  }, []);

  const handleToggleSaveJob = async (job: DbJobPosting) => {
    try {
      const next = new Set(savedJobIds);
      if (next.has(job.id)) {
        await unsaveJob(job.id);
        next.delete(job.id);
      } else {
        await saveJob(job.id);
        next.add(job.id);
      }
      setSavedJobIds(next);
      if (filtersRef.current.only_saved) {
        await loadPagedJobs({ page: 1 });
      }
    } catch (err) {
      console.error('Could not toggle saved job:', err);
    }
  };

  const loadInitialData = async () => {
    const uploaded = await refreshProfileData();
    try {
      const [mdData, savedRes, ssList, notifList] = await Promise.all([
        fetchSkillsMd(),
        fetchSavedJobs().catch(() => ({ items: [] })),
        fetchSavedSearches().catch(() => []),
        fetchNotifications().catch(() => []),
      ]);
      setSkillsMdContent(mdData.content);
      setSkillsFilename(mdData.filename);
      setSavedJobIds(new Set((savedRes.items || []).map((it) => it.job.id)));
      setSavedSearches(ssList);
      setNotifications(notifList);

      if (!uploaded) {
        setScrapedJobs([]);
        setTotalJobs(0);
        setTotalPages(1);
        setExtractedSkillsCount(0);
        setJobUrl('');
        setJobText('');
        return;
      }

      const paged = await loadPagedJobs({ page: 1 });
      const validJobs = (paged.items || []).filter((j) => j.status !== 'FILTERED_OUT');
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
    setScrapeTaskInfo({ status: 'QUEUED', progressPct: 10 });
    try {
      let filteredOutCount = 0;
      try {
        const asyncStart = await triggerAsyncScrape(true);
        const taskId = asyncStart.task_id;
        for (let attempt = 0; attempt < 45; attempt++) {
          await new Promise((r) => setTimeout(r, 1200));
          const st = await fetchScrapeTaskStatus(taskId);
          setScrapeTaskInfo({
            status: st.status,
            progressPct: st.progress_pct ?? (st.status === 'COMPLETED' ? 100 : 50),
            errorMessage: st.error_message,
          });
          if (st.status === 'COMPLETED') {
            filteredOutCount = st.filtered_out_count || 0;
            break;
          }
          if (st.status === 'FAILED') {
            throw new Error(st.error_message || 'Background scan failed');
          }
        }
      } catch (_asyncErr) {
        const res = await triggerMultiPortalScrape(true);
        filteredOutCount = res.filtered_out_count || 0;
        setScrapeTaskInfo({ status: 'COMPLETED', progressPct: 100 });
      }
      const paged = await loadPagedJobs({ page: 1 });
      const validJobs = paged.items || [];
      if (validJobs.length > 0 && !jobUrl) {
        setJobUrl(validJobs[0].url);
        setJobText(validJobs[0].description_raw);
      }
      setScrapeStats({
        total: paged.total || validJobs.length,
        staged: validJobs.filter((j) => j.status === 'STAGED').length,
        filteredOut: filteredOutCount,
      });
    } catch (err: any) {
      setError(err.message || 'Live multi-portal scrape failed');
      setScrapeTaskInfo({ status: 'FAILED', progressPct: 0, errorMessage: err?.message });
    } finally {
      setIsScraping(false);
    }
  };

  const handleSelectScrapedDbJob = (job: DbJobPosting) => {
    setJobUrl(job.url);
    setJobText(job.description_raw);
    setError(null);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setIsScraping(true);
    setError(null);
    try {
      const res = await uploadSkillsMdFile(file);
      setProfileUploaded(true);
      setSkillsMdContent(res.content);
      setSkillsFilename(res.filename);
      setExtractedSkillsCount(res.extracted_skills.length);
      await refreshProfileData();

      const paged = await loadPagedJobs({ page: 1 });
      const validJobs = paged.items || [];
      if (validJobs.length > 0) {
        setJobUrl(validJobs[0].url);
        setJobText(validJobs[0].description_raw);
      }
      setSkillsStatusMsg(`✅ ${res.message} Matched ${paged.total || validJobs.length} vacancies! Scanning live portals for fresh listings...`);

      // Trigger live portal refresh after profile & initial matches are already displayed
      try {
        await triggerMultiPortalScrape(true);
        const freshPaged = await loadPagedJobs({ page: 1 });
        setSkillsStatusMsg(`Profile indexed: ${res.message}. Found ${freshPaged.total || validJobs.length} live verified vacancies.`);
      } catch (refreshErr: any) {
        setSkillsStatusMsg(`Profile indexed (${res.message}). Live portal scan could not complete automatically: ${refreshErr?.message || 'try clicking Run Live Role Scrapers'}.`);
      }
      setTimeout(() => setSkillsStatusMsg(null), 6000);
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
      if (scrapeRes.rejection_reasons?.length) {
        console.debug('[TalentFlow Matcher Diagnostics] Rejected vacancies:', scrapeRes.rejection_reasons);
      }
      const paged = await loadPagedJobs({ page: 1 });
      await refreshProfileData();
      setSkillsStatusMsg(`✅ Synced CandidateProfile (${res.extracted_skills.length} skills) & scanned ${paged.total} live vacancies!`);
      setShowSkillsEditor(false);
      setTimeout(() => setSkillsStatusMsg(null), 5000);
    } catch (err: any) {
      setError(err.message || 'Failed to save skills.md');
    } finally {
      setIsScraping(false);
    }
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

  const visibleJobs = scrapedJobs;

  return (
    <div className="space-y-6">
      {/* Hero Banner */}
      <div className="relative overflow-hidden rounded-2xl border border-emerald-500/30 bg-gradient-to-r from-slate-900 via-slate-900 to-teal-950/70 p-6 shadow-xl">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5">
          <div className="space-y-2 max-w-3xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs font-semibold">
              <Building2 className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Georgia Local &amp; Global B2B Matching • AI Salary Estimator • EN / KA ქართული</span>
            </div>
            <h1 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight">
              Automated Job Discovery, Eligibility Filtering &amp; Bilingual CV Generation
            </h1>
            <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
              Scans <strong>Jobs.ge, HR.ge, HeadHunter.ge, Remotive, Himalayas, RemoteOK, and Djinni</strong>, highlights Georgia-eligible local and B2B remote roles, estimates missing salary bands, and prepares tailored Word/PDF CVs for high-match vacancies.
            </p>
          </div>

          {/* Prominent Bilingual CV Language Switcher */}
          <div className="bg-slate-950/90 border border-slate-800 p-3.5 rounded-2xl flex flex-col gap-2 min-w-[260px]">
            <div className="flex items-center justify-between text-xs font-bold text-slate-300">
              <span className="flex items-center gap-1.5">
                <Languages className="w-4 h-4 text-emerald-400" />
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
                    ? 'bg-emerald-700 text-white border-emerald-400 shadow-md shadow-emerald-600/25'
                    : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                }`}
              >
                <span>🇬🇧 English CV</span>
              </button>
              <button
                onClick={() => setCvLanguage('ka')}
                className={`py-2 px-3 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 border transition-all ${
                  cvLanguage === 'ka'
                    ? 'bg-emerald-700 text-white border-emerald-400 shadow-md shadow-emerald-600/25'
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
                  Candidate Profile &amp; Skills Source: <code className="text-emerald-300">{skillsFilename}</code>
                </h3>
                <span className="text-[11px] px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800 font-semibold">
                  {extractedSkillsCount} Skills Indexed
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Upload your <code className="text-slate-300">skills.md</code> — Gemini automatically detects your profession, academic background, certifications, and matching internships &amp; live roles.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.md,.txt,.markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={handleFileUpload}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white text-xs font-semibold transition-colors shadow-sm"
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Upload CV (.pdf / .docx / .md)</span>
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

        {/* Dynamic Role & Industry Profile Gate Badges (auto-detected from skills.md) */}
        <div className="flex items-center gap-2 flex-wrap pt-2 border-t border-slate-800/60">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Active Profile Gate:</span>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-emerald-950 text-emerald-300 border border-emerald-800 font-semibold flex items-center gap-1">
            <span>👤 {candidateProfile?.full_name || 'Candidate'}</span>
          </span>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-indigo-950 text-indigo-300 border border-indigo-800 font-semibold flex items-center gap-1">
            <span>Industry: {candidateProfile?.detected_industry || candidateProfile?.target_industry || 'Auto-Detect on Upload'}</span>
          </span>
          <span className="text-xs px-2.5 py-1 rounded-lg bg-emerald-950 text-emerald-300 border border-emerald-800 font-semibold flex items-center gap-1">
            <span>
              Experience:{' '}
              {candidateProfile?.experience_years != null
                ? `${candidateProfile.experience_years} Years`
                : 'Not specified'}{' '}
              (Cap {(candidateProfile?.max_allowed_years ?? 2.0).toFixed(1)})
            </span>
          </span>
          {candidateProfile?.eligible_internships && (
            <span className="text-xs px-2.5 py-1 rounded-lg bg-cyan-950 text-cyan-300 border border-cyan-800 font-semibold">
              🎓 Internship &amp; Graduate Tracks Active
            </span>
          )}
          {candidateProfile?.headline && (
            <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">
              {candidateProfile.headline}
            </span>
          )}
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
              className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3.5 text-xs text-slate-200 font-mono leading-relaxed focus:outline-none focus:border-emerald-500"
            />
            <div className="flex justify-end">
              <button
                onClick={handleSaveSkillsMdText}
                className="px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white text-xs font-semibold"
              >
                Save &amp; Sync Profile
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 2. Universal Multi-Tier Optimal Opportunity Feed */}
      <DiscoveryFeed
        candidateProfile={candidateProfile}
        visibleJobs={visibleJobs}
        profileUploaded={profileUploaded}
        isScraping={isScraping}
        isLoadingJobs={isLoadingJobs}
        jobsError={jobsError}
        onRetryJobs={() => void loadPagedJobs()}
        selectedPortalFilter={filters.portal || 'ALL'}
        onSelectPortalFilter={(p) => applyFilters({ portal: p })}
        dbStatusFilter={filters.status || 'ALL'}
        onSelectStatusFilter={(s) => applyFilters({ status: s })}
        tierTab={(filters.tier as 'ALL' | 'DIRECT' | 'ADJACENT' | 'PUBLIC_INTERNSHIP') || 'ALL'}
        onSelectTierTab={(t) => applyFilters({ tier: t })}
        searchQuery={filters.search || ''}
        onSearchQueryChange={(q) => applyFilters({ search: q }, 300)}
        remoteTypeFilter={filters.remote_type || 'ALL'}
        onRemoteTypeFilterChange={(rt) => applyFilters({ remote_type: rt })}
        onlySavedFilter={Boolean(filters.only_saved)}
        onOnlySavedFilterChange={(savedOnly) => applyFilters({ only_saved: savedOnly })}
        b2bOnlyFilter={Boolean(filters.b2b_only)}
        onB2bOnlyFilterChange={(b2b) => applyFilters({ b2b_only: b2b })}
        geoEligibleOnlyFilter={Boolean(filters.geo_eligible_only)}
        onGeoEligibleOnlyFilterChange={(geo) => applyFilters({ geo_eligible_only: geo })}
        advancedFilters={filters}
        onAdvancedFiltersChange={(patch) => {
          const isTextPatch = 'country' in patch || 'city' in patch || 'technology' in patch || 'salary_min' in patch;
          applyFilters(patch, isTextPatch ? 300 : 0);
        }}
        onResetFilters={() => applyFilters({ ...DEFAULT_JOB_FILTERS })}
        savedJobIds={savedJobIds}
        onToggleSaveJob={handleToggleSaveJob}
        savedSearches={savedSearches}
        onSaveSearchAlert={async () => {
          const f = filtersRef.current;
          const parts = [
            f.portal && f.portal !== 'ALL' ? f.portal : null,
            f.search?.trim() || null,
            f.country?.trim() || null,
            f.city?.trim() || null,
            f.technology?.trim() || null,
            f.remote_type && f.remote_type !== 'ALL' ? f.remote_type : null,
            f.b2b_only ? 'B2B' : null,
            f.geo_eligible_only ? 'GE-Eligible' : null,
          ].filter(Boolean);
          const name = parts.length > 0 ? parts.join(' • ') : 'All High-Match Roles';
          try {
            const created = await createSavedSearch(name, {
              portal: f.portal || 'ALL',
              status: f.status || 'ALL',
              tier: f.tier || 'ALL',
              search: f.search?.trim() || '',
              country: f.country?.trim() || '',
              city: f.city?.trim() || '',
              technology: f.technology?.trim() || '',
              language: f.language || 'ALL',
              experience_level: f.experience_level || 'ALL',
              employment_type: f.employment_type || 'ALL',
              salary_min: f.salary_min || undefined,
              sort_by: f.sort_by || 'relevance',
              remote_type: f.remote_type || 'ALL',
              only_new: Boolean(f.only_new),
              only_saved: Boolean(f.only_saved),
              b2b_only: Boolean(f.b2b_only),
              geo_eligible_only: Boolean(f.geo_eligible_only),
            });
            setSavedSearches((prev) => [created, ...prev]);
          } catch (err: any) {
            setError(err?.message || 'Could not save search alert');
          }
        }}
        onApplySavedSearch={(ss) => {
          const f = ss.filters || {};
          applyFilters({
            ...DEFAULT_JOB_FILTERS,
            portal: f.portal || 'ALL',
            status: f.status || 'ALL',
            tier: f.tier || 'ALL',
            search: f.search || '',
            country: f.country || '',
            city: f.city || '',
            technology: f.technology || '',
            language: f.language || 'ALL',
            experience_level: f.experience_level || 'ALL',
            employment_type: f.employment_type || 'ALL',
            salary_min: f.salary_min ? Number(f.salary_min) : undefined,
            sort_by: f.sort_by || 'relevance',
            remote_type: f.remote_type || 'ALL',
            only_new: Boolean(f.only_new),
            only_saved: Boolean(f.only_saved),
            b2b_only: Boolean(f.b2b_only),
            geo_eligible_only: Boolean(f.geo_eligible_only),
            page: 1,
          });
        }}
        onDeleteSavedSearch={async (searchId) => {
          await deleteSavedSearch(searchId).catch(() => {});
          setSavedSearches((prev) => prev.filter((s) => s.id !== searchId));
        }}
        notifications={notifications}
        onMarkNotificationRead={async (notifId) => {
          await markNotificationRead(notifId).catch(() => {});
          setNotifications((prev) => prev.map((n) => (n.id === notifId ? { ...n, is_read: true } : n)));
        }}
        tierCounts={tierCounts}
        statusCounts={statusCounts}
        page={page}
        totalPages={totalPages}
        totalJobs={totalJobs}
        onPageChange={(nextP) => applyFilters({ page: nextP })}
        scrapeStats={scrapeStats}
        scrapeTaskInfo={scrapeTaskInfo}
        preparedEmailPkg={preparedEmailPkg}
        onDismissEmailPkg={() => setPreparedEmailPkg(null)}
        draftingJobId={draftingJobId}
        onRunScrapers={handleRunMultiPortalScrapers}
        onUploadClick={() => fileInputRef.current?.click()}
        onSelectJob={handleSelectScrapedDbJob}
        onOpenFillForm={(job) => {
          handleSelectScrapedDbJob(job);
          setIsStageModalOpen(true);
        }}
        onDraftInGmail={handleDraftInGmail}
      />

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
                    className="text-xs text-emerald-400 hover:underline flex items-center gap-1"
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
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
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
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-300 focus:outline-none focus:border-emerald-500 leading-relaxed"
              />
            </div>

            {/* Dual Action Buttons for English or Georgian CV Generation */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
              <button
                onClick={() => handleRunAudit('en')}
                disabled={isAuditing}
                className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs text-white bg-gradient-to-r from-emerald-700 to-teal-700 hover:from-emerald-400 hover:to-teal-500 shadow-lg shadow-emerald-600/20 transition-all disabled:opacity-50"
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
                className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs text-white bg-gradient-to-r from-emerald-700 to-teal-700 hover:from-emerald-700 hover:to-teal-500 shadow-lg shadow-emerald-600/20 transition-all disabled:opacity-50"
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
              className="w-full flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-xs text-teal-200 bg-teal-950/60 hover:bg-teal-900/70 border border-teal-700/60 transition-all"
            >
              <Play className="w-4 h-4 fill-current" aria-hidden="true" />
              <span>Launch Form Auto-Fill Stager (Fills Application &amp; Attaches Tailored CV)</span>
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
                    <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
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
                  <span className="text-lg font-bold text-emerald-400">{auditResult.score_breakdown.skills_match}%</span>
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
              <div className="p-4 bg-emerald-950/25 border border-emerald-800/60 rounded-xl space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-400 block">
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
                      className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white text-xs font-semibold shadow-sm transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Download PDF CV</span>
                    </a>
                    {auditResult.tailored_cv.html_preview_url && (
                      <a
                        href={`${BACKEND_ORIGIN}${auditResult.tailored_cv.html_preview_url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-700 text-white text-xs font-semibold shadow-sm transition-colors"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        <span>Printable View</span>
                      </a>
                    )}
                  </div>
                </div>

                <div className="text-xs text-slate-300 bg-slate-950/80 p-3 rounded-lg border border-slate-800 space-y-1.5">
                  <div>
                    <strong className="text-emerald-300">
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
                  <BookmarkPlus className="w-4 h-4 text-emerald-400" />
                  <span>Save to SQL Tracker</span>
                </button>

                <button
                  onClick={() => setIsStageModalOpen(true)}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2.5 px-3 rounded-xl bg-gradient-to-r from-emerald-700 to-teal-700 hover:from-emerald-400 hover:to-teal-500 text-xs font-semibold text-white shadow-md shadow-emerald-600/20 transition-all"
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
              <div className="w-12 h-12 rounded-2xl bg-slate-800/80 flex items-center justify-center text-emerald-400">
                <Search className="w-6 h-6" />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-200">
                  Ready to Audit & Generate Your English or Georgian (ქართული) PDF CV
                </h4>
                <p className="text-xs text-slate-300 max-w-md mt-1">
                  Select any vacancy from the <strong>Opportunity Feed</strong> above or paste a job description on the left, then click <strong>Generate English CV</strong> or <strong>Generate ქართული CV</strong>.
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
                <FileText className="w-4 h-4 text-emerald-400" aria-hidden="true" />
                Grounded Screening Answers ({cvLanguage === 'ka' ? 'ქართულ ენაზე' : 'English'})
              </h3>
              <p className="text-xs text-slate-300">
                Answers are tailored directly from your verified profile and the role requirements.
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
                  <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
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
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                      {cvLanguage === 'ka' ? 'ქართული' : 'Natural Tone'}
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
