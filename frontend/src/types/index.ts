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
  graduation_year: number;
  focus: string;
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
  cv_variants: Record<string, CVVariant>;
  faq_bank: FAQItem[];
  skills_md_raw?: string;
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
  suitability_score: number;
  match_rationale: string;
  status: 'DISCOVERED' | 'FILTERED_OUT' | 'AUDITED' | 'STAGED' | 'APPLIED' | 'REJECTED' | string;
  deadline_text?: string | null;
  is_link_live?: boolean;
  delivery_channel?: string | null;
  target_email?: string | null;
  email_subject?: string | null;
  scraped_at: string;
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
  dou_motivational_letter: string;
  tailored_highlights: string[];
  ats_keywords_covered: string[];
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
  mock_url: string;
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
  token_type: string;
  user: UserProfile;
}

export interface Milestone {
  day: number;
  task: string;
  completed: boolean;
  resource_url?: string;
  tutorial_url?: string;
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

