export interface CandidateLocation {
  city: string;
  country: string;
  postal_code?: string;
  address_line?: string;
  timezone?: string;
  open_to_relocation: boolean;
  remote_preference: string;
}

export interface CandidateLinks {
  linkedin: string;
  github: string;
  portfolio: string;
  twitter?: string;
}

export interface CandidateWorkAuth {
  citizenship: string[];
  eu_work_permit: boolean;
  requires_eu_visa: boolean;
  us_work_authorization: string;
  requires_us_visa_sponsorship: boolean;
  uk_work_authorization: string;
  security_clearance: boolean;
}

export interface CandidateLanguage {
  language: string;
  proficiency: string;
}

export interface CandidateCompensation {
  expected_salary_eur: number;
  min_salary_eur: number;
  expected_salary_usd: number;
  notice_period: string;
}

export interface WorkHistoryItem {
  company: string;
  role: string;
  location: string;
  start_date: string;
  end_date: string;
  highlights: string[];
}

export interface EducationItem {
  degree: string;
  institution: string;
  location?: string;
  dates?: string;
  graduation_year?: number;
  gpa?: string;
  modules?: string[];
  focus?: string;
  field_of_study?: string;
  start_year?: string;
  end_year?: string;
}

export interface ProjectItem {
  title: string;
  organization?: string;
  dates?: string;
  highlights: string[];
}

export interface CVVariant {
  id: string;
  title: string;
  summary: string;
  keywords: string[];
  resume_file: string;
}

export interface FAQItem {
  question_trigger: string;
  tags: string[];
  answer: string;
}

export interface GroundTruth {
  candidate: {
    first_name: string;
    last_name: string;
    full_name: string;
    headline: string;
    email: string;
    phone: string;
    location: CandidateLocation;
    links: CandidateLinks;
    work_authorization: CandidateWorkAuth;
    languages: CandidateLanguage[];
    compensation: CandidateCompensation;
  };
  skills: {
    core: string[];
    secondary: string[];
    by_category?: Record<string, string[]>;
  };
  work_history: WorkHistoryItem[];
  education: EducationItem[];
  projects?: ProjectItem[];
  certifications?: string[];
  cv_variants: Record<string, CVVariant>;
  faq_bank: FAQItem[];
  skills_md_raw?: string;
}

export interface GoogleCalendarStatus {
  connected: boolean;
  google_oauth_configured: boolean;
  email: string;
  auth_url: string;
}

export interface GoogleCalendarEventResponse {
  created_in_google_calendar: boolean;
  oauth_connected: boolean;
  needs_oauth: boolean;
  event_id?: string | null;
  html_link: string;
  google_calendar_template_url: string;
  start_iso: string;
  end_iso: string;
  message: string;
}

export interface JobDetails {
  title: string;
  company: string;
  portal?: string;
  industry?: string;
  market?: string;
  experience_years_required: number | null;
  required_skills: string[];
  nice_to_have_skills: string[];
  visa_requirements: string | null;
  language_requirements: string[];
  location: string | null;
  remote_policy: string | null;
  salary_range?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  salary_estimated_by_ai?: boolean;
  summary: string;
}

export interface DbJobPosting {
  id: number;
  portal: string;
  external_id: string;
  title: string;
  company: string;
  url: string;
  market: 'GE' | 'UA_REMOTE' | 'INT_REMOTE' | string;
  is_remote: boolean;
  language_requirements: string[];
  description_raw: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_estimated_by_ai: boolean;
  salary_source?: 'verified' | 'ai_estimated' | 'missing' | string;
  posting_date?: string | null;
  published_at?: string | null;
  suitability_score: number;
  match_rationale: string;
  match_tier?: 'DIRECT' | 'ADJACENT' | 'PUBLIC_INTERNSHIP' | string;
  adjacent_role_tag?: string | null;
  skill_overlap_pct?: number | null;
  status: 'DISCOVERED' | 'FILTERED_OUT' | 'AUDITED' | 'STAGED' | 'APPLIED' | 'REJECTED' | string;
  deadline_text?: string | null;
  is_link_live?: boolean;
  delivery_channel?: string | null;
  target_email?: string | null;
  email_subject?: string | null;
  scraped_at: string;
  contract_mode?: 'GE_LOCAL' | 'REMOTE_B2B' | 'REGION_LOCKED' | string;
  georgia_eligible?: boolean;
  b2b_ready?: boolean;
  eligibility_note?: string;
}

