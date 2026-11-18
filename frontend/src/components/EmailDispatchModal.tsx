import React, { useState, useEffect } from 'react';
import {
  X,
  Mail,
  Send,
  FileText,
  CheckCircle,
  AlertCircle,
  ExternalLink,
  Download,
} from 'lucide-react';
import { dispatchApplicationEmail, fetchGoogleLoginUrl, BACKEND_ORIGIN } from '../services/api';

interface EmailDispatchModalProps {
  isOpen: boolean;
  onClose: () => void;
  appId: string;
  companyName: string;
  jobTitle: string;
  defaultEmail?: string;
  cvPdfPath?: string;
  onEmailSent?: () => void;
}

export const EmailDispatchModal: React.FC<EmailDispatchModalProps> = ({
  isOpen,
  onClose,
  appId,
  companyName,
  jobTitle,
  defaultEmail = '',
  cvPdfPath,
  onEmailSent,
}) => {
  const [recipient, setRecipient] = useState(defaultEmail || '');
  const [subject, setSubject] = useState(`Application: ${jobTitle}`);
  const [body, setBody] = useState(
    `Dear ${companyName} Hiring Team,\n\n` +
      `I am writing to express my strong interest in the ${jobTitle} position.\n\n` +
      `With relevant hands-on experience aligned to your team's key requirements, I am ready to contribute from day one.\n\n` +
      `Please find attached my tailored CV. I look forward to the opportunity to discuss my qualifications.\n\n` +
      `Best regards,`
  );
  const [mode, setMode] = useState<'draft' | 'send'>('draft');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleConnectGoogle = async () => {
    try {
      const url = await fetchGoogleLoginUrl();
      window.open(url, '_blank');
    } catch (err: any) {
      alert(err.message || 'Failed to initiate Google OAuth');
    }
  };

  const handleDispatch = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await dispatchApplicationEmail(appId, {
        recipient_email: recipient,
        subject,
        body_text: body,
        mode,
      });
      setResult(res);
      if (onEmailSent) onEmailSent();
    } catch (err: any) {
      setError(err.message || 'Failed to process email dispatch.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-3 sm:p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="email-dispatch-dialog-title"
    >
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full p-5 sm:p-6 shadow-2xl space-y-5 my-auto">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-600 flex items-center justify-center text-white shadow-md shadow-emerald-500/20">
              <Mail className="w-5 h-5" aria-hidden="true" />
            </div>
            <div>
              <h2 id="email-dispatch-dialog-title" className="text-base font-bold text-white">
                Gmail Application Dispatch &amp; Drafts
              </h2>
              <p className="text-xs text-slate-300">
                Send via configured Gmail SMTP/OAuth or download an RFC 2822 .eml draft with your CV attached
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close email dispatch dialog"
            className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {error && (
          <div className="p-3.5 rounded-xl bg-rose-950/40 border border-rose-900/60 text-rose-200 text-xs flex items-center gap-2" role="alert">
            <AlertCircle className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {result && (
          <div
            className={`p-4 rounded-xl border text-xs space-y-2.5 ${
              result.status === 'needs_transport'
                ? 'bg-amber-950/40 border-amber-700/80 text-amber-200'
                : 'bg-emerald-950/40 border-emerald-800/80 text-emerald-200'
            }`}
          >
            <div className={`flex items-center gap-2 font-bold ${result.status === 'needs_transport' ? 'text-amber-300' : 'text-emerald-300'}`}>
              <CheckCircle className="w-4 h-4" aria-hidden="true" />
              <span>{result.action || (result.mode === 'send' ? 'Dispatched Successfully!' : 'Draft Saved to Gmail!')}</span>
            </div>
            <p className="text-[11px] text-slate-200">
              Recipient: <strong>{result.recipient}</strong> • Attachment: {result.pdf_attached ? 'Tailored CV Included' : 'No attachment'}
            </p>
            {result.eml_url && (
              <div className="pt-1">
                <a
                  href={`${BACKEND_ORIGIN}${result.eml_url}`}
                  download={result.eml_filename}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-semibold"
                >
                  <Download className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Download Ready .eml (Open in Mail / Gmail)</span>
                </a>
              </div>
            )}
            <p className="text-[11px] text-slate-300">
              {result.note}
            </p>
          </div>
        )}

        <form onSubmit={handleDispatch} className="space-y-4">
          {/* Dispatch Mode Selector */}
          <div className="grid grid-cols-2 gap-2 bg-slate-950 p-1 rounded-xl border border-slate-800">
            <button
              type="button"
              onClick={() => setMode('draft')}
              className={`py-2 text-xs font-semibold rounded-lg transition-all ${
                mode === 'draft'
                  ? 'bg-emerald-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              📝 Save as Draft in Gmail
            </button>
            <button
              type="button"
              onClick={() => setMode('send')}
              className={`py-2 text-xs font-semibold rounded-lg transition-all ${
                mode === 'send'
                  ? 'bg-emerald-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              🚀 Send Application Directly
            </button>
          </div>

          <div>
            <label htmlFor="email-recipient-input" className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1">
              Recipient HR Email
            </label>
            <input
              id="email-recipient-input"
              type="email"
              required
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-emerald-400 font-mono"
            />
          </div>

          <div>
            <label htmlFor="email-subject-input" className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1">
              Subject Line
            </label>
            <input
              id="email-subject-input"
              type="text"
              required
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-emerald-400"
            />
          </div>

          <div>
            <label htmlFor="email-body-textarea" className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1">
              Cover Letter &amp; Message Body
            </label>
            <textarea
              id="email-body-textarea"
              rows={6}
              required
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-xs text-slate-200 focus:outline-none focus:border-emerald-400 leading-relaxed font-sans"
            />
          </div>

          {/* Attachment Preview Banner */}
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 text-slate-300">
              <FileText className="w-4 h-4 text-rose-400" aria-hidden="true" />
              <span>Tailored Resume Attached:</span>
              <span className="font-mono text-emerald-300 text-[11px]">
                {cvPdfPath ? cvPdfPath.split('/').pop() : 'No CV attached yet — generate one in CV Studio'}
              </span>
            </div>
            <span className="text-[10px] text-slate-300 font-medium">application/pdf</span>
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={handleConnectGoogle}
              className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center gap-1"
            >
              <span>Connect / Re-auth Gmail OAuth</span>
              <ExternalLink className="w-3 h-3" />
            </button>

            <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={loading}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white font-semibold text-xs flex items-center gap-2 shadow-lg shadow-emerald-600/25 disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                <span>{loading ? 'Processing...' : mode === 'draft' ? 'Create Gmail Draft' : 'Send Application'}</span>
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
