import React, { useState } from 'react';
import {
  Database,
  RefreshCw,
  Mail,
  Download,
  ExternalLink,
  Upload,
  Compass,
  Sparkles,
  Landmark,
  Target,
  Search,
  Star,
  Globe,
  X,
  Bell,
  Bookmark,
  Trash2,
  SlidersHorizontal,
  AlertTriangle,
} from 'lucide-react';
import { DbJobPosting, JobSearchParams, SavedSearchItem, NotificationItem } from '../types';
import { BACKEND_ORIGIN } from '../services/api';

export interface CandidateRoleHeaderInfo {
  full_name?: string;
  headline?: string;
  primary_role?: string;
  detected_industry?: string;
  adjacent_roles?: string[];
  education?: Array<{ degree?: string; field_of_study?: string; institution?: string }>;
  courses_and_certifications?: string[];
  experience_years?: number;
  target_seniority_label?: string;
  target_industry?: string;
}

export interface PreparedEmailPkg {
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
}

interface DiscoveryFeedProps {
  candidateProfile: CandidateRoleHeaderInfo | null;
  visibleJobs: DbJobPosting[];
  profileUploaded: boolean;
  isScraping: boolean;
  selectedPortalFilter: string;
  onSelectPortalFilter: (portal: string) => void;
  dbStatusFilter: string;
  onSelectStatusFilter: (status: string) => void;
  tierTab?: 'ALL' | 'DIRECT' | 'ADJACENT' | 'PUBLIC_INTERNSHIP';
  onSelectTierTab?: (tier: 'ALL' | 'DIRECT' | 'ADJACENT' | 'PUBLIC_INTERNSHIP') => void;
  tierCounts?: {
    ALL: number;
    DIRECT: number;
    ADJACENT: number;
    PUBLIC_INTERNSHIP: number;
  };
  statusCounts?: {
    ALL: number;
    STAGED: number;
    AUDITED: number;
  };
  page?: number;
  totalPages?: number;
  totalJobs?: number;
  onPageChange?: (page: number) => void;
  scrapeStats: { total: number; staged: number; filteredOut: number } | null;
  scrapeTaskInfo?: { status: string; progressPct: number; errorMessage?: string | null } | null;
  preparedEmailPkg: PreparedEmailPkg | null;
  onDismissEmailPkg: () => void;
  draftingJobId: number | null;
  onRunScrapers: () => void;
  onUploadClick: () => void;
  onSelectJob: (job: DbJobPosting) => void;
  onDraftInGmail: (job: DbJobPosting) => void;
  searchQuery?: string;
  onSearchQueryChange?: (q: string) => void;
  remoteTypeFilter?: string;
  onRemoteTypeFilterChange?: (mode: string) => void;
  onlySavedFilter?: boolean;
  onOnlySavedFilterChange?: (val: boolean) => void;
  b2bOnlyFilter?: boolean;
  onB2bOnlyFilterChange?: (val: boolean) => void;
  geoEligibleOnlyFilter?: boolean;
  onGeoEligibleOnlyFilterChange?: (val: boolean) => void;
  savedJobIds?: Set<number>;
  onToggleSaveJob?: (job: DbJobPosting) => void;
  savedSearches?: SavedSearchItem[];
  onSaveSearchAlert?: () => void;
  onApplySavedSearch?: (item: SavedSearchItem) => void;
  onDeleteSavedSearch?: (searchId: number) => void;
  notifications?: NotificationItem[];
  onMarkNotificationRead?: (notifId: number) => void;
  advancedFilters?: Partial<JobSearchParams>;
  onAdvancedFiltersChange?: (patch: Partial<JobSearchParams>) => void;
  onResetFilters?: () => void;
  isLoadingJobs?: boolean;
  jobsError?: string | null;
  onRetryJobs?: () => void;
}

function formatSalaryDisplay(job: DbJobPosting): string | null {
  const hasMin = job.salary_min != null && job.salary_min > 0;
  const hasMax = job.salary_max != null && job.salary_max > 0;
  if (!hasMin && !hasMax) return null;
  const curRaw = (job.salary_currency || 'USD').trim();
  const curUpper = curRaw.toUpperCase();
  const isGel =
    curUpper === 'GEL' ||
    curRaw === '₾' ||
    curRaw.toLowerCase() === 'ლარი' ||
    curRaw === 'ᲚᲐᲠᲘ';
  const sym = isGel ? '₾' : curUpper === 'EUR' ? '€' : curUpper === 'GBP' ? '£' : '$';
  const labelCur = isGel ? 'GEL' : curUpper;
  if (hasMin && hasMax) {
    if (job.salary_min === job.salary_max) {
      return `${job.salary_max!.toLocaleString()} ${sym} (${labelCur})`;
    }
    return `${job.salary_min!.toLocaleString()}–${job.salary_max!.toLocaleString()} ${sym} (${labelCur})`;
  }
  if (hasMin) {
    return `From ${job.salary_min!.toLocaleString()} ${sym} (${labelCur})`;
  }
  return `Up to ${job.salary_max!.toLocaleString()} ${sym} (${labelCur})`;
}

function formatPostedBadge(job: DbJobPosting): { label: string; isFresh: boolean } | null {
  const rawDate = job.published_at || job.posting_date || job.scraped_at;
  if (!rawDate) return null;
  const parsed = new Date(rawDate);
  const valid = !Number.isNaN(parsed.getTime());
  const ageDays = valid ? Math.floor((Date.now() - parsed.getTime()) / 86400000) : 99;
  const label = valid
    ? ageDays <= 0
      ? 'Today'
      : ageDays === 1
      ? 'Yesterday'
      : parsed.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : String(rawDate);
  return { label, isFresh: ageDays <= 2 };
}