export interface ParsedSkillsTaxonomy {
  qa_automation: string[];
  manual_qa: string[];
  languages: string[];
  api_and_performance: string[];
  cicd_and_devops: string[];
  tools: string[];
  frameworks: string[];
  years_of_experience: number;
  all_skills: string[];
  education?: Array<{
    degree?: string;
    field_of_study?: string;
    institution?: string;
    graduation_year?: number | null;
    is_student_or_recent_grad?: boolean;
  }>;
  courses_and_certifications?: string[];
  eligible_internships?: boolean;
  internship_tracks?: string[];
}

export interface PaginatedJobsResponse {
  items: DbJobPosting[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  tier_counts?: {
    ALL: number;
    DIRECT: number;
    ADJACENT: number;
    PUBLIC_INTERNSHIP: number;
  };
  status_counts?: {
    ALL: number;
    STAGED: number;
    AUDITED: number;
  };
}

export interface GapItem {
  skill_or_area: string;
  severity: 'high' | 'moderate' | 'low' | string;
  gap_description: string;
  bridge_strategy: string;
}

export interface CompanyValidation {
  company_name: string;
  reputation?: 'VERIFIED' | 'UNVERIFIED' | 'BLACKLISTED' | string;
  review_count: number;
  reviews_count?: number;
  rating: number | null;
  is_blacklisted?: boolean;
  passed_gate: boolean;
  portals_checked: string[];
  verdict: string;
  pros: string[];
  cons: string[];
}

export interface BulletDiffItem {
  source_bullet_id: string;
  company: string;
  role: string;
  original_text: string;
  tailored_text: string;
  action: 'preserved' | 'prioritized' | 'translated_ka' | string;
  matched_keywords?: string[];
  verified_source?: boolean;
}

export interface ATSParseReport {
  audit_label?: string;
  status: 'PASS' | 'WARN' | 'FAIL' | string;
  score: number;
  page_count: number;
  selectable_text_ok: boolean;
  extracted_char_count: number;
  candidate_name_present?: boolean;
  contact_present?: boolean;
  mojibake_free?: boolean;
  layout_check_performed?: boolean;
  single_column_layout_ok?: boolean;
  sections_detected?: string[];
  keywords_extracted?: string[];
  warnings?: string[];
}

export interface TailoredCVResult {
  pdf_filename: string;
  pdf_url: string;
  docx_filename?: string;
  docx_url?: string;
  html_preview_url?: string;
  cv_language?: 'en' | 'ka' | string;
  candidate_name?: string;
  target_role?: string;
  human_tone_summary: string;
  applicant_summary: string;
  motivation_statement: string;
  cover_letter?: string;
  dou_motivational_letter: string;
  cv_sections?: Record<string, any>;
  rendered_html?: string;
  tailored_highlights: string[];
  ats_keywords_covered: string[];
  bullet_diffs?: BulletDiffItem[];
  ats_parse_report?: ATSParseReport;
  start_date_default: string;
  expected_salary: string;
}

export interface Blocker {
  category: string;
  severity: 'critical' | 'warning' | 'info';
  description: string;
  candidate_status: string;
}

export interface ScoreBreakdown {
  skills_match: number;
  ats_match: number;
  recruiter_match: number;
  experience_match: number;
  visa_match: number;
  language_match: number;
}

export interface JobAuditResponse {
  job_details: JobDetails;
  match_score: number;
  score_breakdown: ScoreBreakdown;
  matched_skills: string[];
  missing_skills: string[];
  gaps: GapItem[];
  company_validation: CompanyValidation;
  tailored_cv: TailoredCVResult;
  blockers: Blocker[];
  recommended_variant: string;
  recommendation_notes: string;
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
  company_reviews_count: number;
  company_rating: number;
  requires_motivational_letter: boolean;
  description: string;
}

export interface SkillsPresetItem {
  id: string;
  label: string;
  role: string;
  content: string;
}

export interface ScreeningQuestion {
  id?: string;
  question: string;
  field_type?: string;
  options?: string[];
}

export interface ScreeningAnswer {
  question: string;
  field_type: string;
  answer: string;
  confidence: number;
  source_ground_truth_field?: string;
}

export interface GenerateAnswersResponse {
  answers: ScreeningAnswer[];
  variant_used: string;
  candidate_name: string;
  applicant_summary?: string;
  motivation_letter?: string;
  dou_motivational_letter?: string;
  default_start_date?: string;
}

export interface StageApplicationResponse {
  status: string;
  portal_detected: string;
  fields_filled: string[];
  captcha_status?: string;
  file_uploaded: boolean;
  resume_file_path?: string;
  company_validation?: CompanyValidation;
  message: string;
  manual_review_needed: boolean;
  page_title?: string;
}

export interface ApplicationItem {
  id: string;
  company: string;
  role: string;
  portal?: string;
  url: string;
  status: 'Discovered' | 'Applied' | 'HR Screening' | 'Technical Interview' | 'Offer / Rejected' | string;
  match_score?: number;
  ats_score?: number;
  recruiter_score?: number;
  salary_estimate?: string | null;
  interview_date?: string | null;
  company_reviews?: number;
  cv_pdf_url?: string;
  variant_used?: string;
  applied_date?: string | null;
  notes?: string | null;
}

export interface UserProfile {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
  has_gmail_oauth: boolean;
}

export interface AuthResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
  user: UserProfile;
}

