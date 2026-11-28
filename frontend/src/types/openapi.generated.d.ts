/* eslint-disable */
// AUTO-GENERATED from FastAPI OpenAPI schema by backend/scripts/generate_openapi_types.py
// Do not hand-edit; re-run the generator after backend Pydantic contract changes.

export type ApiEndpointPath =
  | '/'
  | '/api/action-plans'
  | '/api/action-plans/add-skill'
  | '/api/action-plans/{plan_id}'
  | '/api/action-plans/{plan_id}/milestones/{milestone_index}'
  | '/api/admin/ai-metrics'
  | '/api/admin/backup'
  | '/api/admin/backups'
  | '/api/admin/metrics'
  | '/api/admin/users'
  | '/api/admin/users/{user_id}'
  | '/api/analytics/candidate'
  | '/api/answers/solve-screening'
  | '/api/applications'
  | '/api/applications/analytics'
  | '/api/applications/calendar/status'
  | '/api/applications/export'
  | '/api/applications/gmail/sync-suggestions'
  | '/api/applications/integrations/status'
  | '/api/applications/{app_id}'
  | '/api/applications/{app_id}/apply-status-suggestion'
  | '/api/applications/{app_id}/calendar-event'
  | '/api/applications/{app_id}/calendar.ics'
  | '/api/applications/{app_id}/events'
  | '/api/applications/{app_id}/follow-up-draft'
  | '/api/applications/{app_id}/interviews'
  | '/api/applications/{app_id}/interviews/{round_id}'
  | '/api/applications/{app_id}/interviews/{round_id}/mock-answer'
  | '/api/applications/{app_id}/interviews/{round_id}/notes'
  | '/api/applications/{app_id}/prepare-interview'
  | '/api/applications/{app_id}/send-email'
  | '/api/audit-job'
  | '/api/auth/configure-smtp'
  | '/api/auth/email-status'
  | '/api/auth/google/callback'
  | '/api/auth/google/login'
  | '/api/auth/login'
  | '/api/auth/logout'
  | '/api/auth/me'
  | '/api/auth/refresh'
  | '/api/auth/register'
  | '/api/auth/request-otp'
  | '/api/auth/send-otp'
  | '/api/auth/smtp-status'
  | '/api/auth/verify-otp'
  | '/api/b2b/fx-rates'
  | '/api/b2b/invoice-preview'
  | '/api/b2b/proposal'
  | '/api/b2b/tax-calculator'
  | '/api/b2b/timezone-matrix'
  | '/api/cv-versions'
  | '/api/cv-versions/{version_id}'
  | '/api/cv-versions/{version_id}/ats-check'
  | '/api/cv-versions/{version_id}/duplicate'
  | '/api/extension/check-url'
  | '/api/extension/download-cv/{filename}'
  | '/api/extension/log-application'
  | '/api/extension/prepare-application'
  | '/api/extension/prepare-gmail-draft'
  | '/api/extension/profile'
  | '/api/extension/upload-skills'
  | '/api/generate-answers'
  | '/api/ground-truth'
  | '/api/health'
  | '/api/health/live'
  | '/api/health/ready'
  | '/api/jobs'
  | '/api/jobs/saved'
  | '/api/jobs/scrape/async'
  | '/api/jobs/scrape/status/{task_id}'
  | '/api/jobs/sources/health'
  | '/api/jobs/{job_id}/feedback'
  | '/api/jobs/{job_id}/prepare-email-package'
  | '/api/jobs/{job_id}/save'
  | '/api/metrics'
  | '/api/notifications'
  | '/api/notifications/{notif_id}/read'
  | '/api/profile'
  | '/api/profile/generate-action-plan'
  | '/api/profile/import-apply'
  | '/api/profile/import-preview'
  | '/api/profile/intelligence'
  | '/api/profile/upload-skills'
  | '/api/resumes/generate-edition'
  | '/api/resumes/generated'
  | '/api/resumes/generated/{filename}'
  | '/api/resumes/my-cvs'
  | '/api/resumes/my-cvs/upload'
  | '/api/resumes/my-cvs/{filename}'
  | '/api/resumes/user/{filename}'
  | '/api/resumes/{filename}'
  | '/api/salary/estimate'
  | '/api/saved-searches'
  | '/api/saved-searches/send-digest'
  | '/api/saved-searches/{search_id}'
  | '/api/skills-md'
  | '/api/skills-md/preset/{preset_id}'
  | '/api/skills-md/presets'
  | '/api/skills-md/upload'
  | '/api/vacancies'
  | '/health'
  | '/health/live'
  | '/healthz'
  | '/readyz'
;

export interface ActionPlanOut {
  id: number;
  skill_name: string;
  category: string;
  days_to_learn: number;
  milestones: Array<Record<string, unknown>>;
  is_completed: boolean;
  progress_percent?: number;
}

