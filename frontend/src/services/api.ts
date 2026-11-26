/// <reference types="vite/client" />
import {
  GroundTruth,
  JobAuditResponse,
  GenerateAnswersResponse,
  ScreeningQuestion,
  StageApplicationResponse,
  ApplicationItem,
  PortalVacancyItem,
  SkillsPresetItem,
  DbJobPosting,
  JobSearchParams,
  PaginatedJobsResponse,
  ParsedSkillsTaxonomy,
  ScraperSourceHealthItem,
  UserProfile,
  AuthResponse,
  SkillActionPlan,
  InterviewBrief,
  PlatformMetrics,
  AdminUser,
  CVVersionItem,
  CandidateAnalyticsResponse,
  AIMetricsResponse,
  BulletDiffItem,
  ATSParseReport,
  SavedSearchItem,
  NotificationItem,
  B2BTaxCalculatorResponse,
  TimezoneMatrixResponse,
  B2BProposalResponse,
  B2BFxRatesResponse,
  B2BInvoiceResponse,
} from '../types';

export const BACKEND_ORIGIN = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const API_BASE = `${BACKEND_ORIGIN}/api`;
const ACCESS_TOKEN_KEY = 'talentflow_token';
const REFRESH_TOKEN_KEY = 'talentflow_refresh_token';

function saveAuthTokens(data: AuthResponse): void {
  if (data.access_token) localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
  // Web refresh tokens live in HttpOnly cookies set by /api/auth/*; never persist in localStorage
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  return token
    ? { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
    : { 'Content-Type': 'application/json' };
}

let inFlightRefresh: Promise<boolean> | null = null;

export async function refreshAccessToken(): Promise<boolean> {
  if (inFlightRefresh) return inFlightRefresh;
  const legacyRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  inFlightRefresh = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: legacyRefreshToken ? JSON.stringify({ refresh_token: legacyRefreshToken }) : '{}',
      });
      if (!res.ok) return false;
      saveAuthTokens(await res.json());
      return true;
    } catch {
      return false;
    } finally {
      inFlightRefresh = null;
    }
  })();
  return inFlightRefresh;
}

/** Fetch wrapper with automatic Bearer injection and single-flight 401 refresh retry. */
export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const withAuth = (token: string | null): Headers => {
    const h = new Headers(init.headers || {});
    if (token) h.set('Authorization', `Bearer ${token}`);
    return h;
  };
  let res = await fetch(url, { ...init, headers: withAuth(localStorage.getItem(ACCESS_TOKEN_KEY)) });
  if (res.status === 401 && !url.includes('/auth/refresh') && !url.includes('/auth/login')) {
    if (await refreshAccessToken()) {
      res = await fetch(url, { ...init, headers: withAuth(localStorage.getItem(ACCESS_TOKEN_KEY)) });
    } else {
      logoutUser();
      window.dispatchEvent(new Event('talentflow:auth-expired'));
    }
  }
  return res;
}

async function readErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (data?.detail) return String(data.detail);
  } catch {}
  return fallback;
}

async function apiJson<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    errorMessage?: string;
    signal?: AbortSignal;
    fallbackValue?: T;
    rawBody?: BodyInit;
  } = {}
): Promise<T> {
  const { method = 'GET', body, errorMessage = 'Request failed', signal, fallbackValue, rawBody } = options;
  const init: RequestInit = { method, signal };
  if (rawBody !== undefined) {
    init.body = rawBody;
  } else {
    init.headers = getAuthHeaders();
    if (body !== undefined) init.body = JSON.stringify(body);
  }
  const res = await apiFetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    if (fallbackValue !== undefined) return fallbackValue;
    throw new Error(await readErrorDetail(res, errorMessage));
  }
  return res.json();
}

