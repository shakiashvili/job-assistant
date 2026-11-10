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

export function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem('talentflow_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function fetchHealth(): Promise<{ status: string; gemini: { connected: boolean; model: string; mode: string } }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error('Backend offline');
  return res.json();
}

export async function fetchVacancies(): Promise<PortalVacancyItem[]> {
  const res = await fetch(`${API_BASE}/vacancies`);
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
  const res = await fetch(`${API_BASE}/skills-md/preset/${presetId}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to apply skills preset');
  return res.json();
}

export async function saveSkillsMdText(content: string): Promise<{ status: string; message: string; extracted_skills: string[]; ground_truth: GroundTruth }> {
  const res = await fetch(`${API_BASE}/skills-md`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  const res = await fetch(`${API_BASE}/profile/upload-skills`, {
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
  raw_markdown: string;
  parsed_skills: ParsedSkillsTaxonomy;
  updated_at: string;
}> {
  const res = await fetch(`${API_BASE}/profile`);
  if (!res.ok) throw new Error('Failed to load CandidateProfile from DB');
  return res.json();
}

export async function fetchScrapedJobs(statusFilter?: string): Promise<DbJobPosting[]> {
  const qs = statusFilter && statusFilter !== 'ALL' ? `?status=${encodeURIComponent(statusFilter)}` : '';
  const res = await fetch(`${API_BASE}/jobs${qs}`);
  if (!res.ok) return [];
  return res.json();
}

export async function triggerMultiPortalScrape(allowNetwork = false): Promise<{
  total_processed: number;
  staged_ready_count: number;
  filtered_out_count: number;
  jobs: DbJobPosting[];
}> {
  const res = await fetch(`${API_BASE}/jobs/scrape`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ allow_network: allowNetwork }),
  });
  if (!res.ok) throw new Error('Scraper run failed');
  return res.json();
}

export async function fetchGeneratedResumes(): Promise<Array<{ filename: string; url: string; html_url?: string | null; size_kb: number }>> {
  const res = await fetch(`${API_BASE}/resumes/generated`);
  if (!res.ok) return [];
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
  const res = await fetch(`${API_BASE}/applications/${id}`, {
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
  localStorage.setItem('talentflow_token', data.access_token);
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
  localStorage.setItem('talentflow_token', data.access_token);
  return data;
}

export async function fetchCurrentUser(): Promise<UserProfile> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Unauthorized');
  return res.json();
}

export function logoutUser(): void {
  localStorage.removeItem('talentflow_token');
}

// --- Dedicated Admin API ---

export async function fetchAdminUsers(): Promise<AdminUser[]> {
  const res = await fetch(`${API_BASE}/admin/users`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to load admin user list');
  return res.json();
}

export async function fetchAdminMetrics(): Promise<PlatformMetrics> {
  const res = await fetch(`${API_BASE}/admin/metrics`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to load admin metrics');
  return res.json();
}

export async function updateAdminUser(userId: number, updates: { is_active?: boolean; is_admin?: boolean }): Promise<AdminUser> {
  const res = await fetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error('Failed to update user');
  return res.json();
}

export async function deactivateAdminUser(userId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
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
  const res = await fetch(`${API_BASE}/applications/${appId}/send-email`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('Failed to dispatch application email');
  return res.json();
}

// --- Interview Preparation Copilot API ---

export async function prepareInterview(appId: string, roundType: string = 'HR_SCREEN'): Promise<InterviewBrief> {
  const res = await fetch(`${API_BASE}/applications/${appId}/prepare-interview`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ round_type: roundType }),
  });
  if (!res.ok) throw new Error('Failed to generate interview intelligence');
  return res.json();
}

export async function fetchApplicationInterviews(appId: string): Promise<any[]> {
  const res = await fetch(`${API_BASE}/applications/${appId}/interviews`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function updateInterviewNotes(appId: string, roundId: number, notes: string, status?: string): Promise<any> {
  const res = await fetch(`${API_BASE}/applications/${appId}/interviews/${roundId}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
    body: JSON.stringify({ candidate_notes: notes, status }),
  });
  if (!res.ok) throw new Error('Failed to save interview notes');
  return res.json();
}

// --- Skill Gap Action Plans API ---

export async function fetchActionPlans(): Promise<SkillActionPlan[]> {
  const res = await fetch(`${API_BASE}/action-plans`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to load action plans');
  return res.json();
}

export async function generateActionPlans(): Promise<SkillActionPlan[]> {
  const res = await fetch(`${API_BASE}/profile/generate-action-plan`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to generate action plans');
  return res.json();
}

export async function toggleMilestone(planId: number, milestoneIndex: number): Promise<SkillActionPlan> {
  const res = await fetch(`${API_BASE}/action-plans/${planId}/milestones/${milestoneIndex}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to toggle milestone');
  return res.json();
}

export async function deleteActionPlan(planId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/action-plans/${planId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to delete action plan');
}