export interface AddSkillPlanRequest {
  skill_name: string;
  target_role?: string | null;
}

export interface AdminUpdateUserRequest {
  is_active?: boolean | null;
  is_admin?: boolean | null;
  full_name?: string | null;
}

export interface AdminUserOut {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  application_count?: number;
  has_gmail_oauth?: boolean;
}

export interface ApplicationCreate {
  company: string;
  role: string;
  portal?: string | null;
  url?: string | null;
  status?: string | null;
  match_score?: number | null;
  ats_score?: number | null;
  recruiter_score?: number | null;
  salary_estimate?: string | null;
  salary_expected?: string | null;
  salary_offered?: string | null;
  interview_date?: string | null;
  follow_up_date?: string | null;
  recruiter_name?: string | null;
  recruiter_email?: string | null;
  company_reviews?: number | null;
  cv_pdf_url?: string | null;
  cv_version_id?: number | null;
  cover_letter_text?: string | null;
  variant_used?: string | null;
  applied_date?: string | null;
  outcome?: string | null;
  notes?: string | null;
}

export interface ApplicationItem {
  id: string;
  user_id?: number | null;
  company: string;
  role: string;
  portal?: string | null;
  url: string;
  status?: string;
  match_score?: number | null;
  ats_score?: number | null;
  recruiter_score?: number | null;
  salary_estimate?: string | null;
  salary_expected?: string | null;
  salary_offered?: string | null;
  interview_date?: string | null;
  follow_up_date?: string | null;
  recruiter_name?: string | null;
  recruiter_email?: string | null;
  company_reviews?: number | null;
  jd_snapshot?: Record<string, unknown> | null;
  cv_pdf_url?: string | null;
  cv_version_id?: number | null;
  cover_letter_text?: string | null;
  variant_used?: string | null;
  applied_date?: string | null;
  outcome?: string | null;
  notes?: string | null;
}

export interface ApplicationUpdate {
  company?: string | null;
  role?: string | null;
  portal?: string | null;
  url?: string | null;
  status?: string | null;
  match_score?: number | null;
  ats_score?: number | null;
  recruiter_score?: number | null;
  salary_estimate?: string | null;
  salary_expected?: string | null;
  salary_offered?: string | null;
  interview_date?: string | null;
  follow_up_date?: string | null;
  recruiter_name?: string | null;
  recruiter_email?: string | null;
  company_reviews?: number | null;
  cv_pdf_url?: string | null;
  cv_version_id?: number | null;
  cover_letter_text?: string | null;
  variant_used?: string | null;
  applied_date?: string | null;
  outcome?: string | null;
  notes?: string | null;
}

export interface ApplyStatusSuggestionRequest {
  suggested_status: string;
  reason?: string | null;
}

export interface AuthResponse {
  access_token: string;
  refresh_token?: string | null;
  token_type?: string;
  user: UserOut;
}

export interface B2BInvoiceRequest {
  client_name: string;
  client_address?: string | null;
  service_description: string;
  amount: number;
  currency?: string;
  invoice_number?: string | null;
  payment_method?: string;
  iban_or_account?: string | null;
  language?: string;
}

export interface B2BProposalRequest {
  target_role: string;
  target_company: string;
  client_region?: string;
  contract_rate?: string | null;
  requirements_snippet?: string | null;
  language?: string;
}

export interface Blocker {
  category: string;
  severity: string;
  description: string;
  candidate_status: string;
}

export interface Body_preview_profile_import_api_profile_import_preview_post {
  file: string;
}

export interface Body_upload_personal_cv_api_resumes_my_cvs_upload_post {
  file: string;
  parse_into_profile?: boolean;
}

export interface Body_upload_skills_md_file_api_skills_md_upload_post {
  file: string;
}

export interface Body_upload_skills_profile_api_profile_upload_skills_post {
  file?: string | null;
  content?: string | null;
  run_live_scrape?: boolean;
}

export interface CVVersionCreateRequest {
  title: string;
  target_company?: string;
  target_role?: string;
  edition?: string;
  language?: string;
  blank?: boolean;
  job_posting_id?: number | null;
  structured_json?: Record<string, unknown>;
  cover_letter?: string | null;
  motivational_letter?: string | null;
}

export interface CVVersionPatchRequest {
  title?: string | null;
  target_company?: string | null;
  target_role?: string | null;
  structured_json?: Record<string, unknown> | null;
  cover_letter?: string | null;
  motivational_letter?: string | null;
  language?: string | null;
  edition?: string | null;
}

export interface CalendarEventRequest {
  interview_date?: string | null;
  duration_minutes?: number;
  summary?: string | null;
  description?: string | null;
  location?: string | null;
  attendee_email?: string | null;
}

