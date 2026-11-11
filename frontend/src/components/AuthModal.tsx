import React, { useState, useEffect } from 'react';
import { X, Lock, Mail, User, ShieldCheck, AlertCircle, ArrowRight, KeyRound, Sparkles, CheckCircle2, Settings2 } from 'lucide-react';
import { loginUser, registerUser, sendOtp, verifyOtp, fetchSmtpStatus, configureSmtp } from '../services/api';
import { UserProfile } from '../types';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAuthSuccess: (user: UserProfile) => void;
  isGate?: boolean;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onAuthSuccess, isGate = false }) => {
  const [mode, setMode] = useState<'otp' | 'login' | 'register'>('login');
  const [otpStep, setOtpStep] = useState<'request' | 'verify'>('request');
  const [email, setEmail] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [infoMsg, setInfoMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Local encrypted/gitignored Gmail SMTP configuration state
  const [smtpConfigured, setSmtpConfigured] = useState<boolean | null>(null);
  const [showSmtpSetup, setShowSmtpSetup] = useState(false);
  const [smtpUser, setSmtpUser] = useState('');
  const [smtpAppPassword, setSmtpAppPassword] = useState('');
  const [smtpSaving, setSmtpSaving] = useState(false);

  useEffect(() => {
    if (!isOpen || mode !== 'otp') return;
    let active = true;
    fetchSmtpStatus()
      .then((res) => {
        if (active) {
          setSmtpConfigured(res.smtp_configured);
          if (!res.smtp_configured) setShowSmtpSetup(true);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [isOpen, mode]);

  if (!isOpen) return null;

  const handleSaveSmtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMsg(null);
    setSmtpSaving(true);
    try {
      const targetUser = (smtpUser || email).trim();
      const res = await configureSmtp(targetUser, smtpAppPassword);
      setSmtpConfigured(res.smtp_configured);
      setShowSmtpSetup(false);
      setSmtpAppPassword('');
      if (!email) setEmail(targetUser);
      setInfoMsg(res.message);
    } catch (err: any) {
      setError(err.message || 'Could not authenticate Gmail App Password.');
    } finally {
      setSmtpSaving(false);
    }
  };

  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMsg(null);
    setLoading(true);

    try {
      const res = await sendOtp(email);
      setSmtpConfigured(res.smtp_configured);
      if (res.delivered === false) {
        setShowSmtpSetup(true);
        setError(
          res.message ||
            'Gmail SMTP is not configured locally. Save your Gmail App Password below or use Sign In / Register with Password.'
        );
        return;
      }
      setInfoMsg(res.message);
      setOtpStep('verify');
    } catch (err: any) {
      setError(err.message || 'Failed to send verification code. Please check your email.');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await verifyOtp(email, otpCode);
      onAuthSuccess(res.user);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Invalid or expired verification code.');
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (mode === 'register' && password !== confirmPassword) {
      setError('Passwords do not match. Please verify both password fields.');
      return;
    }

    setLoading(true);

    try {
      if (mode === 'login') {
        const res = await loginUser(email, password);
        onAuthSuccess(res.user);
        onClose();
      } else {
        const res = await registerUser(email, password, fullName.trim() || 'Candidate');
        onAuthSuccess(res.user);
        onClose();
      }
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Please verify credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 shadow-2xl relative">
        {!isGate && (
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        )}

        <div className="flex items-center gap-2 mb-6">
          <div className="w-9 h-9 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">
              {mode === 'otp' ? 'Passwordless Sign In' : mode === 'login' ? 'Sign In with Password' : 'Create Candidate Account'}
            </h2>
            <p className="text-xs text-slate-400">
              {mode === 'otp'
                ? 'Sign in securely with a 6-digit one-time email code'
                : mode === 'login'
                ? 'Access your applications, action plans & admin controls'
                : 'Join the platform to track and automate your career'}
            </p>
          </div>
        </div>

        {/* 3-Way Mode Switcher */}
        <div className="grid grid-cols-3 gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800 mb-5">
          <button
            type="button"
            onClick={() => { setMode('register'); setError(null); setInfoMsg(null); }}
            className={`py-2 text-[11px] font-semibold rounded-lg transition-all flex items-center justify-center gap-1 ${
              mode === 'register' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}
          >
            <User className="w-3 h-3" />
            <span>Register</span>
          </button>
          <button
            type="button"
            onClick={() => { setMode('login'); setError(null); setInfoMsg(null); }}
            className={`py-2 text-[11px] font-semibold rounded-lg transition-all flex items-center justify-center gap-1 ${
              mode === 'login' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Lock className="w-3 h-3" />
            <span>Sign In</span>
          </button>
          <button
            type="button"
            onClick={() => { setMode('otp'); setOtpStep('request'); setError(null); setInfoMsg(null); }}
            className={`py-2 text-[11px] font-semibold rounded-lg transition-all flex items-center justify-center gap-1 ${
              mode === 'otp' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Sparkles className="w-3 h-3" />
            <span>Email OTP</span>
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-950/40 border border-rose-900/60 text-rose-300 text-xs space-y-2">
            <div className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
            {mode === 'register' && error.toLowerCase().includes('already exists') && (
              <div className="flex flex-wrap gap-2 pl-6">
                <button
                  type="button"
                  onClick={() => {
                    setMode('login');
                    setError(null);
                    setInfoMsg('Switched to Sign In. Enter your password or switch to Email OTP.');
                  }}
                  className="px-2.5 py-1 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold text-[11px] transition-colors"
                >
                  Switch to Sign In &rarr;
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMode('otp');
                    setOtpStep('request');
                    setError(null);
                  }}
                  className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold text-[11px] transition-colors"
                >
                  Use Email OTP
                </button>
              </div>
            )}
            {mode === 'login' && error.toLowerCase().includes('invalid email or password') && (
              <div className="pl-6">
                <button
                  type="button"
                  onClick={() => {
                    setMode('register');
                    setError(null);
                    setInfoMsg(null);
                  }}
                  className="px-2.5 py-1 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/40 text-sky-300 font-semibold text-[11px] transition-colors"
                >
                  New user? Create Account &rarr;
                </button>
              </div>
            )}
          </div>
        )}

        {infoMsg && (
          <div className="mb-4 p-3 rounded-xl bg-emerald-950/40 border border-emerald-900/60 text-emerald-300 text-xs flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <span>{infoMsg}</span>
          </div>
        )}

        {/* 1. Passwordless OTP Flow */}
        {mode === 'otp' && otpStep === 'request' && (
          <div className="space-y-4">
            <form onSubmit={handleSendOtp} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
                  Your Email Address
                </label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@example.com"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-xs text-white focus:outline-none focus:border-sky-500"
                  />
                </div>
                <p className="text-[11px] text-slate-500 mt-1.5">
                  We will send a 6-digit verification code to your inbox. No password needed.
                </p>
              </div>

              <button
                type="submit"
                disabled={loading || !email}
                className="w-full py-2.5 rounded-xl bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow-lg shadow-sky-600/25 transition-all disabled:opacity-50"
              >
                <span>{loading ? 'Sending Verification Code...' : 'Send One-Time Code'}</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>

            {smtpConfigured === false && (
              <div className="pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowSmtpSetup((v) => !v)}
                  className="text-[11px] text-sky-400 hover:text-sky-300 flex items-center gap-1.5 font-medium"
                >
                  <Settings2 className="w-3.5 h-3.5" />
                  <span>{showSmtpSetup ? 'Hide local Gmail SMTP setup' : 'Configure Gmail SMTP Sender (Local Only)'}</span>
                </button>

                {showSmtpSetup && (
                  <form onSubmit={handleSaveSmtp} className="mt-3 p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5">
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Stored strictly in local gitignored <code className="text-sky-300">backend/.env</code> &mdash; never pushed to Git or logged. Requires a 16-char Google App Password.
                    </p>
                    <input
                      type="email"
                      required
                      value={smtpUser || email}
                      onChange={(e) => setSmtpUser(e.target.value)}
                      placeholder="Sender Gmail address"
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-sky-500"
                    />
                    <input
                      type="password"
                      required
                      value={smtpAppPassword}
                      onChange={(e) => setSmtpAppPassword(e.target.value)}
                      placeholder="16-char Google App Password"
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-sky-500"
                    />
                    <button
                      type="submit"
                      disabled={smtpSaving}
                      className="w-full py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-[11px] transition-colors disabled:opacity-50"
                    >
                      {smtpSaving ? 'Verifying with Gmail SMTP...' : 'Verify & Save Local SMTP'}
                    </button>
                  </form>
                )}
              </div>
            )}
          </div>
        )}

        {mode === 'otp' && otpStep === 'verify' && (
          <form onSubmit={handleVerifyOtp} className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Enter 6-Digit Code
                </label>
                <button
                  type="button"
                  onClick={() => setOtpStep('request')}
                  className="text-[11px] text-sky-400 hover:underline"
                >
                  Change Email
                </button>
              </div>
              <div className="relative">
                <KeyRound className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                <input
                  type="text"
                  required
                  maxLength={6}
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
                  placeholder="123456"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-base tracking-widest text-center text-white focus:outline-none focus:border-sky-500 font-mono font-bold"
                />
              </div>
              <p className="text-[11px] text-slate-400 mt-1.5 text-center">
                Enter the code sent to <strong className="text-white">{email}</strong> (valid for 10 min)
              </p>
            </div>

            <button
              type="submit"
              disabled={loading || otpCode.length !== 6}
              className="w-full py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 transition-all mt-4 disabled:opacity-50"
            >
              <span>{loading ? 'Verifying Code...' : 'Verify & Sign In'}</span>
              <CheckCircle2 className="w-4 h-4" />
            </button>

            <div className="text-center pt-2">
              <button
                type="button"
                onClick={handleSendOtp}
                disabled={loading}
                className="text-[11px] text-slate-400 hover:text-sky-300 underline"
              >
                Resend code
              </button>
            </div>
          </form>
        )}

        {/* 2. Password Login & Register Flow */}
        {(mode === 'login' || mode === 'register') && (
          <form onSubmit={handlePasswordSubmit} className="space-y-4">
            {mode === 'register' && (
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
                  Full Name
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Your Full Name"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-xs text-white focus:outline-none focus:border-sky-500"
                  />
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
                Email Address
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-xs text-white focus:outline-none focus:border-sky-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
                Password {mode === 'register' && <span className="text-slate-500 font-normal">(min 8 characters)</span>}
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                <input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-xs text-white focus:outline-none focus:border-sky-500"
                />
              </div>
            </div>

            {mode === 'register' && (
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-xs text-white focus:outline-none focus:border-sky-500"
                  />
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-xl bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow-lg shadow-sky-600/25 transition-all mt-6 disabled:opacity-50"
            >
              <span>{loading ? 'Authenticating...' : mode === 'login' ? 'Sign In' : 'Create Account'}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
        )}

        <div className="mt-4 text-center">
          <p className="text-[11px] text-slate-500">
            Protected with bcrypt hashing, HS256 tokens & rate-limited brute force protection.
          </p>
        </div>
      </div>
    </div>
  );
};
