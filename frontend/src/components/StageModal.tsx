import React, { useState, useEffect } from 'react';
import {
  X,
  Play,
  CheckCircle2,
  AlertTriangle,
  FileCheck,
  ExternalLink,
  Loader2,
  ShieldCheck,
  Star,
  Download
} from 'lucide-react';
import { stageApplication, BACKEND_ORIGIN } from '../services/api';
import { StageApplicationResponse, CompanyValidation, TailoredCVResult } from '../types';

interface StageModalProps {
  isOpen: boolean;
  onClose: () => void;
  jobUrl: string;
  variant: string;
  jobTitle?: string;
  company?: string;
  companyValidation?: CompanyValidation;
  tailoredCv?: TailoredCVResult;
}

export const StageModal: React.FC<StageModalProps> = ({
  isOpen,
  onClose,
  jobUrl,
  variant,
  companyValidation,
  tailoredCv
}) => {
  const [urlInput, setUrlInput] = useState(jobUrl || 'https://jobs.dou.ua/companies/macpaw/vacancies/289104/');
  const [applicantSummary, setApplicantSummary] = useState('');
  const [motivationLetter, setMotivationLetter] = useState('');
  const [expectedSalary, setExpectedSalary] = useState('€85,000 / year ($4,500/mo remote)');
  const [startDate, setStartDate] = useState('1 week after offer');
  const [headless, setHeadless] = useState(false);
  const [autoSubmit, setAutoSubmit] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<StageApplicationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (jobUrl) setUrlInput(jobUrl);
    if (tailoredCv) {
      setApplicantSummary(tailoredCv.applicant_summary || tailoredCv.human_tone_summary || '');
      const isDou = (jobUrl || '').toLowerCase().includes('dou');
      setMotivationLetter(
        isDou
          ? tailoredCv.dou_motivational_letter || tailoredCv.motivation_statement
          : tailoredCv.motivation_statement || tailoredCv.dou_motivational_letter
      );
      if (tailoredCv.expected_salary) setExpectedSalary(tailoredCv.expected_salary);
      setStartDate(tailoredCv.start_date_default || '1 week after offer');
    }
  }, [jobUrl, tailoredCv]);

  if (!isOpen) return null;

  const handleStage = async () => {
    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await stageApplication({
        job_url: urlInput,
        variant: variant,
        custom_pdf_filename: tailoredCv?.pdf_filename,
        applicant_summary: applicantSummary,
        motivation_letter: motivationLetter,
        expected_salary: expectedSalary,
        start_date: startDate,
        auto_submit: autoSubmit,
        headless: headless,
      });
      setResult(res);
    } catch (err: any) {
      setError(err.message || 'Failed to stage application');
    } finally {
      setIsLoading(false);
    }
  };

  const portalPresets = [
    { label: 'DOU.ua (+Motivational Letter)', url: 'https://jobs.dou.ua/companies/macpaw/vacancies/289104/' },
    { label: 'Djinni.co', url: 'https://djinni.co/jobs/654321-qa-engineer-playwright/' },
    { label: 'Jobs.ge / HR.ge / HH.ge', url: 'https://jobs.ge/en/?view=jobs&id=541092' },
    { label: 'JustJoin.it (B2B)', url: 'https://justjoin.it/offers/allegro-qa-automation-engineer' },
    { label: 'Greenhouse', url: 'https://boards.greenhouse.io/cloudscale/jobs/7123910' },
    { label: 'Lever', url: 'https://jobs.lever.co/datasphere/sdet' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-3xl overflow-hidden shadow-2xl my-8">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-sky-500/20 text-sky-400 flex items-center justify-center font-bold text-lg">
              ⚡
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">
                Playwright Full Form & CAPTCHA Application Stager
              </h3>
              <p className="text-xs text-slate-400">
                Validates 3+ company reviews • Attaches Per-Vacancy Human-Tone PDF • Fills Summary, Motivation, Salary, Start Date ("1 week after offer") & CAPTCHA
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
          {/* Company 3+ Reviews Gate Banner */}
          {companyValidation && (
            <div
              className={`p-3.5 rounded-xl border flex items-center justify-between ${
                companyValidation.passed_gate
                  ? 'bg-emerald-950/30 border-emerald-800/60 text-emerald-300'
                  : 'bg-rose-950/30 border-rose-800/60 text-rose-300'
              }`}
            >
              <div className="flex items-center gap-2.5 text-xs">
                <Star className="w-4 h-4 fill-current text-amber-400 flex-shrink-0" />
                <div>
                  <span className="font-semibold">{companyValidation.verdict}</span>
                  <div className="text-[11px] text-slate-400">
                    Checked across: {companyValidation.portals_checked.join(' • ')}
                  </div>
                </div>
              </div>
              <span className="text-[10px] font-bold uppercase px-2.5 py-1 rounded-full bg-slate-950/80 border border-slate-700">
                {companyValidation.review_count} Reviews ({companyValidation.rating}★)
              </span>
            </div>
          )}

          {/* Target URL & Portal Switcher */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-xs font-semibold uppercase text-slate-400">
                Target Portal Application URL
              </label>
              <a
                href={urlInput}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-sky-400 hover:underline flex items-center gap-1 font-medium"
              >
                <span>Open Form in Browser Tab</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </div>
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono"
            />
            <div className="flex flex-wrap gap-1.5 mt-2">
              {portalPresets.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => setUrlInput(p.url)}
                  className={`text-[11px] px-2.5 py-1 rounded-md border transition-colors ${
                    urlInput === p.url
                      ? 'bg-sky-600 text-white border-sky-500 font-semibold'
                      : 'bg-slate-950 text-sky-400 border-slate-800 hover:border-sky-700'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Attached Per-Vacancy PDF CV */}
          {tailoredCv && (
            <div className="p-3.5 bg-sky-950/25 border border-sky-800/50 rounded-xl flex items-center justify-between">
              <div className="flex items-center gap-2.5 text-xs">
                <FileCheck className="w-5 h-5 text-sky-400 flex-shrink-0" />
                <div>
                  <span className="font-semibold text-white">
                    Per-Vacancy Human-Tone PDF CV: {tailoredCv.pdf_filename}
                  </span>
                  <div className="text-[11px] text-slate-400">
                    Generated from your attached <code className="text-sky-300">candidate_skills.md</code> • ATS Keywords injected
                  </div>
                </div>
              </div>
              <a
                href={`${BACKEND_ORIGIN}${tailoredCv.pdf_url}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                <span>View PDF</span>
              </a>
            </div>
          )}

          {/* Editable Answers: Summary, DOU/Portal Motivation, Salary, 1-Week Start Date */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Expected Salary
              </label>
              <input
                type="text"
                value={expectedSalary}
                onChange={(e) => setExpectedSalary(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase text-emerald-400 mb-1">
                Start Date / Availability (Default: 1 Week After Offer)
              </label>
              <input
                type="text"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full bg-slate-950 border border-emerald-800/60 rounded-lg px-3 py-2 text-xs text-emerald-300 font-semibold"
              />
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
              Applicant Summary (Human Tone)
            </label>
            <textarea
              rows={2}
              value={applicantSummary}
              onChange={(e) => setApplicantSummary(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 leading-relaxed"
            />
          </div>

          <div>
            <label className="block text-[11px] font-semibold uppercase text-rose-400 mb-1">
              Motivational Letter / Recruiter Message (Mandatory on DOU.ua & Djinni)
            </label>
            <textarea
              rows={4}
              value={motivationLetter}
              onChange={(e) => setMotivationLetter(e.target.value)}
              className="w-full bg-slate-950 border border-rose-900/50 rounded-lg p-2.5 text-xs text-slate-200 leading-relaxed"
            />
          </div>

          {/* Browser & Auto-Submit Controls */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
            <div className="flex items-center justify-between">
              <div>
                <span className="block text-xs font-medium text-slate-300">Visible Browser Window</span>
                <span className="text-[11px] text-slate-500">Opens Chromium on your desktop</span>
              </div>
              <button
                type="button"
                onClick={() => setHeadless(!headless)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  !headless ? 'bg-sky-600' : 'bg-slate-700'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    !headless ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <span className="block text-xs font-medium text-slate-300">Auto-Submit Form After CAPTCHA</span>
                <span className="text-[11px] text-slate-500">Or pause for human review</span>
              </div>
              <button
                type="button"
                onClick={() => setAutoSubmit(!autoSubmit)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  autoSubmit ? 'bg-emerald-600' : 'bg-slate-700'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    autoSubmit ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>

          {/* Error Message */}
          {error && (
            <div className="p-3 bg-rose-950/40 border border-rose-800 rounded-xl text-xs text-rose-300 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Success Result */}
          {result && (
            <div
              className={`p-4 rounded-xl border space-y-2.5 ${
                result.status === 'error' || result.status === 'blocked_by_reviews'
                  ? 'bg-rose-950/30 border-rose-800 text-rose-300'
                  : 'bg-emerald-950/30 border-emerald-800/70 text-emerald-300'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-semibold text-sm">
                  <CheckCircle2 className="w-5 h-5" />
                  <span>{result.message}</span>
                </div>
                <span className="text-xs uppercase bg-slate-950 px-2.5 py-0.5 rounded font-mono">
                  {result.portal_detected}
                </span>
              </div>

              <div className="text-xs text-slate-300 space-y-1">
                <div>
                  <strong>Fields Filled ({result.fields_filled.length}):</strong>{' '}
                  <span className="text-slate-400">{result.fields_filled.join(', ')}</span>
                </div>
                <div className="flex flex-wrap items-center gap-4 pt-1">
                  <span className="flex items-center gap-1.5 text-sky-400 font-medium">
                    <FileCheck className="w-4 h-4" />
                    CV PDF Attached: {result.file_uploaded ? 'Yes' : 'No'}
                  </span>
                  <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                    <ShieldCheck className="w-4 h-4" />
                    CAPTCHA Status: {(result.captcha_status || 'solved').toUpperCase()}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <a
            href={urlInput}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-slate-400 hover:text-sky-400 flex items-center gap-1"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            <span>Preview Portal Form in New Tab</span>
          </a>

          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              Close
            </button>
            <button
              onClick={handleStage}
              disabled={isLoading || !urlInput}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-semibold text-white bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 shadow-lg shadow-sky-600/30 disabled:opacity-50 transition-all"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Running Playwright Stager...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  <span>Launch Playwright & Apply</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