export interface CompanyValidation {
  company_name: string;
  reputation?: string;
  review_count?: number;
  reviews_count?: number;
  rating?: number | null;
  is_blacklisted?: boolean;
  passed_gate?: boolean;
  portals_checked?: Array<string>;
  source_urls?: Array<string>;
  retrieved_at?: string | null;
  verification_status?: string;
  verdict: string;
  pros?: Array<string>;
  cons?: Array<string>;
}

export interface ConfigureSmtpRequest {
  gmail_user: string;
  gmail_app_password: string;
}

export interface CreateInterviewReflectionRequest {
  note_type?: string;
  content?: string;
  stage?: string;
  interviewer_names?: string;
  questions_asked?: Array<string>;
  what_went_well?: string;
  what_to_improve?: string;
  follow_up_items?: string;
}

export interface FieldAnswerItem {
  field_id: string;
  label: string;
  field_type: string;
  value: string;
  confidence?: number;
  source?: string;
}

export interface FollowUpDraftRequest {
  days_since_applied?: number;
  language?: string;
  save_to_gmail?: boolean;
}

export interface FormFieldSchema {
  field_id: string;
  name?: string | null;
  label?: string;
  field_type?: string;
  placeholder?: string | null;
  required?: boolean;
  options?: Array<string>;
}

export interface GapItem {
  skill_or_area: string;
  severity?: string;
  gap_description: string;
  bridge_strategy: string;
}

export interface GenerateAnswersRequest {
  questions: Array<ScreeningQuestion>;
  job_title?: string | null;
  company?: string | null;
  job_description?: string | null;
  portal?: string | null;
  variant?: string | null;
  cv_language?: string | null;
}

export interface GenerateAnswersResponse {
  answers: Array<ScreeningAnswer>;
  variant_used: string;
  candidate_name: string;
  applicant_summary: string;
  motivation_letter: string;
  dou_motivational_letter: string;
  default_start_date?: string;
}

export interface GenerateEditionRequest {
  edition?: string;
  target_role?: string | null;
  target_company?: string | null;
  job_description?: string | null;
  job_url?: string | null;
  cv_language?: string;
}

export interface GmailSyncRequest {
  messages?: Array<Record<string, unknown>> | null;
  max_results?: number;
}

export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}

export interface JobAuditRequest {
  raw_text?: string | null;
  job_url?: string | null;
  variant?: string | null;
  cv_language?: string | null;
  skills_md_override?: string | null;
}

export interface JobAuditResponse {
  job_details: JobDetails;
  match_score: number;
  score_breakdown: ScoreBreakdown;
  matched_skills: Array<string>;
  missing_skills: Array<string>;
  gaps: Array<GapItem>;
  company_validation: CompanyValidation;
  tailored_cv: TailoredCVResult;
  blockers: Array<Blocker>;
  recommended_variant: string;
  recommendation_notes: string;
  data_provenance?: Record<string, unknown>;
}

export interface JobDetails {
  title: string;
  company?: string;
  portal?: string;
  industry?: string;
  market?: string;
  experience_years_required?: number | null;
  required_skills?: Array<string>;
  nice_to_have_skills?: Array<string>;
  visa_requirements?: string | null;
  language_requirements?: Array<string>;
  location?: string;
  remote_policy?: string;
  salary_range?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  salary_estimated_by_ai?: boolean;
  extraction_failed?: boolean;
  summary?: string;
}

export interface JobFeedbackRequest {
  action?: string;
  reason?: string | null;
  note?: string | null;
}