export const DiscoveryFeed: React.FC<DiscoveryFeedProps> = ({
  candidateProfile,
  visibleJobs,
  profileUploaded,
  isScraping,
  selectedPortalFilter,
  onSelectPortalFilter,
  dbStatusFilter,
  onSelectStatusFilter,
  tierTab: controlledTierTab,
  onSelectTierTab,
  tierCounts,
  statusCounts,
  page = 1,
  totalPages = 1,
  totalJobs,
  onPageChange,
  scrapeStats,
  scrapeTaskInfo,
  preparedEmailPkg,
  onDismissEmailPkg,
  draftingJobId,
  onRunScrapers,
  onUploadClick,
  onSelectJob,
  onDraftInGmail,
  searchQuery = '',
  onSearchQueryChange,
  remoteTypeFilter = 'ALL',
  onRemoteTypeFilterChange,
  onlySavedFilter = false,
  onOnlySavedFilterChange,
  b2bOnlyFilter = false,
  onB2bOnlyFilterChange,
  geoEligibleOnlyFilter = false,
  onGeoEligibleOnlyFilterChange,
  savedJobIds,
  onToggleSaveJob,
  savedSearches = [],
  onSaveSearchAlert,
  onApplySavedSearch,
  onDeleteSavedSearch,
  notifications = [],
  onMarkNotificationRead,
  advancedFilters,
  onAdvancedFiltersChange,
  onResetFilters,
  isLoadingJobs = false,
  jobsError = null,
  onRetryJobs,
}) => {
  const [localTierTab, setLocalTierTab] = useState<'ALL' | 'DIRECT' | 'ADJACENT' | 'PUBLIC_INTERNSHIP'>('ALL');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const activeAdvancedCount = [
    advancedFilters?.country,
    advancedFilters?.city,
    advancedFilters?.technology,
    advancedFilters?.language && advancedFilters.language !== 'ALL' ? advancedFilters.language : '',
    advancedFilters?.experience_level && advancedFilters.experience_level !== 'ALL' ? advancedFilters.experience_level : '',
    advancedFilters?.employment_type && advancedFilters.employment_type !== 'ALL' ? advancedFilters.employment_type : '',
    advancedFilters?.salary_min && advancedFilters.salary_min > 0 ? String(advancedFilters.salary_min) : '',
    advancedFilters?.only_new ? 'new' : '',
  ].filter(Boolean).length;
  const tierTab = controlledTierTab ?? localTierTab;
  const handleTierClick = (t: 'ALL' | 'DIRECT' | 'ADJACENT' | 'PUBLIC_INTERNSHIP') => {
    if (onSelectTierTab) onSelectTierTab(t);
    else setLocalTierTab(t);
  };

  const directJobs = visibleJobs.filter((j) => (j.match_tier || 'DIRECT') === 'DIRECT');
  const adjacentJobs = visibleJobs.filter((j) => j.match_tier === 'ADJACENT');
  const publicJobs = visibleJobs.filter(
    (j) => j.match_tier === 'PUBLIC_INTERNSHIP' || j.portal === 'hr.gov.ge'
  );

  const filteredDbJobs = onSelectTierTab ? visibleJobs : visibleJobs.filter((j) => {
    const tier = j.match_tier || (j.portal === 'hr.gov.ge' ? 'PUBLIC_INTERNSHIP' : 'DIRECT');
    const matchesTier = tierTab === 'ALL' || tier === tierTab;
    const matchStatus = dbStatusFilter === 'ALL' || j.status === dbStatusFilter;
    const matchPortal = selectedPortalFilter === 'ALL' || j.portal === selectedPortalFilter;
    return matchesTier && matchStatus && matchPortal;
  });

  const expVal = candidateProfile?.experience_years ?? null;
  const levelLabel =
    candidateProfile?.target_seniority_label ||
    (expVal == null || expVal <= 0.5
      ? 'Entry-Level / Intern'
      : expVal <= 2.5
      ? `Junior (${expVal} yrs)`
      : expVal <= 5
      ? `Mid-Level (${expVal} yrs)`
      : `Senior (${expVal} yrs)`);
  const primaryRole = candidateProfile?.primary_role || candidateProfile?.headline || 'Upload skills.md';
  const detectedIndustry = candidateProfile?.detected_industry || candidateProfile?.target_industry || 'Domain-Agnostic';
  const adjacentRoles = candidateProfile?.adjacent_roles || [];
  const eduList = candidateProfile?.education || [];

  const portals = [
    'ALL',
    'jobs.ge',
    'hr.ge',
    'headhunter.ge',
    'hr.gov.ge',
    'remotive.com',
    'himalayas.app',
    'remoteok.com',
    'linkedin.com',
    'djinni.co',
    'dou.ua',
    'justjoin.it',
    'greenhouse.io',
    'lever.co',
  ];

  return (
    <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-4">
      {/* Dynamic Domain-Agnostic Role Header */}
      {profileUploaded && (
        <div className="p-3.5 rounded-xl bg-slate-950/90 border border-emerald-500/30 flex flex-col lg:flex-row lg:items-center justify-between gap-2.5">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-1 font-bold text-emerald-300">
                <Compass className="w-3.5 h-3.5" />
                Candidate:
              </span>
              <span className="font-bold text-white">{primaryRole}</span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-400">
                Industry: <strong className="text-emerald-300">{detectedIndustry}</strong>
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-400">
                Target level: <strong className="text-amber-300">{levelLabel}</strong>
              </span>
            </div>
            {adjacentRoles.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
                <span className="font-semibold text-indigo-300">Optimal Adjacent Paths:</span>
                {adjacentRoles.slice(0, 4).map((r) => (
                  <span
                    key={r}
                    className="px-2 py-0.5 rounded-md bg-indigo-950/60 border border-indigo-700/50 text-indigo-200"
                  >
                    {r}
                  </span>
                ))}
              </div>
            )}
            {eduList.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
                <span className="font-semibold text-cyan-300">Education &amp; Internships:</span>
                {eduList.slice(0, 2).map((e, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded-md bg-cyan-950/60 border border-cyan-800/50 text-cyan-200"
                  >
                    {e.degree || e.field_of_study}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Header + Scan CTA */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Database className="w-4 h-4 text-emerald-400" />
            Universal Multi-Tier Optimal Opportunity Feed
          </h3>
          <p className="text-xs text-slate-300">
            Adapts dynamically to your <code>skills.md</code> across Georgian portals (<strong>Jobs.ge</strong>, <strong>HR.ge</strong>, <strong>HeadHunter.ge</strong>, <strong>HR.gov.ge</strong>) and global Remote B2B boards (<strong>Remotive</strong>, <strong>Himalayas</strong>, <strong>RemoteOK</strong>, <strong>Djinni</strong>, <strong>JustJoin</strong>).
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onUploadClick}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-emerald-700/20 hover:bg-emerald-700/30 border border-emerald-500/40 text-emerald-300 text-xs font-bold transition-all"
            title="Upload or replace your CV (.pdf, .docx, .md, .txt)"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>{profileUploaded ? 'Update CV / skills.md' : 'Upload CV / skills.md'}</span>
          </button>

          <button
            type="button"
            onClick={onRunScrapers}
            disabled={isScraping}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-700 to-teal-700 hover:from-emerald-700 hover:to-teal-500 text-white text-xs font-bold shadow-md shadow-emerald-600/20 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isScraping ? 'animate-spin' : ''}`} />
            <span>{isScraping ? 'Scanning Live Portals...' : 'Run Live Role Scrapers'}</span>
          </button>

          {['ALL', 'STAGED', 'AUDITED'].map((st) => (
            <button
              key={st}
              onClick={() => onSelectStatusFilter(st)}
              className={`text-[11px] px-2.5 py-1.5 rounded-lg font-semibold transition-colors ${
                dbStatusFilter === st
                  ? 'bg-emerald-700 text-white'
                  : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
              }`}
            >
              {st === 'ALL'
                ? `All Suitable (${statusCounts?.ALL ?? totalJobs ?? visibleJobs.length})`
                : st === 'STAGED'
                ? `Ready >=75% (${statusCounts?.STAGED ?? visibleJobs.filter(j => j.status === 'STAGED').length})`
                : `Match 60-74% (${statusCounts?.AUDITED ?? visibleJobs.filter(j => j.status === 'AUDITED').length})`}
            </button>
          ))}
        </div>
      </div>

      {/* Multi-Tier Tabs (Direct Matches / Adjacent Roles / Public Sector & Internships) */}
      <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-800/60">
        {([
          { id: 'ALL' as const, label: `All Tiers (${tierCounts?.ALL ?? totalJobs ?? visibleJobs.length})`, active: 'bg-slate-800 text-white border border-slate-600' },
          { id: 'DIRECT' as const, label: `🎯 Direct Matches (${tierCounts?.DIRECT ?? directJobs.length})`, active: 'bg-emerald-700 text-white shadow-sm shadow-emerald-600/20', Icon: Target },
          { id: 'ADJACENT' as const, label: `🚀 Optimal Adjacent Roles (${tierCounts?.ADJACENT ?? adjacentJobs.length})`, active: 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/20', Icon: Sparkles },
          { id: 'PUBLIC_INTERNSHIP' as const, label: `🏛️ Public Sector (${tierCounts?.PUBLIC_INTERNSHIP ?? publicJobs.length})`, active: 'bg-cyan-700 text-white shadow-sm shadow-cyan-600/20', Icon: Landmark },
        ]).map(({ id, label, active, Icon }) => (
          <button
            key={id}
            onClick={() => handleTierClick(id)}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl font-bold transition-all ${
              tierTab === id ? active : 'bg-slate-950 text-slate-300 hover:text-white border border-slate-800'
            }`}
          >
            {Icon && <Icon className="w-3.5 h-3.5" />}
            <span>{label}</span>
          </button>
        ))}
      </div>

      {/* Portal Filter Chips + Search & Work Mode Bar */}
      <div className="space-y-2.5 pt-2 border-t border-slate-800/60">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5">
          {/* Live Keyword Search Input */}
          {onSearchQueryChange && (
            <div className="relative flex-1 max-w-md">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden="true" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => onSearchQueryChange(e.target.value)}
                aria-label="Search vacancies by role, company, or skill"
                placeholder="Search by role, company, or skills (e.g. Analyst, Python, IFRS, Remote)..."
                className="w-full pl-8 pr-8 py-1.5 rounded-xl bg-slate-950 border border-slate-700 focus:border-emerald-400 focus:outline-none text-xs text-white placeholder-slate-400"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => onSearchQueryChange('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                  aria-label="Clear search"
                  title="Clear search"
                >
                  <X className="w-3.5 h-3.5" aria-hidden="true" />
                </button>
              )}
            </div>
          )}

          {/* Work Mode, Georgia/B2B Eligibility & Saved Jobs Filter Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            {onRemoteTypeFilterChange && (
              <>
                <span className="text-[10px] font-bold uppercase text-slate-300 mr-1 inline-flex items-center gap-1">
                  <Globe className="w-3 h-3" aria-hidden="true" /> Mode:
                </span>
                {[
                  { id: 'ALL', label: 'All Modes' },
                  { id: 'REMOTE', label: 'Remote' },
                  { id: 'HYBRID', label: 'Hybrid' },
                  { id: 'ONSITE', label: 'On-Site' },
                ].map((mode) => (
                  <button
                    key={mode.id}
                    type="button"
                    aria-pressed={remoteTypeFilter === mode.id}
                    onClick={() => onRemoteTypeFilterChange(mode.id)}
                    className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition-colors ${
                      remoteTypeFilter === mode.id
                        ? 'bg-emerald-700 text-white'
                        : 'bg-slate-950 text-slate-300 hover:text-white border border-slate-800'
                    }`}
                  >
                    {mode.label}
                  </button>
                ))}
              </>
            )}

            {onB2bOnlyFilterChange && (
              <button
                type="button"
                aria-pressed={b2bOnlyFilter}
                onClick={() => onB2bOnlyFilterChange(!b2bOnlyFilter)}
                className={`inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg font-semibold transition-colors ${
                  b2bOnlyFilter
                    ? 'bg-teal-600/30 border border-teal-400/70 text-teal-200'
                    : 'bg-slate-950 text-slate-300 hover:text-teal-200 border border-slate-800'
                }`}
              >
                <span>B2B Remote Contracts</span>
              </button>
            )}

            {onGeoEligibleOnlyFilterChange && (
              <button
                type="button"
                aria-pressed={geoEligibleOnlyFilter}
                onClick={() => onGeoEligibleOnlyFilterChange(!geoEligibleOnlyFilter)}
                className={`inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg font-semibold transition-colors ${
                  geoEligibleOnlyFilter
                    ? 'bg-emerald-700/30 border border-emerald-400/70 text-emerald-200'
                    : 'bg-slate-950 text-slate-300 hover:text-emerald-200 border border-slate-800'
                }`}
              >
                <span>Georgia Eligible</span>
              </button>
            )}

            {onOnlySavedFilterChange && (
              <button
                type="button"
                aria-pressed={onlySavedFilter}
                onClick={() => onOnlySavedFilterChange(!onlySavedFilter)}
                className={`inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg font-semibold transition-colors ${
                  onlySavedFilter
                    ? 'bg-amber-500/20 border border-amber-400/70 text-amber-200'
                    : 'bg-slate-950 text-slate-300 hover:text-amber-200 border border-slate-800'
                }`}
              >
                <Star className={`w-3 h-3 ${onlySavedFilter ? 'fill-amber-400 text-amber-400' : ''}`} aria-hidden="true" />
                <span>Saved ({savedJobIds ? savedJobIds.size : 0})</span>
              </button>
            )}

            {onSaveSearchAlert && (
              <button
                type="button"
                onClick={onSaveSearchAlert}
                className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg font-semibold bg-slate-950 text-emerald-300 hover:text-white border border-emerald-700/60 transition-colors"
                title="Save current filter & keywords as a vacancy alert"
              >
                <Bookmark className="w-3 h-3" aria-hidden="true" />
                <span>Save Alert Filter</span>
              </button>
            )}

            {onAdvancedFiltersChange && (
              <>
                <select
                  aria-label="Filter by posted date"
                  value={advancedFilters?.posted_within_days ? String(advancedFilters.posted_within_days) : ''}
                  onChange={(e) =>
                    onAdvancedFiltersChange({
                      posted_within_days: e.target.value ? Number(e.target.value) : undefined,
                    })
                  }
                  className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-950 text-slate-200 border border-slate-700 focus:border-emerald-400 focus:outline-none"
                >
                  <option value="">Date: Any</option>
                  <option value="1">Last 24h</option>
                  <option value="3">Last 3 Days</option>
                  <option value="7">Last 7 Days</option>
                  <option value="30">Last 30 Days</option>
                </select>
                <select
                  aria-label="Sort vacancies"
                  value={advancedFilters?.sort_by || 'newest'}
                  onChange={(e) => onAdvancedFiltersChange({ sort_by: e.target.value })}
                  className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-950 text-slate-200 border border-slate-700 focus:border-emerald-400 focus:outline-none"
                >
                  <option value="newest">Sort: Newest Posted</option>
                  <option value="relevance">Sort: Best Match</option>
                  <option value="salary_desc">Sort: Highest Salary</option>
                  <option value="company_asc">Sort: Company A–Z</option>
                </select>
                <button
                  type="button"
                  aria-expanded={showAdvancedFilters}
                  onClick={() => setShowAdvancedFilters((v) => !v)}
                  className={`inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg font-semibold border transition-colors ${
                    showAdvancedFilters || activeAdvancedCount > 0
                      ? 'bg-indigo-950/60 border-indigo-500/70 text-indigo-200'
                      : 'bg-slate-950 text-slate-300 hover:text-white border-slate-800'
                  }`}
                >
                  <SlidersHorizontal className="w-3 h-3" aria-hidden="true" />
                  <span>Filters{activeAdvancedCount > 0 ? ` (${activeAdvancedCount})` : ''}</span>
                </button>
              </>
            )}
          </div>
        </div>

        {onAdvancedFiltersChange && showAdvancedFilters && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 p-3 rounded-xl bg-slate-950/85 border border-slate-800 text-xs">
            {([
              { key: 'country' as const, label: 'Filter by country', placeholder: 'Country (e.g. Georgia, Germany)' },
              { key: 'city' as const, label: 'Filter by city', placeholder: 'City (e.g. Tbilisi, Berlin)' },
              { key: 'technology' as const, label: 'Filter by skill or technology', placeholder: 'Skills / Tools (e.g. SQL, Excel, Python)' },
            ]).map((f) => (
              <input
                key={f.key}
                type="text"
                aria-label={f.label}
                value={advancedFilters?.[f.key] || ''}
                onChange={(e) => onAdvancedFiltersChange({ [f.key]: e.target.value })}
                placeholder={f.placeholder}
                className="px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 placeholder-slate-400 focus:outline-none focus:border-emerald-400"
              />
            ))}
            <input
              type="number"
              min={0}
              step={200}
              aria-label="Minimum monthly salary"
              value={advancedFilters?.salary_min || ''}
              onChange={(e) => onAdvancedFiltersChange({ salary_min: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="Min Salary (e.g. 2000)"
              className="px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 placeholder-slate-400 focus:outline-none focus:border-emerald-400"
            />
            {([
              { key: 'language' as const, label: 'Filter by language', options: [['ALL', 'Any Language'], ['English', 'English'], ['Georgian', 'Georgian / ქართული'], ['German', 'German']] },
              { key: 'experience_level' as const, label: 'Filter by experience level', options: [['ALL', 'Any Experience Level'], ['intern', 'Intern / Trainee'], ['junior', 'Junior / Entry'], ['mid', 'Mid-Level'], ['senior', 'Senior / Lead']] },
              { key: 'employment_type' as const, label: 'Filter by employment type', options: [['ALL', 'Any Employment Type'], ['full_time', 'Full-Time'], ['part_time', 'Part-Time'], ['contract', 'Contract / B2B'], ['internship', 'Internship']] },
            ]).map((s) => (
              <select
                key={s.key}
                aria-label={s.label}
                value={advancedFilters?.[s.key] || 'ALL'}
                onChange={(e) => onAdvancedFiltersChange({ [s.key]: e.target.value === 'ALL' ? undefined : e.target.value })}
                className="px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 focus:outline-none focus:border-emerald-400"
              >
                {s.options.map(([v, txt]) => <option key={v} value={v}>{txt}</option>)}
              </select>
            ))}
            <div className="flex items-center justify-between gap-2">
              <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(advancedFilters?.only_new)}
                  onChange={(e) => onAdvancedFiltersChange({ only_new: e.target.checked })}
                  className="rounded border-slate-600 bg-slate-900 text-emerald-500"
                />
                <span>Only Unapplied</span>
              </label>
              {onResetFilters && (
                <button type="button" onClick={onResetFilters} className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-semibold">
                  Clear All
                </button>
              )}
            </div>
          </div>
        )}

        {(savedSearches.length > 0 || notifications.some((n) => !n.is_read)) && (
          <div className="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded-xl bg-slate-950/80 border border-slate-800 text-[11px]">
            <div className="flex flex-wrap items-center gap-1.5">
              {savedSearches.length > 0 && (
                <span className="font-bold uppercase text-[10px] text-slate-300 mr-1">Saved Alerts:</span>
              )}
              {savedSearches.map((ss) => (
                <span
                  key={ss.id}
                  className="inline-flex items-center gap-1 bg-slate-900 border border-slate-700 rounded-lg pl-2 pr-1 py-0.5 text-slate-200"
                >
                  <button
                    type="button"
                    onClick={() => onApplySavedSearch?.(ss)}
                    className="hover:text-emerald-300 font-medium"
                  >
                    {ss.name}
                  </button>
                  {onDeleteSavedSearch && (
                    <button
                      type="button"
                      onClick={() => onDeleteSavedSearch(ss.id)}
                      aria-label={`Delete alert ${ss.name}`}
                      className="p-0.5 text-slate-400 hover:text-rose-400"
                    >
                      <Trash2 className="w-2.5 h-2.5" aria-hidden="true" />
                    </button>
                  )}
                </span>
              ))}
            </div>

            {notifications.filter((n) => !n.is_read).length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="inline-flex items-center gap-1 text-amber-300 font-semibold">
                  <Bell className="w-3 h-3" aria-hidden="true" />
                  <span>{notifications.filter((n) => !n.is_read).length} New Alerts:</span>
                </span>
                {notifications
                  .filter((n) => !n.is_read)
                  .slice(0, 2)
                  .map((n) => (
                    <button
                      key={n.id}
                      type="button"
                      onClick={() => onMarkNotificationRead?.(n.id)}
                      className="px-2 py-0.5 rounded bg-amber-950/60 border border-amber-700/50 text-amber-200 hover:bg-amber-900/60 truncate max-w-[220px]"
                      title="Click to dismiss notification"
                    >
                      {n.title}
                    </button>
                  ))}
              </div>
            )}
          </div>
        )}

        {/* Portal Filter Chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-bold uppercase text-slate-300 mr-1">Portals:</span>
          {portals.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={selectedPortalFilter === p}
              onClick={() => onSelectPortalFilter(p)}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition-colors ${
                selectedPortalFilter === p
                  ? 'bg-emerald-700 text-white'
                  : 'bg-slate-950 text-slate-300 hover:text-white border border-slate-800'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Prepared Gmail Package Banner */}
      {preparedEmailPkg && (
        <div className="p-4 rounded-xl border text-xs space-y-2.5 bg-emerald-950/35 border-emerald-700/60">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <span className="text-[10px] font-bold uppercase block text-emerald-400">
                {preparedEmailPkg.gmail_draft_saved
                  ? `Gmail Draft created with ${preparedEmailPkg.docx_filename} ALREADY attached — open Gmail Drafts and click Send!`
                  : `CV downloaded (${preparedEmailPkg.docx_filename}) — attach it in Gmail Compose (or configure Gmail App Password for auto-attachment)`}
              </span>
              <span className="text-white font-semibold">
                {preparedEmailPkg.title} ({preparedEmailPkg.company}) &mdash; Subject:{' '}
                <code className="text-emerald-300">{preparedEmailPkg.subject}</code>
              </span>
              {preparedEmailPkg.draft_error && !preparedEmailPkg.gmail_draft_saved && (
                <p className="text-[11px] text-amber-300 mt-1">{preparedEmailPkg.draft_error}</p>
              )}
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
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-700 hover:bg-rose-500 text-white font-semibold"
              >
                <Mail className="w-3.5 h-3.5" />
                <span>{preparedEmailPkg.gmail_draft_saved ? 'Open Gmail Drafts' : 'Open Gmail Compose'}</span>
              </a>
              <button
                type="button"
                onClick={onDismissEmailPkg}
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

      {/* Async Background Scan Status Bar */}
      {scrapeTaskInfo && ['PENDING', 'QUEUED', 'RUNNING', 'PROCESSING', 'FAILED'].includes(scrapeTaskInfo.status) && (
        <div
          className={`text-xs px-3.5 py-2.5 rounded-xl border space-y-1.5 ${
            scrapeTaskInfo.status === 'FAILED'
              ? 'bg-rose-950/40 border-rose-800 text-rose-300'
              : 'bg-emerald-950/40 border-emerald-800/70 text-emerald-200'
          }`}
        >
          <div className="flex items-center justify-between gap-2 font-semibold">
            <span>
              {scrapeTaskInfo.status === 'FAILED'
                ? `Scan Failed: ${scrapeTaskInfo.errorMessage || 'Check portal network status'}`
                : `Portal Scan (${scrapeTaskInfo.status}) — scoring remote & local matches...`}
            </span>
            <span className="font-mono">{scrapeTaskInfo.progressPct}%</span>
          </div>
          {scrapeTaskInfo.status !== 'FAILED' && (
            <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-sky-500 to-emerald-400 transition-all duration-300"
                style={{ width: `${Math.min(100, Math.max(8, scrapeTaskInfo.progressPct))}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Synchronized Feed Stats Banner */}
      {(Boolean(totalJobs) || visibleJobs.length > 0 || Boolean(scrapeStats)) && (
        <div className="text-xs bg-emerald-950/30 border border-emerald-800/60 text-emerald-300 px-3.5 py-2 rounded-xl flex items-center justify-between flex-wrap gap-2">
          <span>
            ✅ Found <strong>{totalJobs ?? visibleJobs.length}</strong> suitable opportunities ({tierCounts?.DIRECT ?? directJobs.length} Direct • {tierCounts?.ADJACENT ?? adjacentJobs.length} Adjacent • {tierCounts?.PUBLIC_INTERNSHIP ?? publicJobs.length} Public Sector)
            <span className="text-emerald-300 ml-1.5">(showing {visibleJobs.length} on page {page} of {totalPages})</span>
            {scrapeStats && scrapeStats.filteredOut > 0 && (
              <span className="text-slate-400 ml-1.5">
                ({Math.max(0, scrapeStats.filteredOut)} filtered out by location/seniority gates)
              </span>
            )}
          </span>
          <span className="text-emerald-400 font-bold">
            {statusCounts?.STAGED ?? visibleJobs.filter((j) => j.status === 'STAGED').length} ready to apply (&gt;= 75% match)
          </span>
        </div>
      )}

      {/* API Error Banner (never masquerade errors as zero results) */}
      {jobsError && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-rose-950/40 border border-rose-800/70 text-rose-200 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <strong className="block text-rose-100">Could not load vacancies</strong>
              <span>{jobsError}</span>
            </div>
          </div>
          {onRetryJobs && (
            <button
              type="button"
              onClick={onRetryJobs}
              className="px-3.5 py-1.5 rounded-lg bg-rose-800 hover:bg-rose-700 text-white font-semibold self-start sm:self-center"
            >
              Retry Search
            </button>
          )}
        </div>
      )}

      {/* Search Loading Indicator */}
      {isLoadingJobs && !jobsError && (
        <div className="text-xs text-emerald-300 bg-slate-950/70 border border-slate-800 px-3.5 py-2.5 rounded-xl flex items-center gap-2" aria-live="polite">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
          <span>Updating vacancy matches...</span>
        </div>
      )}

      {/* Empty State */}
      {!isLoadingJobs && !jobsError && filteredDbJobs.length === 0 && (
        <div className="text-xs text-slate-400 text-center py-8 border border-dashed border-slate-700 bg-slate-950/60 rounded-xl space-y-3">
          {!profileUploaded ? (
            <>
              <h4 className="text-sm font-bold text-white">
                Upload your skills.md file to scan tailored live vacancies
              </h4>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                Your discovery feed adapts automatically to any domain. Upload <code className="text-emerald-300">skills.md</code> to discover Direct Matches, Adjacent Transferable Roles, and Public Sector vacancies.
              </p>
              <button
                onClick={onUploadClick}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-500 text-white text-xs font-bold shadow-md transition-colors"
              >
                <Upload className="w-3.5 h-3.5" />
                <span>Upload skills.md Now</span>
              </button>
            </>
          ) : selectedPortalFilter !== 'ALL' ? (
            <div className="space-y-2 max-w-lg mx-auto">
              <h4 className="text-sm font-bold text-white">
                No active suitable vacancies currently on {selectedPortalFilter}
              </h4>
              <p className="text-xs text-slate-400 leading-relaxed">
                {selectedPortalFilter === 'dou.ua'
                  ? 'Many postings on DOU.ua require local Ukrainian or Russian language fluency. If you speak Ukrainian or Russian, add it to your skills.md to unlock Ukrainian remote roles; otherwise, explore English remote roles or switch to other portals.'
                  : selectedPortalFilter === 'headhunter.ge'
                  ? 'HeadHunter.ge postings often require Russian language. Add Russian to your skills.md to unlock them, or switch to Jobs.ge / HR.ge.'
                  : `Currently no active listings on ${selectedPortalFilter} match your experience level and location criteria.`}
              </p>
              <div className="flex items-center justify-center gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => onSelectPortalFilter('ALL')}
                  className="px-3.5 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-500 text-white font-semibold"
                >
                  View All Portals
                </button>
                <button
                  type="button"
                  onClick={onRunScrapers}
                  disabled={isScraping}
                  className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-semibold"
                >
                  Re-scan Portals
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              <h4 className="text-sm font-bold text-white">No matching live vacancies in this tab</h4>
              <p className="text-xs text-slate-400">
                Try switching between Direct Matches, Optimal Adjacent Roles, or All Tiers above, or click <strong>Run Live Role Scrapers</strong>.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {filteredDbJobs.map((job) => {
          const isStaged = job.status === 'STAGED';
          const tier = job.match_tier || (job.portal === 'hr.gov.ge' ? 'PUBLIC_INTERNSHIP' : 'DIRECT');
          const salaryStr = formatSalaryDisplay(job);
          return (
            <div
              key={`${job.portal}-${job.external_id}`}
              role="button"
              tabIndex={0}
              onClick={() => onSelectJob(job)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelectJob(job);
                }
              }}
              aria-label={`Inspect ${job.title} at ${job.company}`}
              className={`p-3.5 rounded-xl border cursor-pointer transition-all flex flex-col justify-between text-left ${
                isStaged
                  ? 'bg-slate-950 border-emerald-700/60 hover:border-emerald-400'
                  : tier === 'ADJACENT'
                  ? 'bg-slate-950 border-indigo-700/60 hover:border-indigo-400'
                  : 'bg-slate-950/70 border-slate-800 hover:border-slate-600'
              }`}
            >
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-1 flex-wrap">
                  <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-slate-900 text-emerald-300 border border-slate-700">
                    {job.portal} • {job.market}
                  </span>
                  <div className="flex items-center gap-1">
                    {onToggleSaveJob && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleSaveJob(job);
                        }}
                        aria-label={savedJobIds?.has(job.id) ? `Unsave ${job.title}` : `Save ${job.title}`}
                        className={`p-1 rounded-md border transition-colors ${
                          savedJobIds?.has(job.id)
                            ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                            : 'bg-slate-900 border-slate-800 text-slate-300 hover:text-amber-300'
                        }`}
                        title={savedJobIds?.has(job.id) ? 'Remove from Saved Jobs' : 'Bookmark / Save Job for later'}
                      >
                        <Star
                          className={`w-3 h-3 ${
                            savedJobIds?.has(job.id) ? 'fill-amber-400 text-amber-400' : ''
                          }`}
                          aria-hidden="true"
                        />
                      </button>
                    )}
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
                </div>

                {tier === 'ADJACENT' && (
                  <div className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md bg-indigo-950/90 text-indigo-300 border border-indigo-700/60">
                    <Sparkles className="w-2.5 h-2.5" />
                    <span>
                      {job.adjacent_role_tag ||
                        `Adjacent Opportunity: ${job.skill_overlap_pct || Math.round(job.suitability_score)}% Skill Overlap`}
                    </span>
                  </div>
                )}

                {tier === 'PUBLIC_INTERNSHIP' && (
                  <div className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md bg-cyan-950/90 text-cyan-200 border border-cyan-700/60">
                    <Landmark className="w-2.5 h-2.5" aria-hidden="true" />
                    <span>Public Sector</span>
                  </div>
                )}

                {tier === 'DIRECT' && job.adjacent_role_tag === 'Entry-Level / Internship' && (
                  <div className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md bg-emerald-950/90 text-emerald-200 border border-emerald-700/60">
                    <span>Entry-Level / Internship</span>
                  </div>
                )}

                {job.contract_mode && (
                  <div
                    title={job.eligibility_note || ''}
                    className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-md border ${
                      job.contract_mode === 'REMOTE_B2B'
                        ? 'bg-teal-950/80 text-teal-200 border-teal-700/60'
                        : job.contract_mode === 'GE_LOCAL'
                        ? 'bg-emerald-950/80 text-emerald-200 border-emerald-700/60'
                        : 'bg-amber-950/70 text-amber-200 border-amber-700/60'
                    }`}
                  >
                    <span>
                      {job.contract_mode === 'REMOTE_B2B'
                        ? 'Global B2B (1% Tax Eligible)'
                        : job.contract_mode === 'GE_LOCAL'
                        ? 'Georgia Market'
                        : 'Region Check Needed'}
                    </span>
                  </div>
                )}

                <h4 className="text-xs font-bold text-white line-clamp-2 leading-snug">{job.title}</h4>
                <div className="text-[11px] text-slate-300 font-medium">{job.company}</div>

                {salaryStr ? (
                  <div className="flex items-center gap-1.5 text-[11px] pt-0.5 flex-wrap">
                    <span className="text-emerald-300 font-semibold">{salaryStr}</span>
                    {job.salary_source === 'ai_estimated' || job.salary_estimated_by_ai ? (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-950/70 text-amber-200 border border-amber-800/70">
                        AI Estimated
                      </span>
                    ) : (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-950/70 text-emerald-200 border border-emerald-800/70">
                        Verified
                      </span>
                    )}
                  </div>
                ) : (
                  <div className="text-[10px] text-slate-400 pt-0.5">
                    {(job.description_raw || '').includes('არ ითვალისწინებს ანაზღაურებას') ||
                    (job.description_raw || '').toLowerCase().includes('unpaid')
                      ? 'Salary: Unpaid Internship'
                      : 'Salary: Not Listed'}
                  </div>
                )}

                <div className="flex items-center gap-2 flex-wrap">
                  {(() => {
                    const posted = formatPostedBadge(job);
                    if (!posted) return null;
                    return (
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded-md border ${
                          posted.isFresh
                            ? 'bg-emerald-950/60 border-emerald-700/60 text-emerald-300 font-semibold'
                            : 'bg-slate-900 border-slate-800 text-slate-300'
                        }`}
                      >
                        Posted: {posted.label}
                      </span>
                    );
                  })()}
                  {job.deadline_text && (
                    <span className="text-[10px] text-amber-200 bg-amber-950/50 border border-amber-800/60 px-2 py-0.5 rounded-md">
                      Deadline: {job.deadline_text}
                    </span>
                  )}
                </div>

                <div className="text-[10px] text-slate-300 line-clamp-2 pt-1 border-t border-slate-800/60">
                  <span>{job.match_rationale}</span>
                </div>
              </div>

              <div className="pt-2 mt-2 border-t border-slate-800/60 space-y-2 text-[10px]">
                <div className="flex items-center justify-between">
                  <span className="text-emerald-300 font-semibold">View Details &amp; Tailor CV</span>
                  <span className="text-slate-300">Lang: {(job.language_requirements || []).join(', ') || 'EN'}</span>
                </div>

                <div className="flex items-center gap-1.5 pt-1">
                  {job.delivery_channel === 'EMAIL' || Boolean(job.target_email) ? (
                    <>
                      <button
                        type="button"
                        disabled={draftingJobId === job.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          onDraftInGmail(job);
                        }}
                        className="flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg bg-rose-700 hover:bg-rose-500 text-white font-semibold transition-colors disabled:opacity-50"
                        title="Generate Tailored Word CV (.docx) + Cover Letter and save Gmail Draft"
                      >
                        <Mail className="w-3 h-3" />
                        <span>{draftingJobId === job.id ? 'Preparing...' : 'Draft in Gmail'}</span>
                      </button>
                      <a
                        href={job.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-700"
                        aria-label={`Open original posting for ${job.title}`}
                        title="Open live job page in new tab"
                      >
                        <ExternalLink className="w-3 h-3" aria-hidden="true" />
                      </a>
                    </>
                  ) : (
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-100 border border-slate-700 font-semibold transition-colors"
                      aria-label={`Open original posting for ${job.title}`}
                    >
                      <ExternalLink className="w-3 h-3" aria-hidden="true" />
                      <span>Open on {job.portal}</span>
                    </a>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Server-Side Pagination Bar */}
      {onPageChange && (totalJobs ?? filteredDbJobs.length) > 0 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-2 pt-3 border-t border-slate-800/80 text-xs">
          <span className="text-slate-400">
            Page <strong className="text-white">{page}</strong> of <strong className="text-white">{totalPages}</strong> &bull;{' '}
            <strong className="text-emerald-300">{totalJobs ?? filteredDbJobs.length}</strong> total matching opportunities
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => onPageChange(Math.max(1, page - 1))}
              className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 hover:text-white disabled:opacity-40"
            >
              Previous
            </button>
            {(() => {
              const totalP = Math.max(1, totalPages || 1);
              const winStart = Math.max(1, Math.min(page - 2, totalP - 4));
              const winEnd = Math.min(totalP, winStart + 4);
              const pages: number[] = [];
              for (let p = winStart; p <= winEnd; p++) pages.push(p);
              return (
                <>
                  {winStart > 1 && (
                    <>
                      <button
                        type="button"
                        onClick={() => onPageChange(1)}
                        className="px-2.5 py-1.5 rounded-lg font-semibold bg-slate-950 border border-slate-800 text-slate-300 hover:text-white"
                      >
                        1
                      </button>
                      {winStart > 2 && <span className="px-1 text-slate-400">...</span>}
                    </>
                  )}
                  {pages.map((pNum) => (
                    <button
                      key={pNum}
                      type="button"
                      onClick={() => onPageChange(pNum)}
                      className={`px-2.5 py-1.5 rounded-lg font-semibold ${
                        pNum === page
                          ? 'bg-emerald-700 text-white'
                          : 'bg-slate-950 border border-slate-800 text-slate-300 hover:text-white'
                      }`}
                    >
                      {pNum}
                    </button>
                  ))}
                  {winEnd < totalP && (
                    <>
                      {winEnd < totalP - 1 && <span className="px-1 text-slate-400">...</span>}
                      <button
                        type="button"
                        onClick={() => onPageChange(totalP)}
                        className="px-2.5 py-1.5 rounded-lg font-semibold bg-slate-950 border border-slate-800 text-slate-300 hover:text-white"
                      >
                        {totalP}
                      </button>
                    </>
                  )}
                </>
              );
            })()}
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => onPageChange(Math.min(totalPages, page + 1))}
              className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 hover:text-white disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