async function apiVoid(path: string, method: string, errorMessage?: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}${path}`, { method, headers: getAuthHeaders() });
  if (!res.ok && errorMessage) throw new Error(await readErrorDetail(res, errorMessage));
}

async function authPost<T>(path: string, body: unknown, errorMessage: string, persistTokens = true): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    credentials: persistTokens ? 'include' : undefined,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readErrorDetail(res, errorMessage));
  const data: T = await res.json();
  if (persistTokens) saveAuthTokens(data as unknown as AuthResponse);
  return data;
}

export async function fetchHealth(): Promise<{
  status: string;
  gemini: { connected: boolean; model: string; mode: string };
  ai?: {
    connected: boolean;
    active_provider: string;
    active_model: string;
    mode: string;
    fallback_provider?: string | null;
    providers?: Record<string, { configured: boolean; model: string; free_tier: boolean }>;
  };
}> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error('Backend offline');
  return res.json();
}

export const fetchVacancies = (): Promise<PortalVacancyItem[]> =>
  apiJson('/vacancies', { errorMessage: 'Failed to fetch portal vacancies' });

export const fetchGroundTruth = (): Promise<GroundTruth> =>
  apiJson('/ground-truth', { errorMessage: 'Failed to fetch ground truth' });

export async function saveGroundTruth(data: GroundTruth): Promise<GroundTruth> {
  const json = await apiJson<{ data: GroundTruth; synced_cv_versions?: number }>('/ground-truth', {
    method: 'PUT',
    body: data,
    errorMessage: 'Failed to update ground truth',
  });
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('talentflow:profile-updated', { detail: { syncedCvVersions: json.synced_cv_versions || 0 } })
    );
  }
  return json.data;
}

export const fetchSkillsMd = (): Promise<{ filename: string; content: string; extracted_skills: string[] }> =>
  apiJson('/skills-md', { errorMessage: 'Failed to load skills.md' });

export async function fetchSkillsPresets(): Promise<{ presets: SkillsPresetItem[] }> {
  const res = await fetch(`${API_BASE}/skills-md/presets`);
  return res.ok ? res.json() : { presets: [] };
}

export const applySkillsPreset = (
  presetId: string
): Promise<{ status: string; preset_id: string; content: string; extracted_skills: string[]; ground_truth: GroundTruth; message: string }> =>
  apiJson(`/skills-md/preset/${presetId}`, { method: 'POST', errorMessage: 'Failed to apply skills preset' });

export const saveSkillsMdText = (
  content: string
): Promise<{ status: string; message: string; extracted_skills: string[]; ground_truth: GroundTruth }> =>
  apiJson('/skills-md', { method: 'POST', body: { content }, errorMessage: 'Failed to save skills.md' });

export async function uploadSkillsMdFile(file: File): Promise<{
  status: string;
  filename: string;
  content: string;
  extracted_skills: string[];
  parsed_skills?: ParsedSkillsTaxonomy;
  scrape_summary?: any;
  message: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('run_live_scrape', 'false');
  const data = await apiJson<any>('/profile/upload-skills', {
    method: 'POST',
    rawBody: formData,
    errorMessage: 'Failed to upload .md file',
  });
  const allSkills: string[] = data.parsed_skills?.all_skills || [];
  return {
    status: data.status,
    filename: data.filename || file.name,
    content: data.raw_markdown || '',
    extracted_skills: allSkills,
    parsed_skills: data.parsed_skills,
    scrape_summary: data.scrape_summary,
    message: `Uploaded ${file.name} into SQLite CandidateProfile (${allSkills.length} skills indexed)!`,
  };
}

export const fetchDbProfile = (): Promise<{
  id: number;
  profile_uploaded?: boolean;
  raw_markdown: string;
  parsed_skills: ParsedSkillsTaxonomy;
  updated_at: string;
}> => apiJson('/profile', { errorMessage: 'Failed to load CandidateProfile from DB' });

export const fetchProfileIntelligence = (): Promise<import('../types').ProfileIntelligenceResponse> =>
  apiJson('/profile/intelligence', { errorMessage: 'Failed to load profile intelligence' });

export async function previewProfileImport(file: File): Promise<import('../types').ProfileImportPreviewResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return apiJson('/profile/import-preview', {
    method: 'POST',
    rawBody: formData,
    errorMessage: 'Failed to extract CV preview',
  });
}

export const applyProfileImport = (payload: {
  filename: string;
  extracted: Record<string, any>;
  section_modes: Record<string, string>;
}): Promise<{ status: string; synced_cv_versions: number; data: GroundTruth; intelligence: import('../types').ProfileIntelligenceResponse }> =>
  apiJson('/profile/import-apply', {
    method: 'POST',
    body: payload,
    errorMessage: 'Failed to apply reviewed profile import',
  });

export async function fetchScrapedJobs(
  params?: JobSearchParams | string,
  signal?: AbortSignal
): Promise<PaginatedJobsResponse> {
  const qs = new URLSearchParams();
  if (typeof params === 'string') {
    if (params && params !== 'ALL') qs.set('status', params);
  } else if (params) {
    const entries: Array<[string, string | number | boolean | undefined]> = [
      ['page', params.page],
      ['limit', params.limit],
      ['portal', params.portal !== 'ALL' ? params.portal : undefined],
      ['market', params.market !== 'ALL' ? params.market : undefined],
      ['status', params.status !== 'ALL' ? params.status : undefined],
      ['min_score', params.min_score],
      ['include_filtered', params.include_filtered ? 'true' : undefined],
      ['include_dismissed', params.include_dismissed ? 'true' : undefined],
      ['industry', params.industry && params.industry !== 'ALL' ? params.industry : undefined],
      ['tier', params.tier !== 'ALL' ? params.tier : undefined],
      ['search', params.search?.trim()],
      ['country', params.country?.trim()],
      ['city', params.city?.trim()],
      ['remote_type', params.remote_type !== 'ALL' ? params.remote_type : undefined],
      ['salary_min', params.salary_min && params.salary_min > 0 ? params.salary_min : undefined],
      ['language', params.language && params.language !== 'ALL' ? params.language.trim() : undefined],
      ['technology', params.technology?.trim()],
      ['experience_level', params.experience_level !== 'ALL' ? params.experience_level : undefined],
      ['employment_type', params.employment_type !== 'ALL' ? params.employment_type : undefined],
      ['sort_by', params.sort_by],
      ['posted_within_days', params.posted_within_days && params.posted_within_days > 0 ? params.posted_within_days : undefined],
      ['only_new', params.only_new ? 'true' : undefined],
      ['only_saved', params.only_saved ? 'true' : undefined],
      ['b2b_only', params.b2b_only ? 'true' : undefined],
      ['geo_eligible_only', params.geo_eligible_only ? 'true' : undefined],
    ];
    for (const [k, v] of entries) {
      if (v !== undefined && v !== '') qs.set(k, String(v));
    }
  }
  const queryStr = qs.toString() ? `?${qs.toString()}` : '';
  const data = await apiJson<PaginatedJobsResponse | DbJobPosting[]>(`/jobs${queryStr}`, {
    signal,
    errorMessage: 'Failed to load vacancies',
  });
  return Array.isArray(data)
    ? { items: data, total: data.length, page: 1, limit: data.length || 12, total_pages: 1 }
    : data;
}

export const fetchScraperSourceHealth = (): Promise<{ sources: ScraperSourceHealthItem[]; default_portals: string[] }> =>
  apiJson('/jobs/sources/health', { errorMessage: 'Failed to fetch source health' });

export const triggerMultiPortalScrape = (
  allowNetwork = true
): Promise<{
  total_processed: number;
  staged_ready_count: number;
  filtered_out_count: number;
  cache_hits?: number;
  rejection_reasons?: Array<{ portal: string; title: string; company: string; reason: string }>;
  jobs: DbJobPosting[];
}> => apiJson('/jobs/scrape', { method: 'POST', body: { allow_network: allowNetwork }, errorMessage: 'Scraper run failed' });

export const triggerAsyncScrape = (allowNetwork = true): Promise<{ task_id: string; status: string; deduplicated?: boolean }> =>
  apiJson('/jobs/scrape/async', { method: 'POST', body: { allow_network: allowNetwork }, errorMessage: 'Failed to start background scraper' });

export const fetchScrapeTaskStatus = (
  taskId: string
): Promise<{
  task_id: string;
  status: string;
  progress_pct?: number;
  total_processed: number;
  staged_count: number;
  filtered_out_count: number;
  error_message?: string | null;
}> => apiJson(`/jobs/scrape/status/${encodeURIComponent(taskId)}`, { errorMessage: 'Failed to check scrape task status' });

export const fetchGeneratedResumes = (): Promise<
  Array<{ filename: string; url: string; docx_url?: string | null; html_url?: string | null; size_kb: number }>
> => apiJson('/resumes/generated', { fallbackValue: [] });

export const fetchMyCvs = (): Promise<Array<{ filename: string; url: string; ext: string; size_kb: number }>> =>
  apiJson('/resumes/my-cvs', { fallbackValue: [] });

export function uploadPersonalCv(file: File): Promise<{ status: string; filename: string; url: string; ext: string; size_kb: number }> {
  const formData = new FormData();
  formData.append('file', file);
  return apiJson('/resumes/my-cvs/upload', { method: 'POST', rawBody: formData, errorMessage: 'Failed to upload CV' });
}

export const deletePersonalCv = (filename: string): Promise<void> =>
  apiVoid(`/resumes/my-cvs/${encodeURIComponent(filename)}`, 'DELETE', 'Failed to delete CV');

export const generateCvEdition = (params: {
  edition: 'ats' | 'recruiter' | 'tailored';
  target_role?: string;
  target_company?: string;
  job_description?: string;
  job_url?: string;
  cv_language?: 'en' | 'ka';
}): Promise<{
  status: string;
  edition: string;
  company: string;
  title: string;
  subject: string;
  cover_letter: string;
  motivational_letter?: string;
  cv_language: string;
  docx_filename: string;
  docx_url: string;
  pdf_filename: string;
  pdf_url: string;
  html_preview_url?: string;
  cv_version_id?: number | null;
  cv_sections?: Record<string, any>;
  rendered_html?: string;
  bullet_diffs?: BulletDiffItem[];
  ats_parse_report?: ATSParseReport;
  matched_skills?: string[];
  missing_skills?: string[];
  url_fetched?: boolean;
  url_fetch_warning?: string | null;
  extracted_description_preview?: string;
  persistence_status?: string;
  persistence_error?: string | null;
}> => apiJson('/resumes/generate-edition', { method: 'POST', body: params, errorMessage: 'Failed to generate CV edition' });

export const prepareJobEmailPackage = (
  jobId: number,
  cvLanguage = 'auto'
): Promise<{
  company: string;
  title: string;
  recipient_email: string;
  subject: string;
  cover_letter: string;
  motivational_letter?: string;
  cv_language: string;
  docx_filename: string;
  docx_url: string;
  pdf_filename: string;
  pdf_url: string;
  gmail_draft_saved?: boolean;
  gmail_draft_id?: string | null;
  gmail_drafts_url?: string | null;
  attached_files?: string[];
  draft_mode_used?: string;
  draft_error?: string | null;
}> =>
  apiJson(`/jobs/${jobId}/prepare-email-package?cv_language=${encodeURIComponent(cvLanguage)}`, {
    method: 'POST',
    errorMessage: 'Failed to prepare Gmail application package',
  });

export const auditJob = (params: {
  raw_text?: string;
  job_url?: string;
  variant?: string;
  skills_md_override?: string;
  cv_language?: 'en' | 'ka';
}): Promise<JobAuditResponse> => apiJson('/audit-job', { method: 'POST', body: params, errorMessage: 'Audit failed' });

export const generateAnswers = (params: {
  questions: ScreeningQuestion[];
  job_title?: string;
  company?: string;
  job_description?: string;
  portal?: string;
  variant?: string;
  cv_language?: 'en' | 'ka';
}): Promise<GenerateAnswersResponse> =>
  apiJson('/generate-answers', { method: 'POST', body: params, errorMessage: 'Failed to generate screening answers' });

export const stageApplication = (params: {
  job_url: string;
  variant?: string;
  custom_pdf_filename?: string;
  custom_answers?: Record<string, string>;
  applicant_summary?: string;
  motivation_letter?: string;
  expected_salary?: string;
  start_date?: string;
  bypass_company_gate?: boolean;
  auto_submit?: boolean;
  headless?: boolean;
}): Promise<StageApplicationResponse> =>
  apiJson('/stage-application', { method: 'POST', body: params, errorMessage: 'Staging failed' });

export const fetchApplications = (): Promise<ApplicationItem[]> =>
  apiJson('/applications', { errorMessage: 'Failed to fetch applications' });

export const fetchApplicationAnalytics = (): Promise<{
  total_tracked: number;
  applications_submitted: number;
  awaiting_response: number;
  interviews_received: number;
  offers_received: number;
  rejections: number;
  withdrawn: number;
  response_rate_pct: number;
  interview_conversion_rate_pct: number;
  offer_rate_pct: number;
  by_status: Record<string, number>;
}> => apiJson('/applications/analytics', { errorMessage: 'Failed to fetch tracker analytics' });

export const getExportApplicationsUrl = (format: 'json' | 'csv' = 'csv'): string =>
  `${API_BASE}/applications/export?format=${format}`;

export async function downloadApplicationsExport(format: 'json' | 'csv' = 'csv'): Promise<void> {
  const res = await apiFetch(`${API_BASE}/applications/export?format=${format}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to export applications');
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = `talentflow_applications.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const createApplication = (app: Partial<ApplicationItem>): Promise<ApplicationItem> =>
  apiJson('/applications', { method: 'POST', body: app, errorMessage: 'Failed to create application' });

export const updateApplication = (id: string, update: Partial<ApplicationItem>): Promise<ApplicationItem> =>
  apiJson(`/applications/${id}`, { method: 'PUT', body: update, errorMessage: 'Failed to update application' });

export const deleteApplication = (id: string): Promise<void> =>
  apiVoid(`/applications/${id}`, 'DELETE', 'Failed to delete application');

export const fetchGoogleCalendarStatus = (): Promise<{
  connected: boolean;
  google_oauth_configured: boolean;
  instant_link_ready?: boolean;
  ics_export_ready?: boolean;
  email: string;
  auth_url: string;
}> => apiJson('/applications/calendar/status', { errorMessage: 'Failed to fetch Google Calendar status' });

export const fetchIntegrationsStatus = (): Promise<{
  profile: { uploaded: boolean; full_name: string; primary_role: string; skills_count: number; education_count: number };
  google_calendar: {
    oauth_connected: boolean;
    oauth_configured: boolean;
    instant_link_ready: boolean;
    ics_export_ready: boolean;
    email: string;
    test_event_url: string;
  };
  email: { oauth_connected: boolean; smtp_configured: boolean; eml_fallback_ready: boolean; mode: string };
  ai: { connected: boolean; active_provider: string; active_model: string; mode: string };
  database: { alembic_version: string; integrity_ok: boolean; foreign_key_errors: number };
}> => apiJson('/applications/integrations/status', { errorMessage: 'Failed to fetch integrations status' });

export async function downloadApplicationCalendarIcs(
  appId: string,
  kind: 'interview' | 'followup' = 'interview',
  durationMinutes = 45
): Promise<void> {
  const res = await apiFetch(
    `${API_BASE}/applications/${encodeURIComponent(appId)}/calendar.ics?kind=${encodeURIComponent(kind)}&duration_minutes=${durationMinutes}`
  );
  if (!res.ok) throw new Error('Failed to download .ics calendar invite');
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${kind}_${appId}.ics`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const fetchGoogleOAuthConsentUrl = (): Promise<{ authorization_url: string }> =>
  apiJson('/auth/google/login', { errorMessage: 'Failed to obtain Google OAuth consent URL' });