export interface MilestoneLink {
  title: string;
  channel?: string;
  source?: string;
  url: string;
}

export interface Milestone {
  day: number;
  task: string;
  completed: boolean;
  resource_url?: string;
  tutorial_url?: string;
  youtube_videos?: MilestoneLink[];
  blog_posts?: MilestoneLink[];
}

export interface SkillActionPlan {
  id: number;
  skill_name: string;
  category: string;
  days_to_learn: number;
  milestones: Milestone[];
  is_completed: boolean;
  progress_percent: number;
}

export interface StarStrategy {
  situation: string;
  task: string;
  action: string;
  result: string;
}

export interface PredictedQuestion {
  id: number;
  category: 'Technical' | 'Behavioral' | 'Scenario' | string;
  question: string;
  star_strategy: StarStrategy;
}

export interface InterviewBrief {
  round_id: number;
  application_id: number;
  company_name: string;
  job_title: string;
  round_type: string;
  status: string;
  company_intel: string;
  predicted_questions: PredictedQuestion[];
  candidate_notes: string;
}

export interface PlatformMetrics {
  total_users: number;
  active_users: number;
  admin_users: number;
  total_tracked_applications: number;
  applications_by_status: Record<string, number>;
  interview_conversion_rate: number;
  total_discovered_jobs: number;
  gemini_api_status: string;
  database_status: string;
}

export interface AdminUser {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  application_count: number;
  has_gmail_oauth: boolean;
}

