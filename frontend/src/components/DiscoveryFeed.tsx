import React, { useState } from 'react';
import {
  Database,
  RefreshCw,
  Mail,
  Download,
  ExternalLink,
  Play,
  Upload,
  Compass,
  Sparkles,
  Landmark,
  Target,
  Search,
  Star,
  Globe,
  X,
} from 'lucide-react';
import { DbJobPosting } from '../types';
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
  max_allowed_years?: number;
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
  preparedEmailPkg: PreparedEmailPkg | null;
  onDismissEmailPkg: () => void;
  draftingJobId: number | null;
  onRunScrapers: () => void;
  onUploadClick: () => void;
  onSelectJob: (job: DbJobPosting) => void;
  onOpenFillForm?: (job: DbJobPosting) => void;
  onDraftInGmail: (job: DbJobPosting) => void;
  searchQuery?: string;
  onSearchQueryChange?: (q: string) => void;
  remoteTypeFilter?: string;
  onRemoteTypeFilterChange?: (mode: string) => void;
  onlySavedFilter?: boolean;
  onOnlySavedFilterChange?: (val: boolean) => void;
  savedJobIds?: Set<number>;
  onToggleSaveJob?: (job: DbJobPosting) => void;
}

function formatSalaryDisplay(job: DbJobPosting): string | null {
  if (!job.salary_min || !job.salary_max) return null;
  const curRaw = (job.salary_currency || 'USD').trim();
  const curUpper = curRaw.toUpperCase();
  const isGel =
    curUpper === 'GEL' ||
    curRaw === '₾' ||
    curRaw.toLowerCase() === 'ლარი' ||
    curRaw === 'ᲚᲐᲠᲘ';
  const sym = isGel ? '₾' : curUpper === 'EUR' ? '€' : curUpper === 'GBP' ? '£' : '$';
  const labelCur = isGel ? 'GEL' : curUpper;
  if (job.salary_min === job.salary_max) {
    return `${job.salary_max.toLocaleString()} ${sym} (${labelCur})`;
  }
  return `${job.salary_min.toLocaleString()}–${job.salary_max.toLocaleString()} ${sym} (${labelCur})`;
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
  preparedEmailPkg,
  onDismissEmailPkg,
  draftingJobId,
  onRunScrapers,
  onUploadClick,
  onSelectJob,
  onOpenFillForm,
  onDraftInGmail,
  searchQuery = '',
  onSearchQueryChange,
  remoteTypeFilter = 'ALL',
  onRemoteTypeFilterChange,
  onlySavedFilter = false,
  onOnlySavedFilterChange,
  savedJobIds,
  onToggleSaveJob,
}) => {
  const [localTierTab, setLocalTierTab] = useState<'ALL' | 'DIRECT' | 'ADJACENT' | 'PUBLIC_INTERNSHIP'>('ALL');
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

  const expVal = candidateProfile?.experience_years ?? 1.5;
  const capVal = candidateProfile?.max_allowed_years ?? Math.min(expVal + 0.5, 2.0);
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
        <div className="p-3.5 rounded-xl bg-slate-950/90 border border-sky-500/30 flex flex-col lg:flex-row lg:items-center justify-between gap-2.5">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-1 font-bold text-sky-300">
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
                Experience:{' '}
                <strong className="text-amber-300">
                  {expVal} Yrs (Cap: {capVal.toFixed(1)} Yrs)
                </strong>
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
          <span className="text-[10px] px-2.5 py-1 rounded-full bg-emerald-950/60 border border-emerald-700/50 text-emerald-300 font-semibold self-start lg:self-center">
            Strict &le; {capVal.toFixed(1)} Yr Experience Guard Active
          </span>
        </div>
      )}

      {/* Header + Scan CTA */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Database className="w-4 h-4 text-emerald-400" />
            Universal Multi-Tier Optimal Opportunity Feed
          </h3>
          <p className="text-xs text-slate-400">
            Adapts dynamically to any uploaded <code>skills.md</code> across <strong>Jobs.ge</strong>, <strong>HR.ge</strong>, <strong>HeadHunter.ge</strong>, <strong>HR.gov.ge</strong>, <strong>Djinni.co</strong>, <strong>DOU.ua</strong> &amp; <strong>JustJoin.it</strong>.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onUploadClick}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/40 text-sky-300 text-xs font-bold transition-all"
            title="Upload or replace your skills.md profile"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>{profileUploaded ? 'Update skills.md' : 'Upload skills.md'}</span>
          </button>

          <button
            type="button"
            onClick={onRunScrapers}
            disabled={isScraping}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-bold shadow-md shadow-emerald-600/20 transition-all disabled:opacity-50"
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
                  ? 'bg-sky-600 text-white'
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
        <button
          onClick={() => handleTierClick('ALL')}
          className={`text-xs px-3 py-1.5 rounded-xl font-bold transition-all ${
            tierTab === 'ALL'
              ? 'bg-slate-800 text-white border border-slate-600'
              : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
          }`}
        >
          All Tiers ({tierCounts?.ALL ?? totalJobs ?? visibleJobs.length})
        </button>
        <button
          onClick={() => handleTierClick('DIRECT')}
          className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl font-bold transition-all ${
            tierTab === 'DIRECT'
              ? 'bg-emerald-600 text-white shadow-sm shadow-emerald-600/20'
              : 'bg-slate-950 text-slate-300 hover:text-white border border-slate-800'
          }`}
        >
          <Target className="w-3.5 h-3.5" />
          <span>🎯 Direct Matches ({tierCounts?.DIRECT ?? directJobs.length})</span>
        </button>
        <button
          onClick={() => handleTierClick('ADJACENT')}
          className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl font-bold transition-all ${
            tierTab === 'ADJACENT'
              ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/20'
              : 'bg-slate-950 text-slate-300 hover:text-white border border-slate-800'
          }`}
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span>🚀 Optimal Adjacent Roles ({tierCounts?.ADJACENT ?? adjacentJobs.length})</span>
        </button>
        <button
          onClick={() => handleTierClick('PUBLIC_INTERNSHIP')}
          className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl font-bold transition-all ${
            tierTab === 'PUBLIC_INTERNSHIP'
              ? 'bg-cyan-600 text-white shadow-sm shadow-cyan-600/20'
              : 'bg-slate-950 text-slate-300 hover:text-white border border-slate-800'
          }`}
        >
          <Landmark className="w-3.5 h-3.5" />
          <span>🏛️ Public Sector &amp; Internships ({tierCounts?.PUBLIC_INTERNSHIP ?? publicJobs.length})</span>
        </button>
      </div>

      {/* Portal Filter Chips + Search & Work Mode Bar */}
      <div className="space-y-2.5 pt-2 border-t border-slate-800/60">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5">
          {/* Live Keyword Search Input */}
          {onSearchQueryChange && (
            <div className="relative flex-1 max-w-md">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => onSearchQueryChange(e.target.value)}
                placeholder="Search by role, company, or skill (e.g. QA, Python, API, TBC)..."
                className="w-full pl-8 pr-8 py-1.5 rounded-xl bg-slate-950 border border-slate-800 focus:border-sky-500 focus:outline-none text-xs text-white placeholder-slate-500"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => onSearchQueryChange('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                  title="Clear search"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}

          {/* Work Mode & Saved Jobs Filter Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            {onRemoteTypeFilterChange && (
              <>
                <span className="text-[10px] font-bold uppercase text-slate-500 mr-1 inline-flex items-center gap-1">
                  <Globe className="w-3 h-3" /> Mode:
                </span>
                {[
                  { id: 'ALL', label: 'All Modes' },
                  { id: 'REMOTE', label: '🌍 Remote' },
                  { id: 'HYBRID', label: '🏢 Hybrid' },
                  { id: 'ONSITE', label: '📍 On-Site' },
                ].map((mode) => (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => onRemoteTypeFilterChange(mode.id)}
                    className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition-colors ${
                      remoteTypeFilter === mode.id
                        ? 'bg-indigo-600 text-white'
                        : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
                    }`}
                  >
                    {mode.label}
                  </button>
                ))}
              </>
            )}

            {onOnlySavedFilterChange && (
              <button
                type="button"
                onClick={() => onOnlySavedFilterChange(!onlySavedFilter)}
                className={`inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg font-semibold transition-colors ${
                  onlySavedFilter
                    ? 'bg-amber-500/20 border border-amber-500/60 text-amber-300'
                    : 'bg-slate-950 text-slate-400 hover:text-amber-300 border border-slate-800'
                }`}
              >
                <Star className={`w-3 h-3 ${onlySavedFilter ? 'fill-amber-400 text-amber-400' : ''}`} />
                <span>Saved ({savedJobIds ? savedJobIds.size : 0})</span>
              </button>
            )}
          </div>
        </div>

        {/* Portal Filter Chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-bold uppercase text-slate-500 mr-1">Portals:</span>
          {portals.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onSelectPortalFilter(p)}
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
      </div>

      {/* Prepared Gmail Package Banner */}
      {preparedEmailPkg && (
        <div
          className={`p-4 rounded-xl border text-xs space-y-2.5 ${
            preparedEmailPkg.gmail_draft_saved
              ? 'bg-emerald-950/35 border-emerald-700/60'
              : 'bg-sky-950/35 border-sky-700/60'
          }`}
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <span
                className={`text-[10px] font-bold uppercase block ${
                  preparedEmailPkg.gmail_draft_saved ? 'text-emerald-400' : 'text-sky-400'
                }`}
              >
                {preparedEmailPkg.gmail_draft_saved
                  ? `Gmail Draft created with ${preparedEmailPkg.docx_filename} ALREADY attached — open Gmail Drafts and click Send!`
                  : `CV downloaded (${preparedEmailPkg.docx_filename}) — attach it in Gmail Compose (or configure Gmail App Password for auto-attachment)`}
              </span>
              <span className="text-white font-semibold">
                {preparedEmailPkg.title} ({preparedEmailPkg.company}) &mdash; Subject:{' '}
                <code className="text-sky-300">{preparedEmailPkg.subject}</code>
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
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold"
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

      {/* Synchronized Feed Stats Banner */}
      {(Boolean(totalJobs) || visibleJobs.length > 0 || Boolean(scrapeStats)) && (
        <div className="text-xs bg-emerald-950/30 border border-emerald-800/60 text-emerald-300 px-3.5 py-2 rounded-xl flex items-center justify-between flex-wrap gap-2">
          <span>
            ✅ Found <strong>{totalJobs ?? visibleJobs.length}</strong> suitable opportunities ({tierCounts?.DIRECT ?? directJobs.length} Direct • {tierCounts?.ADJACENT ?? adjacentJobs.length} Adjacent • {tierCounts?.PUBLIC_INTERNSHIP ?? publicJobs.length} Public/Intern)
            <span className="text-sky-300 ml-1.5">(showing {visibleJobs.length} on page {page} of {totalPages})</span>
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

      {/* Empty State */}
      {filteredDbJobs.length === 0 && (
        <div className="text-xs text-slate-400 text-center py-8 border border-dashed border-slate-700 bg-slate-950/60 rounded-xl space-y-3">
          {!profileUploaded ? (
            <>
              <h4 className="text-sm font-bold text-white">
                Upload your skills.md file to scan tailored live vacancies
              </h4>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                Your discovery feed adapts automatically to any domain. Upload <code className="text-sky-300">skills.md</code> to discover Direct Matches, Adjacent Transferable Roles, and Public Sector Internships.
              </p>
              <button
                onClick={onUploadClick}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-bold shadow-md transition-colors"
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
                  : `Currently no active listings on ${selectedPortalFilter} match your strict experience cap (<= ${capVal.toFixed(1)} yrs) and location criteria.`}
              </p>
              <div className="flex items-center justify-center gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => onSelectPortalFilter('ALL')}
                  className="px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold"
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
              onClick={() => onSelectJob(job)}
              className={`p-3.5 rounded-xl border cursor-pointer transition-all flex flex-col justify-between ${
                isStaged
                  ? 'bg-slate-950 border-emerald-700/60 hover:border-emerald-500'
                  : tier === 'ADJACENT'
                  ? 'bg-slate-950 border-indigo-700/60 hover:border-indigo-500'
                  : 'bg-slate-950/70 border-slate-800 hover:border-slate-700'
              }`}
            >
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-1 flex-wrap">
                  <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-slate-900 text-sky-400 border border-slate-700">
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
                        className={`p-1 rounded-md border transition-colors ${
                          savedJobIds?.has(job.id)
                            ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                            : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-amber-300'
                        }`}
                        title={savedJobIds?.has(job.id) ? 'Remove from Saved Jobs' : 'Bookmark / Save Job for later'}
                      >
                        <Star
                          className={`w-3 h-3 ${
                            savedJobIds?.has(job.id) ? 'fill-amber-400 text-amber-400' : ''
                          }`}
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
                  <div className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md bg-cyan-950/90 text-cyan-300 border border-cyan-700/60">
                    <Landmark className="w-2.5 h-2.5" />
                    <span>Public Sector / Internship</span>
                  </div>
                )}

                <h4 className="text-xs font-bold text-white line-clamp-2 leading-snug">{job.title}</h4>
                <div className="text-[11px] text-slate-300 font-medium">{job.company}</div>

                {salaryStr ? (
                  <div className="flex items-center gap-1.5 text-[11px] pt-0.5">
                    <span className="text-emerald-300 font-semibold">{salaryStr}</span>
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
                  {job.delivery_channel === 'EMAIL' || Boolean(job.target_email) ? (
                    <button
                      type="button"
                      disabled={draftingJobId === job.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        onDraftInGmail(job);
                      }}
                      className="flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg bg-rose-600/90 hover:bg-rose-500 text-white font-semibold transition-colors disabled:opacity-50"
                      title="Generate Tailored Word CV (.docx) + Cover Letter and save Gmail Draft"
                    >
                      <Mail className="w-3 h-3" />
                      <span>{draftingJobId === job.id ? 'Preparing...' : 'Draft in Gmail'}</span>
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (onOpenFillForm) {
                          onOpenFillForm(job);
                        } else {
                          onSelectJob(job);
                        }
                      }}
                      className="flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold transition-colors"
                    >
                      <Play className="w-3 h-3" />
                      <span>Open &amp; Fill Form</span>
                    </button>
                  )}

                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700"
                    title="Open live job page in new tab"
                  >
                    <ExternalLink className="w-3 h-3" />
                  </a>
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
            {Array.from({ length: Math.min(totalPages, 5) }, (_, idx) => idx + 1).map((pNum) => (
              <button
                key={pNum}
                type="button"
                onClick={() => onPageChange(pNum)}
                className={`px-2.5 py-1.5 rounded-lg font-semibold ${
                  pNum === page
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-950 border border-slate-800 text-slate-400 hover:text-white'
                }`}
              >
                {pNum}
              </button>
            ))}
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