export interface LogApplicationRequest {
  company_name: string;
  job_title: string;
  job_url: string;
  portal?: string;
  salary_offered?: string | null;
  cv_pdf_path?: string | null;
  cover_letter_text?: string | null;
  status?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface MockInterviewAnswerRequest {
  question_id: number;
  answer_text: string;
}

export interface NotificationOut {
  id: number;
  user_id: number;
  job_posting_id?: number | null;
  saved_search_id?: number | null;
  title: string;
  message: string;
  notification_type: string;
  is_read: boolean;
  created_at: string;
}

export interface PlatformMetricsOut {
  total_users: number;
  active_users: number;
  admin_users: number;
  total_tracked_applications: number;
  applications_by_status: Record<string, unknown>;
  interview_conversion_rate: number;
  total_discovered_jobs: number;
  gemini_api_status: string;
  database_status?: string;
}

export interface PortalVacancyItem {
  id: string;
  title: string;
  company: string;
  portal: string;
  industry?: string;
  location: string;
  salary: string;
  url: string;
  company_reviews_count?: number | null;
  company_rating?: number | null;
  verification_status?: string;
  requires_motivational_letter?: boolean;
  description: string;
}

export interface PrepareApplicationRequest {
  url: string;
  portal?: string | null;
  job_title?: string | null;
  company_name?: string | null;
  location?: string | null;
  job_description?: string | null;
  raw_page_text?: string | null;
  cv_language?: string | null;
  fields?: Array<FormFieldSchema>;
}

export interface PrepareApplicationResponse {
  status?: string;
  portal: string;
  job_title: string;
  company_name: string;
  extraction_failed?: boolean;
  match_score: number;
  match_tier: string;
  seniority_warning?: string | null;
  seniority_blocked?: boolean;
  matched_skills?: Array<string>;
  missing_skills?: Array<string>;
  match_explanation?: Array<Record<string, unknown>>;
  salary_info: Record<string, unknown>;
  company_intel: Record<string, unknown>;
  tailored_cv: Record<string, unknown>;
  cover_letter: string;
  motivational_letter?: string;
  applicant_summary: string;
  field_answers?: Array<FieldAnswerItem>;
}

export interface PrepareGmailDraftRequest {
  recipient_email: string;
  company_name: string;
  job_title: string;
  job_url: string;
  portal?: string;
  cover_letter?: string;
  pdf_filename?: string | null;
  docx_filename?: string | null;
  salary_offered?: string | null;
  mark_applied?: boolean;
}

export interface PrepareInterviewRequest {
  round_type?: string;
}

export interface ProfileImportApplyRequest {
  filename?: string;
  extracted: Record<string, unknown>;
  section_modes?: Record<string, unknown>;
}

export interface RefreshTokenRequest {
  refresh_token?: string | null;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string;
}

export interface SalaryEstimateRequest {
  title: string;
  description: string;
  market?: string;
  portal?: string;
}

export interface SavedSearchCreate {
  name: string;
  filters?: Record<string, unknown>;
  notify_on_new?: boolean;
}

export interface SavedSearchDigestRequest {
  channels?: Array<string>;
  telegram_chat_id?: string | null;
  min_score?: number | null;
  dry_run?: boolean;
}

export interface SavedSearchOut {
  id: number;
  user_id: number;
  name: string;
  filters: Record<string, unknown>;
  notify_on_new: boolean;
  last_run_at?: string | null;
  created_at: string;
}

export interface ScoreBreakdown {
  skills_match: number;
  ats_match: number;
  recruiter_match: number;
  experience_match: number;
  seniority_match?: number;
  education_match?: number;
  location_remote_match?: number;
  visa_match: number;
  language_match: number;
  salary_compatibility?: string;
}

export interface ScrapeRequest {
  portals?: Array<string> | null;
  allow_network?: boolean;
}

export interface ScreeningAnswer {
  question: string;
  field_type?: string;
  answer: string;
  confidence?: number;
  source_ground_truth_field?: string | null;
  verification_status?: string;
}

export interface ScreeningQuestion {
  id?: string | null;
  question: string;
  field_type?: string | null;
  options?: Array<string> | null;
}

export interface SendEmailRequest {
  recipient_email?: string | null;
  subject?: string | null;
  body_text?: string | null;
  mode?: string;
}

export interface SendOTPRequest {
  email: string;
}

export interface SkillsMdPayload {
  content: string;
}

export interface TailoredCVResult {
  pdf_filename: string;
  pdf_url: string;
  docx_filename?: string | null;
  docx_url?: string | null;
  html_preview_url?: string | null;
  cv_language?: string;
  candidate_name?: string;
  target_role?: string;
  human_tone_summary: string;
  applicant_summary: string;
  motivation_statement: string;
  dou_motivational_letter: string;
  tailored_highlights: Array<string>;
  ats_keywords_covered: Array<string>;
  start_date_default?: string | null;
  expected_salary?: string | null;
  document_id?: number | null;
  version_number?: number;
  bullet_diffs?: Array<Record<string, unknown>>;
  ats_parse_report?: Record<string, unknown>;
}

export interface TaxCalculatorRequest {
  amount: number;
  currency?: string;
  billing_period?: string;
  hours_per_month?: number;
  custom_fx_to_gel?: number | null;
  include_pension_for_labor?: boolean;
  transfer_fee_pct?: number;
  ytd_revenue_gel?: number;
}

export interface TrackerAnalyticsResponse {
  total_tracked: number;
  applications_submitted: number;
  awaiting_response: number;
  interviews_received: number;
  offers_received: number;
  rejections: number;
  withdrawn: number;
  follow_ups_due?: number;
  response_rate_pct: number;
  interview_conversion_rate_pct: number;
  offer_rate_pct: number;
  by_status: Record<string, unknown>;
  by_portal: Record<string, unknown>;
  by_role: Record<string, unknown>;
  by_cv_version?: Record<string, unknown>;
}

export interface UpdateInterviewNotesRequest {
  candidate_notes?: string | null;
  status?: string | null;
}

export interface UserOut {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
  has_gmail_oauth?: boolean;
}

export interface ValidationError {
  loc: Array<string | number>;
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface VerifyOTPRequest {
  email: string;
  otp_code: string;
}
