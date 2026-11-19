import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProfileVault } from '../components/ProfileVault';
import { DiscoveryFeed } from '../components/DiscoveryFeed';
import { CVVariantManager } from '../components/CVVariantManager';
import { ApplicationTracker } from '../components/ApplicationTracker';
import { StageModal } from '../components/StageModal';
import { B2BMarketHub } from '../components/B2BMarketHub';
import * as api from '../services/api';
import { DbJobPosting, GroundTruth } from '../types';

const mockGroundTruth: GroundTruth = {
  candidate: {
    first_name: 'Nino',
    last_name: 'Beridze',
    full_name: 'Nino Beridze',
    email: 'nino@example.ge',
    phone: '+995 599 12 34 56',
    headline: 'QA Automation Engineer',
    location: { city: 'Tbilisi', country: 'Georgia', open_to_relocation: true, remote_preference: 'Remote' },
    links: { linkedin: 'https://linkedin.com/in/nino', github: 'https://github.com/nino', portfolio: '' },
    work_authorization: {
      citizenship: ['GE'],
      eu_work_permit: false,
      requires_eu_visa: true,
      us_work_authorization: '',
      requires_us_visa_sponsorship: true,
      uk_work_authorization: '',
      security_clearance: false,
    },
    compensation: {
      expected_salary_eur: 3500,
      min_salary_eur: 3000,
      expected_salary_usd: 3800,
      notice_period: '2 weeks',
    },
    languages: [{ language: 'English', proficiency: 'C1' }],
  },
  skills: { core: ['Playwright', 'Python', 'PyTest'], secondary: ['Docker'] },
  work_history: [
    {
      company: 'Acme Tech',
      role: 'QA Engineer',
      start_date: '2022-01',
      end_date: 'Present',
      location: 'Tbilisi',
      highlights: ['Automated 120 E2E scenarios in Playwright.'],
    },
  ],
  education: [],
  cv_variants: {},
  faq_bank: [],
};

const mockJobs: DbJobPosting[] = [
  {
    id: 10,
    external_id: 'dou-10',
    portal: 'dou.ua',
    title: 'Senior SDET',
    company: 'CloudFlow',
    url: 'https://jobs.dou.ua/companies/cloudflow/vacancies/10/',
    market: 'INT_REMOTE',
    is_remote: true,
    salary_min: 4000,
    salary_max: 5500,
    salary_currency: 'USD',
    salary_estimated_by_ai: false,
    language_requirements: ['English'],
    delivery_channel: 'WEB_FORM',
    description_raw: 'Playwright Python B2B remote contract.',
    suitability_score: 92,
    match_tier: 'DIRECT',
    status: 'STAGED',
    match_rationale: 'Strong skill alignment',
    is_link_live: true,
    scraped_at: '2026-11-19T10:00:00Z',
  },
];

