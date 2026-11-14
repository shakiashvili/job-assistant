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
  PaginatedJobsResponse,
  ParsedSkillsTaxonomy,
  UserProfile,
  AuthResponse,
  SkillActionPlan,
  InterviewBrief,
  PlatformMetrics,
  AdminUser,
} from '../types';

export const BACKEND_ORIGIN = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const API_BASE = `${BACKEND_ORIGIN}/api`;

const ACCESS_TOKEN_KEY = 'talentflow_token';
const REFRESH_TOKEN_KEY = 'talentflow_refresh_token';

function saveAuthTokens(data: AuthResponse): void {
  if (data.access_token) {
    localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
  }
  if (data.refresh_token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
  }
}

export function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

let inFlightRefresh: Promise<boolean> | null = null;

export async function refreshAccessToken(): Promise<boolean> {
  if (inFlightRefresh) return inFlightRefresh;

  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return false;

  inFlightRefresh = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const data: AuthResponse = await res.json();
      saveAuthTokens(data);
      return true;
    } catch {
      return false;
    } finally {
      inFlightRefresh = null;
    }
  })();

  return inFlightRefresh;
}

/**
 * Fetch wrapper with automatic Bearer injection and single-flight 401 refresh retry.
 * Only clears stored tokens and notifies the UI if refresh also fails.
 */
export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const buildHeaders = (withToken: string | null): Headers => {
    const headers = new Headers(init.headers || {});
    if (withToken) {
      headers.set('Authorization', `Bearer ${withToken}`);
    }
    return headers;
  };

  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  let res = await fetch(url, { ...init, headers: buildHeaders(token) });

  if (res.status === 401 && !url.includes('/auth/refresh') && !url.includes('/auth/login')) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      const nextToken = localStorage.getItem(ACCESS_TOKEN_KEY);
      res = await fetch(url, { ...init, headers: buildHeaders(nextToken) });
    } else {
      logoutUser();
      window.dispatchEvent(new Event('talentflow:auth-expired'));
    }
  }

  return res;
}

export async function fetchHealth(): Promise<{ status: string; gemini: { connected: boolean; model: string; mode: string } }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error('Backend offline');
  return res.json();
}