export interface CVVersionItem {
  id: number;
  title: string;
  target_company?: string | null;
  target_role?: string | null;
  edition: string;
  language: string;
  structured_json: Record<string, any>;
  rendered_html?: string;
  pdf_filename?: string | null;
  docx_filename?: string | null;
  pdf_url?: string | null;
  docx_url?: string | null;
  html_preview_url?: string | null;
  version_number: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CandidateAnalyticsResponse {
  profile_uploaded: boolean;
  completeness_score: number;
  missing_fields: string[];
  detected_industry?: string;
  primary_role?: string;
  matching_jobs_count: number;
  remote_b2b_matches_count?: number;
  local_georgia_matches_count?: number;
  ready_to_apply_count?: number;
  tier_breakdown: Record<string, number>;
  saved_jobs_count: number;
  active_applications_count: number;
  applied_count: number;
  interviews_count: number;
  offers_count: number;
  cv_versions_count?: number;
  response_rate_pct: number;
  applications_by_status: Record<string, number>;
  upcoming_interviews: Array<{
    id: number;
    application_id: number;
    round_type: string;
    scheduled_at?: string | null;
    interviewer?: string | null;
  }>;
}

export interface AIMetricsResponse {
  gemini_configured: boolean;
  quality_model: string;
  fast_model: string;
  total_requests: number;
  success_count: number;
  cache_hits: number;
  cache_hit_rate: number;
  active_cache_entries?: number;
  rate_limited_count: number;
  failed_count: number;
  unconfigured_count?: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  prompt_tokens?: number;
  output_tokens?: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  by_task: Record<
    string,
    {
      count: number;
      success: number;
      cache_hits: number;
      errors: number;
      avg_latency_ms: number;
    }
  >;
  recent_logs: Array<{
    id: number;
    task_type: string;
    model_name: string;
    cache_hit: boolean;
    latency_ms: number;
    status: string;
    error_type?: string | null;
    total_tokens?: number | null;
    estimated_cost_usd?: number | null;
    created_at: string;
  }>;
}

export interface B2BTaxCalculatorResponse {
  currency: string;
  fx_to_gel: number;
  fx_source?: string;
  fx_as_of?: string | null;
  monthly_gross_orig: number;
  monthly_gross_gel: number;
  annual_gross_gel: number;
  ytd_revenue_gel?: number;
  actual_cumulative_gel?: number;
  actual_cap_usage_pct?: number;
  cumulative_annual_gel?: number;
  projected_annual_gross_gel?: number;
  projected_cumulative_gel?: number;
  projected_exceeds_500k_cap?: boolean;
  threshold_crossing_month?: number | null;
  projected_annual_tax_gel?: number;
  projected_effective_tax_rate_pct?: number;
  projected_cap_usage_pct?: number;
  under_500k_cap: boolean;
  b2b_small_business: {
    tax_rate_pct: number;
    tax_gel: number;
    transfer_fee_gel: number;
    net_gel: number;
    net_orig: number;
    hourly_net_orig: number;
  };
  standard_labor_contract: {
    pension_gel: number;
    income_tax_gel: number;
    net_gel: number;
    net_orig: number;
  };
  monthly_b2b_advantage_gel: number;
  cap_usage_pct: number;
  notes: string[];
}

export interface TimezoneMatrixResponse {
  base_timezone: string;
  selected_shift_get: string;
  regions: Array<{
    region: string;
    hours_behind_tbilisi: number;
    client_hours_tbilisi_time: string;
    overlap_hours_count: number;
    overlap_window_get: string;
    recommended_shift_get: string;
  }>;
}

export interface B2BProposalResponse {
  subject: string;
  proposal_text: string;
  language: string;
}

export interface B2BFxRatesResponse {
  rates: Record<string, number>;
  source: string;
  as_of?: string | null;
}

export interface B2BInvoiceResponse {
  invoice_number: string;
  currency: string;
  amount: number;
  fx_rate: number;
  fx_source: string;
  gel_equivalent: number;
  estimated_1pct_tax_gel: number;
  invoice_text: string;
}

export interface JobSearchParams {
  page?: number;
  limit?: number;
  portal?: string;
  market?: string;
  status?: string;
  tier?: string;
  min_score?: number;
  include_filtered?: boolean;
  search?: string;
  country?: string;
  city?: string;
  remote_type?: string;
  salary_min?: number;
  language?: string;
  technology?: string;
  experience_level?: string;
  employment_type?: string;
  sort_by?: 'relevance' | 'newest' | 'salary_desc' | 'company_asc' | string;
  posted_within_days?: number;
  only_new?: boolean;
  only_saved?: boolean;
  b2b_only?: boolean;
  geo_eligible_only?: boolean;
}

export interface ScraperSourceHealthItem {
  portal: string;
  status: string;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  jobs_found: number;
  latency_ms: number;
  consecutive_failures: number;
  last_error?: string | null;
}

export interface SavedSearchItem {
  id: number;
  user_id: number;
  name: string;
  filters: Record<string, any>;
  notify_on_new: boolean;
  last_run_at?: string | null;
  created_at: string;
}

export interface NotificationItem {
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