describe('Core Frontend Component Workflows', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('ProfileVault loads ground truth, updates headline, and persists edited profile', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'fetchGroundTruth').mockResolvedValueOnce(mockGroundTruth);
    vi.spyOn(api, 'fetchCandidateAnalytics').mockResolvedValueOnce({
      profile_uploaded: true,
      completeness_score: 95,
      missing_fields: [],
      matching_jobs_count: 4,
      tier_breakdown: { DIRECT: 4 },
      saved_jobs_count: 1,
      active_applications_count: 1,
      applied_count: 0,
      interviews_count: 0,
      offers_count: 0,
      response_rate_pct: 0,
      applications_by_status: {},
      upcoming_interviews: [],
    });
    const saveSpy = vi.spyOn(api, 'saveGroundTruth').mockResolvedValueOnce({
      ...mockGroundTruth,
      candidate: { ...mockGroundTruth.candidate, headline: 'Principal QA Architect' },
    });

    render(<ProfileVault />);

    const headlineInput = await screen.findByDisplayValue('QA Automation Engineer');
    await user.clear(headlineInput);
    await user.type(headlineInput, 'Principal QA Architect');
    await user.click(screen.getByRole('button', { name: /save ground truth/i }));

    await waitFor(() => expect(saveSpy).toHaveBeenCalledTimes(1));
    expect(saveSpy.mock.calls[0][0].candidate.headline).toBe('Principal QA Architect');
    expect(await screen.findByText(/profile saved/i)).toBeInTheDocument();
  });

  it('DiscoveryFeed triggers tier filters, search input, and pagination callbacks', async () => {
    const user = userEvent.setup();
    const onTier = vi.fn();
    const onSearch = vi.fn();
    const onPage = vi.fn();

    render(
      <DiscoveryFeed
        candidateProfile={{ full_name: 'Nino Beridze', headline: 'QA Engineer' }}
        visibleJobs={mockJobs}
        profileUploaded={true}
        isScraping={false}
        selectedPortalFilter="ALL"
        onSelectPortalFilter={vi.fn()}
        dbStatusFilter="ALL"
        onSelectStatusFilter={vi.fn()}
        tierTab="ALL"
        onSelectTierTab={onTier}
        tierCounts={{ ALL: 25, DIRECT: 15, ADJACENT: 7, PUBLIC_INTERNSHIP: 3 }}
        statusCounts={{ ALL: 25, STAGED: 20, AUDITED: 5 }}
        page={1}
        totalPages={3}
        totalJobs={25}
        onPageChange={onPage}
        searchQuery=""
        onSearchQueryChange={onSearch}
        scrapeStats={null}
        preparedEmailPkg={null}
        onDismissEmailPkg={vi.fn()}
        draftingJobId={null}
        onRunScrapers={vi.fn()}
        onUploadClick={vi.fn()}
        onSelectJob={vi.fn()}
        onDraftInGmail={vi.fn()}
      />
    );

    await user.click(screen.getByRole('button', { name: /direct matches/i }));
    expect(onTier).toHaveBeenCalledWith('DIRECT');

    await user.type(screen.getByPlaceholderText(/search by role/i), 'Playwright');
    expect(onSearch).toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(onPage).toHaveBeenCalledWith(2);
  });

  it('CVVariantManager generates ATS CV, shows PDF Text Extraction & Layout Check, and saves Studio edits', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'fetchMyCvs').mockResolvedValueOnce([]);
    vi.spyOn(api, 'fetchScrapedJobs').mockResolvedValueOnce({
      items: mockJobs,
      total: 1,
      page: 1,
      limit: 40,
      total_pages: 1,
    });
    vi.spyOn(api, 'fetchCvVersions')
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({
        items: [
          {
            id: 77,
            title: 'QA Automation Engineer — ATS Edition (ATS)',
            edition: 'ats',
            language: 'en',
            target_role: 'QA Automation Engineer',
            target_company: 'ATS Edition',
            structured_json: {
              summary: 'Initial verified summary.',
              headline: 'QA Automation Engineer',
              skills: ['Playwright', 'Python'],
              work_history: [],
            },
            rendered_html: '<p>Initial verified summary.</p>',
            pdf_filename: 'Nino_Beridze_QA_ATS.pdf',
            docx_filename: 'Nino_Beridze_QA_ATS.docx',
            pdf_url: '/api/resumes/generated/Nino_Beridze_QA_ATS.pdf',
            docx_url: '/api/resumes/generated/Nino_Beridze_QA_ATS.docx',
            version_number: 1,
            is_active: true,
            created_at: '2026-11-19T10:00:00Z',
            updated_at: '2026-11-19T10:00:00Z',
          },
        ],
      });

    vi.spyOn(api, 'generateCvEdition').mockResolvedValueOnce({
      status: 'ok',
      edition: 'ats',
      cv_version_id: 77,
      title: 'QA Automation Engineer',
      company: 'ATS Edition',
      subject: 'Nino Beridze — QA Automation Engineer',
      cover_letter: 'Letter text',
      cv_language: 'en',
      docx_filename: 'Nino_Beridze_QA_ATS.docx',
      docx_url: '/api/resumes/generated/Nino_Beridze_QA_ATS.docx',
      pdf_filename: 'Nino_Beridze_QA_ATS.pdf',
      pdf_url: '/api/resumes/generated/Nino_Beridze_QA_ATS.pdf',
      ats_parse_report: {
        audit_label: 'PDF Text Extraction & Layout Check',
        status: 'PASS',
        score: 95,
        page_count: 1,
        selectable_text_ok: true,
        extracted_char_count: 1450,
        candidate_name_present: true,
        contact_present: true,
        layout_check_performed: true,
        single_column_layout_ok: true,
        sections_detected: ['Summary', 'Skills', 'Experience'],
      },
    });

    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(new Blob(['docx']), { status: 200 }));
    if (!URL.createObjectURL) {
      Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:mock'), writable: true });
      Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), writable: true });
    }
    const patchSpy = vi.spyOn(api, 'patchCvVersion').mockResolvedValueOnce({
      id: 77,
      title: 'QA Automation Engineer — ATS Edition (ATS)',
      edition: 'ats',
      language: 'en',
      structured_json: { summary: 'Updated verified summary.', headline: 'QA Automation Engineer', skills: ['Playwright', 'Python'] },
      rendered_html: '<p>Updated verified summary.</p>',
      version_number: 2,
      is_active: true,
      created_at: '2026-11-19T10:00:00Z',
      updated_at: '2026-11-19T10:05:00Z',
    });

    render(<CVVariantManager />);
    await user.click(await screen.findByRole('button', { name: /build ats word/i }));

    expect(await screen.findByText('PDF Text Extraction & Layout Check')).toBeInTheDocument();
    expect(screen.getByText(/name match:/i)).toBeInTheDocument();
    expect(screen.getByText(/single-column flow:/i)).toBeInTheDocument();

    const saveBtn = await screen.findByRole('button', { name: /save & re-render pdf \+ word/i });
    await user.click(saveBtn);
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
  });

  it('ApplicationTracker requires inline confirmation before deleting and avoids window.confirm', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'fetchApplications').mockResolvedValueOnce([
      {
        id: 'app-55',
        company: 'CloudFlow',
        role: 'Senior SDET',
        portal: 'dou.ua',
        url: 'https://jobs.dou.ua/1',
        status: 'Discovered',
        match_score: 90,
      },
    ]);
    vi.spyOn(api, 'fetchGoogleCalendarStatus').mockResolvedValueOnce({
      connected: false,
      google_oauth_configured: false,
      email: '',
      auth_url: '',
    });
    const delSpy = vi.spyOn(api, 'deleteApplication').mockResolvedValueOnce(undefined);

    render(<ApplicationTracker />);
    const trashBtn = await screen.findByRole('button', { name: /remove senior sdet at cloudflow from board/i });
    await user.click(trashBtn);

    expect(delSpy).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /confirm delete senior sdet at cloudflow/i }));
    await waitFor(() => expect(delSpy).toHaveBeenCalledWith('app-55'));
  });

  it('StageModal displays authorization/staging errors and resets cleanly on reopen', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'stageApplication').mockRejectedValueOnce(
      new Error('Forbidden: requested CV file belongs to another user.')
    );

    const { rerender } = render(
      <StageModal
        isOpen={true}
        onClose={vi.fn()}
        jobUrl="https://boards.greenhouse.io/acme/jobs/1"
        variant="qa_automation"
      />
    );

    await user.click(screen.getByRole('button', { name: /launch playwright & apply/i }));
    expect(await screen.findByText(/belongs to another user/i)).toBeInTheDocument();

    rerender(
      <StageModal
        isOpen={false}
        onClose={vi.fn()}
        jobUrl="https://boards.greenhouse.io/acme/jobs/1"
        variant="qa_automation"
      />
    );
    rerender(
      <StageModal
        isOpen={true}
        onClose={vi.fn()}
        jobUrl="https://boards.greenhouse.io/acme/jobs/2"
        variant="qa_automation"
      />
    );

    expect(screen.queryByText(/belongs to another user/i)).not.toBeInTheDocument();
  });

  it('B2BMarketHub distinguishes current 1% tax from 12-month Article 90 threshold projection', async () => {
    vi.spyOn(api, 'calculateB2BTax').mockResolvedValueOnce({
      currency: 'GEL',
      fx_to_gel: 1.0,
      fx_source: 'custom',
      monthly_gross_orig: 45000,
      monthly_gross_gel: 45000,
      annual_gross_gel: 540000,
      ytd_revenue_gel: 0,
      actual_cumulative_gel: 45000,
      actual_cap_usage_pct: 9.0,
      cumulative_annual_gel: 540000,
      projected_annual_gross_gel: 540000,
      projected_cumulative_gel: 540000,
      projected_exceeds_500k_cap: true,
      threshold_crossing_month: 12,
      projected_annual_tax_gel: 6300,
      projected_effective_tax_rate_pct: 1.17,
      under_500k_cap: true,
      b2b_small_business: {
        tax_rate_pct: 1.0,
        tax_gel: 450,
        transfer_fee_gel: 0,
        net_gel: 44550,
        net_orig: 44550,
        hourly_net_orig: 278.44,
      },
      standard_labor_contract: {
        pension_gel: 900,
        income_tax_gel: 8820,
        net_gel: 35280,
        net_orig: 35280,
      },
      monthly_b2b_advantage_gel: 9270,
      cap_usage_pct: 9.0,
      notes: [],
    });
    vi.spyOn(api, 'fetchTimezoneMatrix').mockResolvedValueOnce({
      base_timezone: 'Asia/Tbilisi (GET, UTC+4)',
      selected_shift_get: '12:00-20:00 GET',
      regions: [],
    });

    render(<B2BMarketHub />);
    expect(await screen.findByText(/IE B2B \(1% Tax\)/i)).toBeInTheDocument();
    expect(screen.getByText(/1% applies this month\. At this run-rate, Month #12 crosses 500,000 GEL/i)).toBeInTheDocument();
    expect(screen.getByText(/Actual Cumulative Turnover \(YTD \+ This Month\):/i)).toBeInTheDocument();
  });
});