export async function fetchVacancies(): Promise<PortalVacancyItem[]> {
  const res = await apiFetch(`${API_BASE}/vacancies`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch portal vacancies');
  return res.json();
}

export async function fetchGroundTruth(): Promise<GroundTruth> {
  const res = await fetch(`${API_BASE}/ground-truth`);
  if (!res.ok) throw new Error('Failed to fetch ground truth');
  return res.json();
}

export async function saveGroundTruth(data: GroundTruth): Promise<GroundTruth> {
  const res = await fetch(`${API_BASE}/ground-truth`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Failed to update ground truth');
  const json = await res.json();
  return json.data;
}

export async function fetchSkillsMd(): Promise<{ filename: string; content: string; extracted_skills: string[] }> {
  const res = await fetch(`${API_BASE}/skills-md`);
  if (!res.ok) throw new Error('Failed to load skills.md');
  return res.json();
}

export async function fetchSkillsPresets(): Promise<{ presets: SkillsPresetItem[] }> {
  const res = await fetch(`${API_BASE}/skills-md/presets`);
  if (!res.ok) return { presets: [] };
  return res.json();
}

export async function applySkillsPreset(presetId: string): Promise<{
  status: string;
  preset_id: string;
  content: string;
  extracted_skills: string[];
  ground_truth: GroundTruth;
  message: string;
}> {
  const res = await apiFetch(`${API_BASE}/skills-md/preset/${presetId}`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to apply skills preset');
  return res.json();
}

export async function saveSkillsMdText(content: string): Promise<{ status: string; message: string; extracted_skills: string[]; ground_truth: GroundTruth }> {
  const res = await apiFetch(`${API_BASE}/skills-md`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error('Failed to save skills.md');
  return res.json();
}

export async function uploadSkillsMdFile(file: File): Promise<{
  status: string;
  filename: string;
  content: string;
  extracted_skills: string[];
  parsed_skills?: ParsedSkillsTaxonomy;
  message: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await apiFetch(`${API_BASE}/profile/upload-skills`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error('Failed to upload .md file');
  const data = await res.json();
  const allSkills: string[] = data.parsed_skills?.all_skills || [];
  return {
    status: data.status,
    filename: data.filename || file.name,
    content: data.raw_markdown || '',
    extracted_skills: allSkills,
    parsed_skills: data.parsed_skills,
    message: `Uploaded ${file.name} into SQLite CandidateProfile (${allSkills.length} skills indexed)!`,
  };
}

export async function fetchDbProfile(): Promise<{
  id: number;
  profile_uploaded?: boolean;
  raw_markdown: string;
  parsed_skills: ParsedSkillsTaxonomy;
  updated_at: string;
}> {
  const res = await apiFetch(`${API_BASE}/profile`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to load CandidateProfile from DB');
  return res.json();
}

export async function fetchScrapedJobs(params?: {
  page?: number;
  limit?: number;
  portal?: string;
  status?: string;
  min_score?: number;
  tier?: string;
} | string): Promise<PaginatedJobsResponse> {
  const qs = new URLSearchParams();
  if (typeof params === 'string') {
    if (params && params !== 'ALL') qs.set('status', params);
  } else if (params) {
    if (params.page) qs.set('page', String(params.page));
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.portal && params.portal !== 'ALL') qs.set('portal', params.portal);
    if (params.status && params.status !== 'ALL') qs.set('status', params.status);
    if (params.min_score !== undefined) qs.set('min_score', String(params.min_score));
    if (params.tier && params.tier !== 'ALL') qs.set('tier', params.tier);
  }
  const queryStr = qs.toString() ? `?${qs.toString()}` : '';
  const res = await apiFetch(`${API_BASE}/jobs${queryStr}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) return { items: [], total: 0, page: 1, limit: 12, total_pages: 1 };
  const data = await res.json();
  if (Array.isArray(data)) {
    return { items: data, total: data.length, page: 1, limit: data.length || 12, total_pages: 1 };
  }
  return data;
}

export async function triggerMultiPortalScrape(allowNetwork = true): Promise<{
  total_processed: number;
  staged_ready_count: number;
  filtered_out_count: number;
  cache_hits?: number;
  rejection_reasons?: Array<{ portal: string; title: string; company: string; reason: string }>;
  jobs: DbJobPosting[];
}> {
  const res = await apiFetch(`${API_BASE}/jobs/scrape`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ allow_network: allowNetwork }),
  });
  if (!res.ok) throw new Error('Scraper run failed');
  return res.json();
}

export async function fetchGeneratedResumes(): Promise<Array<{ filename: string; url: string; docx_url?: string | null; html_url?: string | null; size_kb: number }>> {
  const res = await fetch(`${API_BASE}/resumes/generated`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchMyCvs(): Promise<Array<{ filename: string; url: string; ext: string; size_kb: number }>> {
  const res = await apiFetch(`${API_BASE}/resumes/my-cvs`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function uploadPersonalCv(file: File): Promise<{ status: string; filename: string; url: string; ext: string; size_kb: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await apiFetch(`${API_BASE}/resumes/my-cvs/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to upload CV' }));
    throw new Error(err.detail || 'Failed to upload CV');
  }
  return res.json();
}

export async function deletePersonalCv(filename: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/resumes/my-cvs/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to delete CV');
}

export async function generateCvEdition(params: {
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
  cv_language: string;
  docx_filename: string;
  docx_url: string;
  pdf_filename: string;
  pdf_url: string;
}> {
  const res = await apiFetch(`${API_BASE}/resumes/generate-edition`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to generate CV edition' }));
    throw new Error(err.detail || 'Failed to generate CV edition');
  }
  return res.json();
}

export async function prepareJobEmailPackage(
  jobId: number,
  cvLanguage: string = 'auto'
): Promise<{
  company: string;
  title: string;
  recipient_email: string;
  subject: string;
  cover_letter: string;
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
}> {
  const res = await apiFetch(`${API_BASE}/jobs/${jobId}/prepare-email-package?cv_language=${encodeURIComponent(cvLanguage)}`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to prepare Gmail application package' }));
    throw new Error(err.detail || 'Failed to prepare Gmail application package');
  }
  return res.json();
}

export async function auditJob(params: {
  raw_text?: string;
  job_url?: string;
  variant?: string;
  skills_md_override?: string;
  cv_language?: 'en' | 'ka';
}): Promise<JobAuditResponse> {
  const res = await fetch(`${API_BASE}/audit-job`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Audit failed' }));
    throw new Error(err.detail || 'Audit failed');
  }
  return res.json();
}

export async function generateAnswers(params: {
  questions: ScreeningQuestion[];
  job_title?: string;
  company?: string;
  job_description?: string;
  portal?: string;
  variant?: string;
  cv_language?: 'en' | 'ka';
}): Promise<GenerateAnswersResponse> {
  const res = await fetch(`${API_BASE}/generate-answers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('Failed to generate screening answers');
  return res.json();
}

export async function stageApplication(params: {
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
}): Promise<StageApplicationResponse> {
  const res = await fetch(`${API_BASE}/stage-application`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Staging failed' }));
    throw new Error(err.detail || 'Staging failed');
  }
  return res.json();
}

export async function fetchApplications(): Promise<ApplicationItem[]> {
  const res = await fetch(`${API_BASE}/applications`);
  if (!res.ok) throw new Error('Failed to fetch applications');
  return res.json();
}

export async function createApplication(app: Partial<ApplicationItem>): Promise<ApplicationItem> {
  const res = await fetch(`${API_BASE}/applications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(app),
  });
  if (!res.ok) throw new Error('Failed to create application');
  return res.json();
}

export async function updateApplication(id: string, update: Partial<ApplicationItem>): Promise<ApplicationItem> {
  const res = await fetch(`${API_BASE}/applications/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  });
  if (!res.ok) throw new Error('Failed to update application');
  return res.json();
}

export async function deleteApplication(id: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/applications/${id}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to delete application');
}

// --- Authentication & User API ---

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(err.detail || 'Invalid email or password');
  }
  const data: AuthResponse = await res.json();
  saveAuthTokens(data);
  return data;
}

export async function registerUser(email: string, password: string, full_name: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, full_name }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
    throw new Error(err.detail || 'Registration failed');
  }
  const data: AuthResponse = await res.json();
  saveAuthTokens(data);
  return data;
}

export async function sendOtp(email: string): Promise<{ status: string; delivered: boolean; smtp_configured: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/auth/send-otp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to send OTP code' }));
    throw new Error(err.detail || 'Failed to send OTP code');
  }
  return res.json();
}

export async function verifyOtp(email: string, otp_code: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/verify-otp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, otp_code }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Invalid or expired OTP code' }));
    throw new Error(err.detail || 'Invalid or expired OTP code');
  }
  const data: AuthResponse = await res.json();
  saveAuthTokens(data);
  return data;
}

export async function fetchSmtpStatus(): Promise<{ smtp_configured: boolean }> {
  const res = await fetch(`${API_BASE}/auth/smtp-status`);
  if (!res.ok) return { smtp_configured: false };
  return res.json();
}

export async function configureSmtp(
  gmail_user: string,
  gmail_app_password: string
): Promise<{ status: string; smtp_configured: boolean; sender_masked: string; message: string }> {
  const res = await apiFetch(`${API_BASE}/auth/configure-smtp`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ gmail_user, gmail_app_password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to verify Gmail SMTP credentials' }));
    throw new Error(err.detail || 'Failed to verify Gmail SMTP credentials');
  }
  return res.json();
}

export async function fetchCurrentUser(): Promise<UserProfile> {
  const res = await apiFetch(`${API_BASE}/auth/me`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error('Unauthorized');
  return res.json();
}

export function logoutUser(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

// --- Dedicated Admin API ---

export async function fetchAdminUsers(): Promise<AdminUser[]> {
  const res = await apiFetch(`${API_BASE}/admin/users`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error('Failed to load admin user list');
  return res.json();
}

export async function fetchAdminMetrics(): Promise<PlatformMetrics> {
  const res = await apiFetch(`${API_BASE}/admin/metrics`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error('Failed to load admin metrics');
  return res.json();
}

export async function updateAdminUser(userId: number, updates: { is_active?: boolean; is_admin?: boolean }): Promise<AdminUser> {
  const res = await apiFetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error('Failed to update user');
  return res.json();
}

export async function deactivateAdminUser(userId: number): Promise<void> {
  const res = await apiFetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error('Failed to deactivate user');
}

// --- Gmail OAuth & Dispatch API ---

export async function fetchGoogleLoginUrl(): Promise<string> {
  const res = await fetch(`${API_BASE}/auth/google/login`);
  if (!res.ok) throw new Error('Failed to get Google login URL');
  const data = await res.json();
  return data.authorization_url;
}

export async function dispatchApplicationEmail(
  appId: string,
  params: { recipient_email?: string; subject?: string; body_text?: string; mode: 'draft' | 'send' }
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/applications/${appId}/send-email`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('Failed to dispatch application email');
  return res.json();
}

// --- Interview Preparation Copilot API ---

export async function prepareInterview(appId: string, roundType: string = 'HR_SCREEN'): Promise<InterviewBrief> {
  const res = await apiFetch(`${API_BASE}/applications/${appId}/prepare-interview`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ round_type: roundType }),
  });
  if (!res.ok) throw new Error('Failed to generate interview intelligence');
  return res.json();
}

export async function fetchApplicationInterviews(appId: string): Promise<any[]> {
  const res = await apiFetch(`${API_BASE}/applications/${appId}/interviews`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function updateInterviewNotes(appId: string, roundId: number, notes: string, status?: string): Promise<any> {
  const res = await apiFetch(`${API_BASE}/applications/${appId}/interviews/${roundId}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
    body: JSON.stringify({ candidate_notes: notes, status }),
  });
  if (!res.ok) throw new Error('Failed to save interview notes');
  return res.json();
}

// --- Skill Gap Action Plans API ---

export async function fetchActionPlans(): Promise<SkillActionPlan[]> {
  const res = await apiFetch(`${API_BASE}/action-plans`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to load action plans');
  return res.json();
}

export async function generateActionPlans(): Promise<SkillActionPlan[]> {
  const res = await apiFetch(`${API_BASE}/profile/generate-action-plan`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to generate action plans');
  return res.json();
}

export async function toggleMilestone(planId: number, milestoneIndex: number): Promise<SkillActionPlan> {
  const res = await apiFetch(`${API_BASE}/action-plans/${planId}/milestones/${milestoneIndex}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to toggle milestone');
  return res.json();
}

export async function deleteActionPlan(planId: number): Promise<void> {
  const res = await apiFetch(`${API_BASE}/action-plans/${planId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to delete action plan');
}