export const createApplicationCalendarEvent = (
  appId: string,
  payload: {
    interview_date?: string;
    duration_minutes?: number;
    summary?: string;
    description?: string;
    location?: string;
    attendee_email?: string;
  }
): Promise<{
  created_in_google_calendar: boolean;
  oauth_connected: boolean;
  needs_oauth: boolean;
  event_id?: string | null;
  html_link: string;
  google_calendar_template_url: string;
  start_iso: string;
  end_iso: string;
  message: string;
}> =>
  apiJson(`/applications/${appId}/calendar-event`, {
    method: 'POST',
    body: payload,
    errorMessage: 'Failed to schedule interview in Google Calendar',
  });

// --- Authentication & User API ---

export const loginUser = (email: string, password: string): Promise<AuthResponse> =>
  authPost('/auth/login', { email, password }, 'Invalid email or password');

export const registerUser = (email: string, password: string, full_name: string): Promise<AuthResponse> =>
  authPost('/auth/register', { email, password, full_name }, 'Registration failed');

export const sendOtp = (email: string): Promise<{ status: string; delivered: boolean; smtp_configured: boolean; message: string }> =>
  authPost('/auth/send-otp', { email }, 'Failed to send OTP code', false);

export const verifyOtp = (email: string, otp_code: string): Promise<AuthResponse> =>
  authPost('/auth/verify-otp', { email, otp_code }, 'Invalid or expired OTP code');

