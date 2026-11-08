import React, { useState, useEffect } from 'react';
import { FileText, Download, CheckCircle, Tag, Sparkles, RefreshCw, Eye } from 'lucide-react';
import { fetchGeneratedResumes, BACKEND_ORIGIN } from '../services/api';

type VariantKey =
  | 'qa_automation'
  | 'receptionist_hospitality'
  | 'customer_service'
  | 'healthcare_hospital'
  | 'qa_manual'
  | 'tech_support';

export const CVVariantManager: React.FC = () => {
  const [activeVariant, setActiveVariant] = useState<VariantKey>('qa_automation');
  const [generatedResumes, setGeneratedResumes] = useState<
    Array<{ filename: string; url: string; html_url?: string | null; size_kb: number }>
  >([]);

  useEffect(() => {
    loadGeneratedResumes();
  }, []);

  const loadGeneratedResumes = async () => {
    const list = await fetchGeneratedResumes();
    setGeneratedResumes(list);
  };

  const variants: Record<
    VariantKey,
    {
      id: VariantKey;
      title: string;
      badge: string;
      summary: string;
      keywords: string[];
      resume_file: string;
      idealFor: string;
    }
  > = {
    qa_automation: {
      id: 'qa_automation',
      title: 'Lead QA Automation Engineer / SDET',
      badge: '💻 Tech & QA',
      summary:
        'Senior QA Automation Engineer with 5+ years of practical experience building fast, reliable test suites in Playwright, Cypress, and Python. Focused on keeping CI/CD pipelines green and cutting regression cycles from hours to minutes. Available to start 1 week after offer.',
      keywords: ['Playwright', 'Cypress', 'Python', 'TypeScript', 'CI/CD', 'Docker', 'PyTest', 'API Testing', 'SDET'],
      resume_file: 'resume_qa_automation.pdf',
      idealFor: 'Roles on DOU.ua, Djinni.co, Jobs.ge, JustJoin.it requiring Playwright, Cypress, Python, SDET, and CI/CD.',
    },
    receptionist_hospitality: {
      id: 'receptionist_hospitality',
      title: 'Front Desk Receptionist & Guest Relations (მიმღები-რეცეფციონისტი)',
      badge: '🏨 Hospitality & Hotels',
      summary:
        'Warm, organized, and detail-oriented Front Desk Receptionist and Hospitality Specialist with 4+ years of experience at 5-star boutique and international hotels. Skilled in Opera PMS, Fidelio, Booking.com/Expedia channel management, VIP guest check-in/check-out, and calm multi-line phone handling in Georgian, English, and Russian.',
      keywords: [
        'Opera PMS',
        'Fidelio',
        'Guest Check-in / Check-out',
        'Booking.com & Expedia',
        'Reservation Management',
        'VIP Guest Relations',
        'POS & Cash Billing',
        'Georgian & English',
      ],
      resume_file: 'resume_qa_automation.pdf',
      idealFor: 'Hotel Receptionist, Front Office, Concierge, and Guest Relations roles on Jobs.ge, HR.ge, and HeadHunter.ge.',
    },
    customer_service: {
      id: 'customer_service',
      title: 'Customer Service & Client Care Specialist (მომხმარებელთა მხარდაჭერა)',
      badge: '🎧 Customer Care',
      summary:
        'Empathetic and high-performing Customer Service & Client Success Specialist with 4+ years of experience supporting international customers across live chat, email, and phone. Expert in Zendesk, Intercom, Salesforce CRM, conflict de-escalation, and maintaining 98%+ CSAT scores.',
      keywords: [
        'Omnichannel Support',
        'Zendesk',
        'Intercom',
        'Salesforce CRM',
        'Conflict De-escalation',
        'CSAT / NPS',
        'Live Chat & Phone',
        'SLA Management',
      ],
      resume_file: 'resume_tech_support.pdf',
      idealFor: 'Customer Support, Call Center, Client Relations, and Account Care roles on Jobs.ge, Djinni, and remote BPOs.',
    },
    healthcare_hospital: {
      id: 'healthcare_hospital',
      title: 'Hospital Patient Coordinator & Medical Receptionist (სამედიცინო კოორდინატორი)',
      badge: '🏥 Hospital & Clinic',
      summary:
        'Compassionate, composed, and highly organized Hospital Patient Coordinator & Medical Receptionist with 5 years of experience in modern multi-profile clinics and hospitals. Proficient in Electronic Medical Records (EMR/EHR), patient registration, insurance claims verification, and doctor appointment scheduling.',
      keywords: [
        'Patient Registration',
        'EMR / EHR Systems',
        'Health Insurance Verification',
        'Appointment Scheduling',
        'Medical Front Desk',
        'Triage Coordination',
        'Medical Confidentiality',
      ],
      resume_file: 'resume_qa_manual.pdf',
      idealFor: 'Hospitals, Multi-profile Clinics, Medical Reception, and Patient Coordination roles on HR.ge and Jobs.ge.',
    },
    qa_manual: {
      id: 'qa_manual',
      title: 'Senior Quality Assurance & Release Specialist',
      badge: '🔍 Product QA',
      summary:
        'Quality Assurance Specialist focused on exploratory testing, BDD requirements validation, test case design, regression management, and cross-browser quality audits across SaaS and FinTech platforms. Available 1 week after offer.',
      keywords: ['Manual Testing', 'Test Plans', 'Jira', 'Xray', 'Exploratory Testing', 'Bug Reporting', 'BDD', 'Agile'],
      resume_file: 'resume_qa_manual.pdf',
      idealFor: 'Roles emphasizing exploratory testing, user acceptance testing, compliance, and release governance.',
    },
    tech_support: {
      id: 'tech_support',
      title: 'Technical Support Engineer / Solutions Specialist',
      badge: '🛠️ Tech Support',
      summary:
        'Technical Support & QA Engineer with strong debugging skills in REST APIs, SQL queries, network logs, and web UI diagnostics. Bridges customer escalations and engineering teams. Available 1 week after offer.',
      keywords: ['Tier 3 Support', 'REST APIs', 'SQL Debugging', 'Log Analysis', 'SaaS Troubleshooting', 'Postman'],
      resume_file: 'resume_tech_support.pdf',
      idealFor: 'Roles focusing on Tier-3 customer support, API escalation, and technical solutions engineering.',
    },
  };

  const current = variants[activeVariant];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <FileText className="w-5 h-5 text-sky-400" />
          Multi-Industry & Bilingual (EN / KA ქართული) CV Variants
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          Every time you audit or stage a vacancy, the system generates a custom PDF & Printable HTML CV in{' '}
          <strong className="text-slate-200">English</strong> or <strong className="text-emerald-300">Georgian (ქართული ენა)</strong>{' '}
          tailored to that exact company and role from your <code className="text-sky-300">candidate_skills.md</code>.
        </p>
      </div>

      {/* Dynamically Generated Per-Vacancy PDF CVs */}
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-emerald-400" />
              Dynamically Generated Per-Vacancy CVs ({generatedResumes.length})
            </h3>
            <p className="text-xs text-slate-400">
              Generated in a natural human tone in English (EN) and Georgian (KA) across QA, Hospitality, Customer Care, and Healthcare.
            </p>
          </div>
          <button
            onClick={loadGeneratedResumes}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
        </div>

        {generatedResumes.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {generatedResumes.map((item) => {
              const isGeorgian = item.filename.includes('_KA.');
              return (
                <div
                  key={item.filename}
                  className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          isGeorgian
                            ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                            : 'bg-sky-950 text-sky-300 border border-sky-800'
                        }`}
                      >
                        {isGeorgian ? '🇬🇪 KA' : '🇬🇧 EN'}
                      </span>
                      <div className="text-xs font-bold text-white truncate">{item.filename}</div>
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      Human-Tone Tailored CV • {item.size_kb} KB
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <a
                      href={`${BACKEND_ORIGIN}${item.url}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>PDF</span>
                    </a>
                    {item.html_url && (
                      <a
                        href={`${BACKEND_ORIGIN}${item.html_url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700"
                        title="Open Printable HTML View"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-xs text-slate-500 italic py-4">
            No per-vacancy PDFs generated yet — click "Audit & Generate CV" in the Audit & Stage tab to generate one!
          </div>
        )}
      </div>

      {/* Variant Selector Tabs (6 Multi-Industry Templates) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {(Object.keys(variants) as VariantKey[]).map((key) => {
          const v = variants[key];
          const isSelected = activeVariant === key;
          return (
            <div
              key={key}
              onClick={() => setActiveVariant(key)}
              className={`p-5 rounded-2xl border cursor-pointer transition-all ${
                isSelected
                  ? 'bg-slate-900 border-sky-500/80 shadow-lg shadow-sky-500/10'
                  : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-semibold uppercase px-2.5 py-0.5 rounded-full bg-sky-950 text-sky-400 border border-sky-800">
                  {v.badge}
                </span>
                {isSelected && <CheckCircle className="w-4 h-4 text-sky-400" />}
              </div>
              <h3 className="text-sm font-bold text-white leading-snug">{v.title}</h3>
              <p className="text-xs text-slate-400 line-clamp-2 mt-1.5">{v.summary}</p>
            </div>
          );
        })}
      </div>

      {/* Active Variant Deep Dive */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-sky-400">Industry Profile Template</span>
            <h3 className="text-lg font-bold text-white">{current.title}</h3>
            <p className="text-xs text-slate-400 mt-0.5">{current.idealFor}</p>
          </div>

          <a
            href={`${BACKEND_ORIGIN}/api/resumes/${current.resume_file}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors self-start sm:self-auto"
          >
            <Download className="w-4 h-4" />
            <span>Download Base PDF</span>
          </a>
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase text-slate-400 mb-2">Human-Tone Summary</h4>
          <p className="text-xs text-slate-300 leading-relaxed bg-slate-950 p-4 rounded-xl border border-slate-800">
            {current.summary}
          </p>
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase text-slate-400 mb-2 flex items-center gap-1.5">
            <Tag className="w-3.5 h-3.5" />
            <span>Target Industry & ATS Keywords</span>
          </h4>
          <div className="flex flex-wrap gap-2">
            {current.keywords.map((kw) => (
              <span
                key={kw}
                className="text-xs px-3 py-1 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 font-medium"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
