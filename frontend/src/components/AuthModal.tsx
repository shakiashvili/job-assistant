import React, { useState } from 'react';
import { X, Lock, Mail, User, ShieldCheck, AlertCircle, ArrowRight, KeyRound, Sparkles, CheckCircle2 } from 'lucide-react';
import { loginUser, registerUser, sendOtp, verifyOtp } from '../services/api';
import { UserProfile } from '../types';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAuthSuccess: (user: UserProfile) => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onAuthSuccess }) => {
  const [mode, setMode] = useState<'otp' | 'login' | 'register'>('otp');
  const [otpStep, setOtpStep] = useState<'request' | 'verify'>('request');
  const [email, setEmail] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [infoMsg, setInfoMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMsg(null);
    setLoading(true);

    try {
      const res = await sendOtp(email);
      setInfoMsg(res.message);
      if (res.demo_code) {
        setOtpCode(res.demo_code);
      }
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
    setLoading(true);

    try {
      if (mode === 'login') {
        const res = await loginUser(email, password);
        onAuthSuccess(res.user);
        onClose();
      } else {
        const res = await registerUser(email, password, fullName || 'Candidate');
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
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

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
            onClick={() => { setMode('otp'); setOtpStep('request'); setError(null); setInfoMsg(null); }}
            className={`py-2 text-[11px] font-semibold rounded-lg transition-all flex items-center justify-center gap-1 ${
              mode === 'otp' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Sparkles className="w-3 h-3" />
            <span>Email OTP</span>
          </button>
          <button
            type="button"
            onClick={() => { setMode('login'); setError(null); setInfoMsg(null); }}
            className={`py-2 text-[11px] font-semibold rounded-lg transition-all flex items-center justify-center gap-1 ${
              mode === 'login' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Lock className="w-3 h-3" />
            <span>Password</span>
          </button>
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
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-950/40 border border-rose-900/60 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
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
                  placeholder="e.g. giorgi.shakiashvili.dev@gmail.com"
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
              className="w-full py-2.5 rounded-xl bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 text-white font-semibold text-xs flex items-center justify-center gap-2 shadow-lg shadow-sky-600/25 transition-all mt-4 disabled:opacity-50"
            >
              <span>{loading ? 'Sending Verification Code...' : 'Send One-Time Code'}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
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
                    placeholder="e.g. Giorgi Shakiashvili"
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