export async function fetchSmtpStatus(): Promise<{
  smtp_configured: boolean;
  otp_available?: boolean;
  provider?: string;
  can_configure_local_smtp?: boolean;
}> {
  const res = await fetch(`${API_BASE}/auth/smtp-status`);
  return res.ok ? res.json() : { smtp_configured: false, otp_available: false, can_configure_local_smtp: false };
}

export const configureSmtp = (
  gmail_user: string,
  gmail_app_password: string
): Promise<{ status: string; smtp_configured: boolean; sender_masked: string; message: string }> =>
  apiJson('/auth/configure-smtp', {
    method: 'POST',
    body: { gmail_user, gmail_app_password },
    errorMessage: 'Failed to verify Gmail SMTP credentials',
  });

export async function fetchCurrentUser(): Promise<UserProfile> {
  const res = await apiFetch(`${API_BASE}/auth/me`, { headers: { 'Content-Type': 'application/json' } });
  if (!res.ok) {
    const err = new Error(res.status === 401 ? 'Unauthorized' : `Auth check failed (${res.status})`) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export function logoutUser(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include' }).catch(() => {});
}

// --- Admin, Gmail, Interviews, Action Plans, Saved Jobs & Alerts ---

export const fetchAdminUsers = (): Promise<AdminUser[]> =>
  apiJson('/admin/users', { errorMessage: 'Failed to load admin user list' });

export const fetchAdminMetrics = (): Promise<PlatformMetrics> =>
  apiJson('/admin/metrics', { errorMessage: 'Failed to load admin metrics' });

export const updateAdminUser = (userId: number, updates: { is_active?: boolean; is_admin?: boolean }): Promise<AdminUser> =>
  apiJson(`/admin/users/${userId}`, { method: 'PATCH', body: updates, errorMessage: 'Failed to update user' });

export const deactivateAdminUser = (userId: number): Promise<void> =>
  apiVoid(`/admin/users/${userId}`, 'DELETE', 'Failed to deactivate user');

export async function fetchGoogleLoginUrl(): Promise<string> {
  const data = await apiJson<{ authorization_url: string }>('/auth/google/login', { errorMessage: 'Failed to get Google login URL' });
  return data.authorization_url;
}

export const dispatchApplicationEmail = (
  appId: string,
  params: { recipient_email?: string; subject?: string; body_text?: string; mode: 'draft' | 'send' }
): Promise<any> => apiJson(`/applications/${appId}/send-email`, { method: 'POST', body: params, errorMessage: 'Failed to dispatch application email' });

export const prepareInterview = (appId: string, roundType = 'HR_SCREEN'): Promise<InterviewBrief> =>
  apiJson(`/applications/${appId}/prepare-interview`, { method: 'POST', body: { round_type: roundType }, errorMessage: 'Failed to generate interview intelligence' });

export const fetchApplicationInterviews = (appId: string): Promise<any[]> =>
  apiJson(`/applications/${appId}/interviews`, { fallbackValue: [] });

export const updateInterviewNotes = (appId: string, roundId: number, notes: string, status?: string): Promise<any> =>
  apiJson(`/applications/${appId}/interviews/${roundId}`, {
    method: 'PATCH',
    body: { candidate_notes: notes, status },
    errorMessage: 'Failed to save interview notes',
  });

export const fetchActionPlans = (): Promise<SkillActionPlan[]> =>
  apiJson('/action-plans', { errorMessage: 'Failed to load action plans' });

export const generateActionPlans = (): Promise<SkillActionPlan[]> =>
  apiJson('/profile/generate-action-plan', { method: 'POST', errorMessage: 'Failed to generate action plans' });

export const toggleMilestone = (planId: number, milestoneIndex: number): Promise<SkillActionPlan> =>
  apiJson(`/action-plans/${planId}/milestones/${milestoneIndex}`, { method: 'PATCH', errorMessage: 'Failed to toggle milestone' });

export const deleteActionPlan = (planId: number): Promise<void> =>
  apiVoid(`/action-plans/${planId}`, 'DELETE', 'Failed to delete action plan');

export const saveJob = (jobId: number, notes = ''): Promise<{ status: string; saved_id: number; job_posting_id: number }> =>
  apiJson(`/jobs/${jobId}/save`, { method: 'POST', body: { notes }, errorMessage: 'Failed to bookmark job' });

export const unsaveJob = (jobId: number): Promise<{ status: string; job_posting_id: number }> =>
  apiJson(`/jobs/${jobId}/save`, { method: 'DELETE', errorMessage: 'Failed to remove job bookmark' });

export const fetchSavedJobs = (): Promise<{ items: Array<{ saved_id: number; notes: string; saved_at: string; job: DbJobPosting }> }> =>
  apiJson('/jobs/saved', { fallbackValue: { items: [] } });

export const submitJobFeedback = (
  jobId: number,
  action: 'dismiss' | 'irrelevant' | 'restore',
  reason?: string,
  note?: string
): Promise<{ status: string; job_id: number; is_ignored: boolean; reason?: string | null }> =>
  apiJson(`/jobs/${jobId}/feedback`, {
    method: 'POST',
    body: { action, reason, note },
    errorMessage: 'Failed to save job feedback',
  });

export async function fetchSavedSearches(): Promise<SavedSearchItem[]> {
  const data = await apiJson<SavedSearchItem[] | { items?: SavedSearchItem[] }>('/saved-searches', { fallbackValue: [] });
  return Array.isArray(data) ? data : data?.items || [];
}

export async function fetchNotifications(): Promise<NotificationItem[]> {
  const data = await apiJson<NotificationItem[]>('/notifications', { fallbackValue: [] });
  return Array.isArray(data) ? data : [];
}

export const markNotificationRead = (notifId: number): Promise<void> => apiVoid(`/notifications/${notifId}/read`, 'PATCH');

export const createSavedSearch = (name: string, filters: Record<string, any>, notify_on_new = true): Promise<any> =>
  apiJson('/saved-searches', { method: 'POST', body: { name, filters, notify_on_new }, errorMessage: 'Failed to save search preset' });

export const deleteSavedSearch = (searchId: number): Promise<void> => apiVoid(`/saved-searches/${searchId}`, 'DELETE');

// --- Candidate Analytics, Admin AI Observability, CV Studio & B2B Hub ---

export const fetchCandidateAnalytics = (): Promise<CandidateAnalyticsResponse> =>
  apiJson('/analytics/candidate', { errorMessage: 'Failed to load candidate dashboard analytics' });

export const fetchAdminAiMetrics = (): Promise<AIMetricsResponse> =>
  apiJson('/admin/ai-metrics', { errorMessage: 'Failed to load AI telemetry metrics' });

export const fetchCvVersions = (): Promise<{ items: CVVersionItem[] }> =>
  apiJson('/cv-versions', { fallbackValue: { items: [] } });

export const createCvVersion = (payload: {
  title: string;
  target_company?: string;
  target_role?: string;
  edition?: string;
  language?: string;
  blank?: boolean;
  structured_json?: Record<string, any>;
  cover_letter?: string;
  motivational_letter?: string;
}): Promise<CVVersionItem> => apiJson('/cv-versions', { method: 'POST', body: payload, errorMessage: 'Failed to save CV version' });

export const duplicateCvVersion = (versionId: number): Promise<CVVersionItem> =>
  apiJson(`/cv-versions/${versionId}/duplicate`, { method: 'POST', errorMessage: 'Failed to duplicate CV version' });

export const patchCvVersion = (
  versionId: number,
  payload: {
    title?: string;
    target_company?: string;
    target_role?: string;
    language?: string;
    structured_json?: Record<string, any>;
    cover_letter?: string;
    motivational_letter?: string;
  }
): Promise<CVVersionItem> =>
  apiJson(`/cv-versions/${versionId}`, { method: 'PATCH', body: payload, errorMessage: 'Failed to update & re-render CV version' });

export const deleteCvVersion = (versionId: number): Promise<void> =>
  apiVoid(`/cv-versions/${versionId}`, 'DELETE', 'Failed to delete CV version');

export const submitMockInterviewAnswer = (
  appId: string,
  roundId: number,
  questionId: number,
  answerText: string
): Promise<{
  evaluation: import('../types').MockAnswerEvaluation;
  mock_progress: NonNullable<InterviewBrief['mock_progress']>;
}> =>
  apiJson(`/applications/${encodeURIComponent(appId)}/interviews/${roundId}/mock-answer`, {
    method: 'POST',
    body: { question_id: questionId, answer_text: answerText },
    errorMessage: 'Failed to evaluate mock interview answer',
  });

export const deleteInterviewRound = (appId: string, roundId: number): Promise<void> =>
  apiVoid(`/applications/${encodeURIComponent(appId)}/interviews/${roundId}`, 'DELETE', 'Failed to delete interview session');

export const calculateB2BTax = (payload: {
  amount: number;
  currency: 'USD' | 'EUR' | 'GBP' | 'GEL';
  billing_period: 'monthly' | 'hourly' | 'annual';
  hours_per_month?: number;
  custom_fx_to_gel?: number;
  include_pension_for_labor?: boolean;
  transfer_fee_pct?: number;
  ytd_revenue_gel?: number;
}): Promise<B2BTaxCalculatorResponse> =>
  apiJson('/b2b/tax-calculator', { method: 'POST', body: payload, errorMessage: 'Failed to calculate B2B take-home pay' });

export const fetchTimezoneMatrix = (workStartGet = 11, workEndGet = 19): Promise<TimezoneMatrixResponse> =>
  apiJson(`/b2b/timezone-matrix?work_start_get=${workStartGet}&work_end_get=${workEndGet}`, {
    errorMessage: 'Failed to load timezone overlap matrix',
  });

export const generateB2BProposal = (payload: {
  target_role: string;
  target_company: string;
  client_region: string;
  contract_rate?: string;
  requirements_snippet?: string;
  language: 'en' | 'ka';
}): Promise<B2BProposalResponse> =>
  apiJson('/b2b/proposal', { method: 'POST', body: payload, errorMessage: 'Failed to generate B2B proposal' });

export const fetchB2BFxRates = (): Promise<B2BFxRatesResponse> =>
  apiJson('/b2b/fx-rates', { errorMessage: 'Failed to fetch GEL exchange rates' });

export const generateB2BInvoice = (payload: {
  client_name: string;
  client_address?: string;
  service_description: string;
  amount: number;
  currency: 'USD' | 'EUR' | 'GBP' | 'GEL';
  invoice_number?: string;
  payment_method: string;
  iban_or_account?: string;
  language: 'en' | 'ka';
}): Promise<B2BInvoiceResponse> =>
  apiJson('/b2b/invoice-preview', { method: 'POST', body: payload, errorMessage: 'Failed to generate B2B invoice' });
