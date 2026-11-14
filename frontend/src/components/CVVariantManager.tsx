import React, { useState, useEffect, useRef } from 'react';
import {
  FileText,
  Download,
  UploadCloud,
  Trash2,
  Sparkles,
  Briefcase,
  ShieldCheck,
  UserCheck,
  Copy,
  Check,
  Languages,
} from 'lucide-react';
import {
  fetchMyCvs,
  uploadPersonalCv,
  deletePersonalCv,
  generateCvEdition,
  fetchScrapedJobs,
  BACKEND_ORIGIN,
} from '../services/api';
import { DbJobPosting } from '../types';

export const CVVariantManager: React.FC = () => {
  const [myCvs, setMyCvs] = useState<Array<{ filename: string; url: string; ext: string; size_kb: number }>>([]);
  const [uploading, setUploading] = useState(false);
  const [cvLanguage, setCvLanguage] = useState<'en' | 'ka'>('en');
  const [generatingKey, setGeneratingKey] = useState<string | null>(null);
  const [targetRole, setTargetRole] = useState('');
  const [targetCompany, setTargetCompany] = useState('');
  const [customJobUrl, setCustomJobUrl] = useState('');
  const [customJobDescription, setCustomJobDescription] = useState('');
  const [vacancySearch, setVacancySearch] = useState('');
  const [jobsList, setJobsList] = useState<DbJobPosting[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string>('');
  const [generatedOutput, setGeneratedOutput] = useState<{
    edition: string;
    title: string;
    company: string;
    subject: string;
    cover_letter: string;
    docx_filename: string;
    docx_url: string;
    pdf_filename: string;
    pdf_url: string;
  } | null>(null);
  const [copiedLetter, setCopiedLetter] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [downloadBanner, setDownloadBanner] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement | null>(null);
  const outputRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    loadInitial();
  }, []);

  const loadInitial = async () => {
    const [cvs, firstPage] = await Promise.all([
      fetchMyCvs().catch(() => []),
      fetchScrapedJobs({ page: 1, limit: 100, min_score: 0 }).catch(() => ({ items: [], total: 0, page: 1, limit: 100, total_pages: 1 })),
    ]);
    setMyCvs(cvs);
    let combined: DbJobPosting[] = firstPage.items || [];
    const totalPages = Math.min(firstPage.total_pages || 1, 10);
    if (totalPages > 1) {
      const rest = await Promise.all(
        Array.from({ length: totalPages - 1 }, (_, i) =>
          fetchScrapedJobs({ page: i + 2, limit: 100, min_score: 0 }).catch(() => ({ items: [] as DbJobPosting[] }))
        )
      );
      for (const pg of rest) {
        combined = combined.concat(pg.items || []);
      }
    }
    setJobsList(combined);
  };

  const triggerCrossOriginDownload = async (relativeOrFullUrl: string, filename: string) => {
    const targetUrl = relativeOrFullUrl.startsWith('http') ? relativeOrFullUrl : `${BACKEND_ORIGIN}${relativeOrFullUrl}`;
    try {
      const token = localStorage.getItem('talentflow_token');
      const res = await fetch(targetUrl, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
    } catch {
      window.open(targetUrl, '_blank', 'noopener,noreferrer');
    }
  };

  const handleUploadFile = async (file: File) => {
    if (!file) return;
    setUploading(true);
    setStatusError(null);
    try {
      await uploadPersonalCv(file);
      const cvs = await fetchMyCvs();
      setMyCvs(cvs);
    } catch (err: any) {
      setStatusError(err.message || 'Failed to upload CV');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteCv = async (filename: string) => {
    try {
      await deletePersonalCv(filename);
      setMyCvs((prev) => prev.filter((c) => c.filename !== filename));
    } catch (err: any) {
      setStatusError(err.message || 'Failed to remove CV');
    }
  };

  const handleSelectVacancy = (idStr: string) => {
    setSelectedJobId(idStr);
    const found = jobsList.find((j) => String(j.id) === idStr);
    if (found) {
      setTargetRole(found.title);
      setTargetCompany(found.company);
      setCustomJobUrl(found.url || '');
      setCustomJobDescription(found.description_raw || '');
    }
  };

  const handleGenerate = async (edition: 'ats' | 'recruiter' | 'tailored') => {
    setGeneratingKey(edition);
    setStatusError(null);
    setDownloadBanner(null);
    try {
      const selectedJob = jobsList.find((j) => String(j.id) === selectedJobId);
      const res = await generateCvEdition({
        edition,
        target_role: edition === 'tailored' ? targetRole || selectedJob?.title : undefined,
        target_company: edition === 'tailored' ? targetCompany || selectedJob?.company : undefined,
        job_description: edition === 'tailored' ? (customJobDescription || selectedJob?.description_raw || '') : '',
        job_url: edition === 'tailored' ? (customJobUrl || selectedJob?.url || undefined) : undefined,
        cv_language: cvLanguage,
      });
      setGeneratedOutput({
        edition: res.edition,
        title: res.title,
        company: res.company,
        subject: res.subject,
        cover_letter: res.cover_letter,
        docx_filename: res.docx_filename,
        docx_url: res.docx_url,
        pdf_filename: res.pdf_filename,
        pdf_url: res.pdf_url,
      });

      // Immediately download ready Word (.docx) file and notify user
      void triggerCrossOriginDownload(res.docx_url, res.docx_filename);

      setDownloadBanner(`Downloaded ${res.docx_filename}! Both Word (.docx) and PDF links are ready below.`);
      setTimeout(() => {
        outputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
    } catch (err: any) {
      setStatusError(err.message || 'Could not generate CV edition. Make sure skills.md is uploaded.');
    } finally {
      setGeneratingKey(null);
    }
  };

  const copyCoverLetter = () => {
    if (!generatedOutput?.cover_letter) return;
    navigator.clipboard.writeText(generatedOutput.cover_letter);
    setCopiedLetter(true);
    setTimeout(() => setCopiedLetter(false), 2500);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-sky-400" />
            My CVs &amp; Ready Word / PDF Editions
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Store your personal resumes and generate clean <strong className="text-white">Word (.docx)</strong> and{' '}
            <strong className="text-white">PDF</strong> editions built specifically for <strong className="text-sky-300">ATS</strong>,{' '}
            <strong className="text-emerald-300">Recruiters</strong>, and <strong className="text-amber-300">Specific Jobs</strong>.
          </p>
        </div>

        {/* Language Selector */}
        <div className="flex items-center gap-1.5 bg-slate-950 p-1.5 rounded-xl border border-slate-800 self-start sm:self-auto">
          <Languages className="w-4 h-4 text-slate-400 ml-1" />
          <button
            type="button"
            onClick={() => setCvLanguage('en')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              cvLanguage === 'en' ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            English
          </button>
          <button
            type="button"
            onClick={() => setCvLanguage('ka')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              cvLanguage === 'ka' ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            ქართული
          </button>
        </div>
      </div>

      {statusError && (
        <div className="p-3 bg-rose-950/40 border border-rose-800 rounded-xl text-xs text-rose-300">
          {statusError}
        </div>
      )}

      {downloadBanner && generatedOutput && (
        <div className="p-4 bg-emerald-950/40 border border-emerald-700/60 rounded-xl text-xs text-emerald-200 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <span>{downloadBanner}</span>
          <div className="flex items-center gap-2">
            <a
              href={`${BACKEND_ORIGIN}${generatedOutput.docx_url}`}
              download={generatedOutput.docx_filename}
              className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold"
            >
              Download Word (.docx)
            </a>
            <a
              href={`${BACKEND_ORIGIN}${generatedOutput.pdf_url}`}
              download={generatedOutput.pdf_filename}
              className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold"
            >
              Download PDF
            </a>
          </div>
        </div>
      )}

      {/* 1. My Uploaded CVs */}
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <UploadCloud className="w-4 h-4 text-sky-400" />
              My Uploaded CVs ({myCvs.length})
            </h3>
            <p className="text-xs text-slate-400">
              Keep your own master Word (<code>.docx</code>) or PDF resumes ready here (stored privately, never pushed to Git).
            </p>
          </div>
          <input
            ref={uploadRef}
            type="file"
            accept=".pdf,.docx,.doc,.md,.txt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUploadFile(f);
            }}
          />
          <button
            type="button"
            onClick={() => uploadRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold shadow-sm transition-colors disabled:opacity-50"
          >
            <UploadCloud className="w-4 h-4" />
            <span>{uploading ? 'Uploading...' : 'Upload My CV (.docx / .pdf)'}</span>
          </button>
        </div>

        {myCvs.length === 0 ? (
          <div className="text-xs text-slate-500 border border-dashed border-slate-800 bg-slate-950/50 rounded-xl p-6 text-center">
            No personal CV uploaded yet. Click <strong>Upload My CV</strong> above to store your own <code>.docx</code> or <code>.pdf</code> file.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {myCvs.map((cv) => (
              <div
                key={cv.filename}
                className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-sky-950 text-sky-300 border border-sky-800">
                      .{cv.ext}
                    </span>
                    <div className="text-xs font-semibold text-white truncate">{cv.filename}</div>
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">{cv.size_kb} KB</div>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <a
                    href={`${BACKEND_ORIGIN}${cv.url}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-2 rounded-lg bg-slate-900 hover:bg-sky-600 text-slate-300 hover:text-white border border-slate-800 transition-colors"
                    title="Download CV"
                  >
                    <Download className="w-3.5 h-3.5" />
                  </a>
                  <button
                    type="button"
                    onClick={() => handleDeleteCv(cv.filename)}
                    className="p-2 rounded-lg bg-slate-900 hover:bg-rose-600 text-slate-400 hover:text-white border border-slate-800 transition-colors"
                    title="Delete CV"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 2. Curated CV Editions (ATS, Recruiter, Job-Specific) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Card 1: ATS-Optimized */}
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl flex flex-col justify-between space-y-4">
          <div className="space-y-2">
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase px-2.5 py-1 rounded-full bg-sky-950 text-sky-300 border border-sky-800">
              <ShieldCheck className="w-3.5 h-3.5" />
              ATS-Optimized
            </span>
            <h3 className="text-base font-bold text-white">ATS-Parser Clean CV</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Strict single-column structure with zero tables or columns so Greenhouse, Lever, and portal ATS scanners extract 100% of your skills.
            </p>
          </div>
          <button
            type="button"
            onClick={() => handleGenerate('ats')}
            disabled={generatingKey !== null}
            className="w-full py-2.5 px-4 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4" />
            <span>{generatingKey === 'ats' ? 'Generating Word & PDF...' : 'Build ATS Word (.docx) + PDF'}</span>
          </button>
        </div>

        {/* Card 2: Recruiter-Ready */}
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl flex flex-col justify-between space-y-4">
          <div className="space-y-2">
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800">
              <UserCheck className="w-3.5 h-3.5" />
              For Recruiters
            </span>
            <h3 className="text-base font-bold text-white">Recruiter Fast-Scan CV</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Highlights impact bullets, clear stack grouping, availability, and concise human-tone executive summary crafted for 10-second recruiter review.
            </p>
          </div>
          <button
            type="button"
            onClick={() => handleGenerate('recruiter')}
            disabled={generatingKey !== null}
            className="w-full py-2.5 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4" />
            <span>{generatingKey === 'recruiter' ? 'Generating Word & PDF...' : 'Build Recruiter Word (.docx) + PDF'}</span>
          </button>
        </div>

        {/* Card 3: Job-Specific Tailored */}
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl flex flex-col justify-between space-y-4">
          <div className="space-y-3">
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase px-2.5 py-1 rounded-full bg-amber-950 text-amber-300 border border-amber-800">
              <Briefcase className="w-3.5 h-3.5" />
              For Specific Jobs
            </span>
            <h3 className="text-base font-bold text-white">Job-Tailored CV &amp; Cover Letter</h3>
            {jobsList.length > 0 && (
              <div className="space-y-1.5">
                <input
                  type="text"
                  placeholder={`Filter ${jobsList.length} vacancies by title, company, or portal...`}
                  value={vacancySearch}
                  onChange={(e) => setVacancySearch(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-amber-500"
                />
                <select
                  value={selectedJobId}
                  onChange={(e) => handleSelectVacancy(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500"
                >
                  <option value="">-- Optional: pick discovered vacancy --</option>
                  {jobsList
                    .filter((j) => {
                      const q = vacancySearch.trim().toLowerCase();
                      if (!q) return true;
                      return (
                        j.title.toLowerCase().includes(q) ||
                        j.company.toLowerCase().includes(q) ||
                        j.portal.toLowerCase().includes(q)
                      );
                    })
                    .map((j) => (
                      <option key={j.id} value={String(j.id)}>
                        {j.title} — {j.company} [{j.portal}] ({Math.round(j.suitability_score)}%)
                      </option>
                    ))}
                </select>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                placeholder="Role (e.g. Junior Analyst)"
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-amber-500"
              />
              <input
                type="text"
                placeholder="Company (e.g. Employer)"
                value={targetCompany}
                onChange={(e) => setTargetCompany(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-amber-500"
              />
            </div>
            <input
              type="url"
              placeholder="Custom job URL (optional)"
              value={customJobUrl}
              onChange={(e) => setCustomJobUrl(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-amber-500"
            />
            <textarea
              rows={2}
              placeholder="Paste custom job description (optional — tailors keywords automatically)"
              value={customJobDescription}
              onChange={(e) => setCustomJobDescription(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-200 focus:outline-none focus:border-amber-500"
            />
          </div>
          <button
            type="button"
            onClick={() => handleGenerate('tailored')}
            disabled={generatingKey !== null}
            className="w-full py-2.5 px-4 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4" />
            <span>{generatingKey === 'tailored' ? 'Generating Package...' : 'Build Job Word (.docx) + Letter'}</span>
          </button>
        </div>
      </div>

      {/* 3. Output Download & Cover Letter Preview Card */}
      {generatedOutput && (
        <div ref={outputRef} className="bg-slate-900 border border-sky-700/60 p-6 rounded-2xl space-y-4 shadow-xl">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-sky-400">
                Ready for Application ({generatedOutput.edition.toUpperCase()})
              </span>
              <h3 className="text-base font-bold text-white">
                {generatedOutput.title} — {generatedOutput.company}
              </h3>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => triggerCrossOriginDownload(generatedOutput.docx_url, generatedOutput.docx_filename)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-sm"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Download Word (.docx)</span>
              </button>
              <button
                type="button"
                onClick={() => triggerCrossOriginDownload(generatedOutput.pdf_url, generatedOutput.pdf_filename)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Download PDF</span>
              </button>
            </div>
          </div>

          <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-300">
                Email Subject: <code className="text-sky-300">{generatedOutput.subject}</code>
              </span>
              <button
                type="button"
                onClick={copyCoverLetter}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 text-xs text-slate-300 border border-slate-700"
              >
                {copiedLetter ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedLetter ? 'Copied Cover Letter!' : 'Copy Cover Letter'}</span>
              </button>
            </div>
            <pre className="text-xs text-slate-300 whitespace-pre-wrap font-sans leading-relaxed pt-2 border-t border-slate-800">
              {generatedOutput.cover_letter}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
};
