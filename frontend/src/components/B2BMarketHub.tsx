import React, { useState, useEffect } from 'react';
import {
  Globe2,
  Calculator,
  Clock,
  CheckCircle2,
  Circle,
  Send,
  Copy,
  Check,
  ShieldCheck,
  TrendingUp,
  Info,
} from 'lucide-react';
import {
  calculateB2BTax,
  fetchTimezoneMatrix,
  generateB2BProposal,
  generateB2BInvoice,
} from '../services/api';
import {
  B2BTaxCalculatorResponse,
  TimezoneMatrixResponse,
  B2BProposalResponse,
  B2BInvoiceResponse,
} from '../types';

const CHECKLIST_STORAGE_KEY = 'talentflow_b2b_readiness_v1';

const DEFAULT_READINESS_ITEMS = [
  {
    id: 'ie_small_biz',
    labelEn: 'Georgian IE + 1% Small Business Status (rs.ge)',
    labelKa: 'ინდ. მეწარმე + 1% მცირე ბიზნესის სტატუსი (rs.ge)',
    detailEn: 'Reduces tax from 21.6% (labor contract) to 1% on international B2B exports under 500,000 GEL/year.',
    detailKa: 'უცხოურ B2B ექსპორტზე 500,000 ლარამდე წლიურ ბრუნვაზე გადასახადი 21.6%-ის ნაცვლად 1%-ია.',
  },
  {
    id: 'usd_eur_iban',
    labelEn: 'Multi-Currency USD / EUR IBAN (TBC, Bank of Georgia, Wise, or Payoneer)',
    labelKa: 'მულტისავალუტო USD / EUR ანგარიში (TBC, BOG, Wise ან Payoneer)',
    detailEn: 'Keep SWIFT/IBAN routing details ready for fast contractor onboarding & lower FX conversion spread.',
    detailKa: 'მოამზადეთ SWIFT/IBAN რეკვიზიტები უცხოური B2B გადახდებისთვის.',
  },
  {
    id: 'w8ben_ready',
    labelEn: 'W-8BEN Foreign Contractor Tax Form Prepared (for US clients)',
    labelKa: 'W-8BEN ფორმა აშშ-ს კლიენტებისთვის',
    detailEn: 'Confirms non-US tax residency so US companies do not withhold 30% US backup tax.',
    detailKa: 'ადასტურებს არარეზიდენტ სტატუსს აშშ-ში 30%-იანი დაბეგვრის თავიდან ასაცილებლად.',
  },
  {
    id: 'b2b_invoice_msa',
    labelEn: 'B2B Monthly Invoice & English MSA/SOW Template Ready',
    labelKa: 'ინგლისური B2B ინვოისისა და სერვის-კონტრაქტის (MSA/SOW) შაბლონი',
    detailEn: 'Required both by foreign finance teams (Deel, Remote, direct clients) and Georgian Revenue Service.',
    detailKa: 'საჭიროა როგორც უცხოელი პარტნიორებისთვის, ისე საქართველოს საგადასახადო აღრიცხვისთვის.',
  },
];

export const B2BMarketHub: React.FC = () => {
  const [lang, setLang] = useState<'en' | 'ka'>('en');

  // Tax Calculator State
  const [amount, setAmount] = useState<number>(3000);
  const [currency, setCurrency] = useState<'USD' | 'EUR' | 'GBP' | 'GEL'>('USD');
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'hourly' | 'annual'>('monthly');
  const [fxOverride, setFxOverride] = useState<string>('');
  const [transferFeePct, setTransferFeePct] = useState<number>(0.5);
  const [taxResult, setTaxResult] = useState<B2BTaxCalculatorResponse | null>(null);
  const [taxLoading, setTaxLoading] = useState<boolean>(false);

  // Timezone Matrix State
  const [shiftStart, setShiftStart] = useState<number>(12);
  const [tzMatrix, setTzMatrix] = useState<TimezoneMatrixResponse | null>(null);

  // B2B Checklist State
  const [completedChecklist, setCompletedChecklist] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem(CHECKLIST_STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });

  // B2B Client Pitch State
  const [propRole, setPropRole] = useState<string>('QA Automation Engineer');
  const [propCompany, setPropCompany] = useState<string>('Remote Partner');
  const [propRegion, setPropRegion] = useState<string>('EU / CET & UK');
  const [propRate, setPropRate] = useState<string>('$3,000 / month B2B');
  const [propNotes, setPropNotes] = useState<string>('');
  const [proposal, setProposal] = useState<B2BProposalResponse | null>(null);
  const [propLoading, setPropLoading] = useState<boolean>(false);
  const [copiedProp, setCopiedProp] = useState<boolean>(false);

  // B2B Contractor Monthly Invoice State
  const [invClient, setInvClient] = useState<string>('Acme Remote Inc.');
  const [invService, setInvService] = useState<string>('Software Engineering & QA Automation Services (Monthly Retainer)');
  const [invAmount, setInvAmount] = useState<number>(3000);
  const [invCurrency, setInvCurrency] = useState<'USD' | 'EUR' | 'GBP' | 'GEL'>('USD');
  const [invMethod, setInvMethod] = useState<string>('SWIFT / IBAN Wire Transfer (USD/EUR)');
  const [invAccount, setInvAccount] = useState<string>('');
  const [invoicePreview, setInvoicePreview] = useState<B2BInvoiceResponse | null>(null);
  const [invLoading, setInvLoading] = useState<boolean>(false);
  const [copiedInv, setCopiedInv] = useState<boolean>(false);

  const runTaxCalc = async () => {
    if (!amount || amount <= 0) return;
    setTaxLoading(true);
    try {
      const parsedFx = parseFloat(fxOverride);
      const res = await calculateB2BTax({
        amount,
        currency,
        billing_period: billingPeriod,
        custom_fx_to_gel: !Number.isNaN(parsedFx) && parsedFx > 0 ? parsedFx : undefined,
        transfer_fee_pct: transferFeePct,
      });
      setTaxResult(res);
    } catch {
      // Non-blocking fallback state
    } finally {
      setTaxLoading(false);
    }
  };

  useEffect(() => {
    void runTaxCalc();
  }, [amount, currency, billingPeriod, fxOverride, transferFeePct]);

  useEffect(() => {
    fetchTimezoneMatrix(shiftStart, shiftStart + 8)
      .then(setTzMatrix)
      .catch(() => {});
  }, [shiftStart]);

  const toggleChecklistItem = (id: string) => {
    setCompletedChecklist((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      try {
        localStorage.setItem(CHECKLIST_STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  };

  const handleGenerateProposal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!propRole.trim() || !propCompany.trim()) return;
    setPropLoading(true);
    try {
      const res = await generateB2BProposal({
        target_role: propRole.trim(),
        target_company: propCompany.trim(),
        client_region: propRegion,
        contract_rate: propRate.trim() || undefined,
        requirements_snippet: propNotes.trim() || undefined,
        language: lang,
      });
      setProposal(res);
    } finally {
      setPropLoading(false);
    }
  };

  const completedCount = DEFAULT_READINESS_ITEMS.filter((i) => Boolean(completedChecklist[i.id])).length;
  const readinessPct = Math.round((completedCount / DEFAULT_READINESS_ITEMS.length) * 100);
  const isKa = lang === 'ka';

  return (
    <div className="space-y-6">
      {/* Calm Confidence Header */}
      <div className="glass-card rounded-2xl p-6 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="space-y-2 max-w-3xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-950/80 border border-emerald-700/60 text-emerald-300 text-xs font-semibold">
            <Globe2 className="w-3.5 h-3.5" />
            <span>
              {isKa
                ? 'საქართველოდან დისტანციური და გლობალური B2B კონტრაქტების ცენტრი'
                : 'Georgia Local & Global Remote B2B Command Hub'}
            </span>
          </div>
          <h1 className="text-xl sm:text-2xl font-extrabold text-white">
            {isKa
              ? '1% მცირე ბიზნესის კალკულატორი, დროის სარტყელი (UTC+4) და B2B შეთავაზებები'
              : '1% B2B Tax Take-Home Calculator, Tbilisi Timezone Overlap & Contractor Pitch Builder'}
          </h1>
          <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
            {isKa
              ? 'შეადარეთ ადგილობრივი შრომითი ხელშეკრულება (20%+2%) და უცხოური B2B კონტრაქტი (1% მცირე ბიზნესი), დაგეგმეთ EU/UK/US სამუშაო საათები და მოამზადეთ B2B წინადადებები.'
              : 'Compare Georgian standard labor contracts (20% PIT + 2% pension) against 1% Small Business B2B exports, plan overlap from Tbilisi (UTC+4), and craft client-ready B2B outreach.'}
          </p>
        </div>

        <div className="flex items-center gap-2 self-start lg:self-center bg-slate-950 border border-slate-800 p-1.5 rounded-xl" role="group" aria-label="B2B Hub Language Switcher">
          <button
            type="button"
            onClick={() => setLang('en')}
            aria-pressed={lang === 'en'}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              lang === 'en' ? 'bg-emerald-700 text-white shadow' : 'text-slate-300 hover:text-white'
            }`}
          >
            English
          </button>
          <button
            type="button"
            onClick={() => setLang('ka')}
            aria-pressed={lang === 'ka'}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              lang === 'ka' ? 'bg-emerald-700 text-white shadow' : 'text-slate-300 hover:text-white'
            }`}
          >
            ქართული
          </button>
        </div>
      </div>

      {/* Section 1: Georgia 1% Small Business vs Standard Labor Calculator */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-5 glass-card rounded-2xl p-5 space-y-4">
          <div className="flex items-center gap-2.5 border-b border-slate-800 pb-3">
            <Calculator className="w-5 h-5 text-emerald-400" />
            <div>
              <h2 className="text-base font-bold text-white">
                {isKa ? 'შემოსავლის და 1% B2B გადასახადის კალკულატორი' : '1% B2B vs. Local Salary Net Calculator'}
              </h2>
              <p className="text-xs text-slate-300">
                {isKa ? 'ინდ. მეწარმე 1% (500,000 ₾-მდე) vs 20%+2%' : 'Georgian IE 1% Status vs Standard 20% + 2% Labor'}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="b2b-amount" className="block text-xs font-semibold text-slate-300 mb-1">
                {isKa ? 'თანხა (Amount)' : 'Offer / Rate Amount'}
              </label>
              <input
                id="b2b-amount"
                type="number"
                min={1}
                step={50}
                value={amount}
                onChange={(e) => setAmount(Math.max(1, Number(e.target.value) || 0))}
                className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white font-mono focus:border-emerald-500"
              />
            </div>

            <div>
              <label htmlFor="b2b-currency" className="block text-xs font-semibold text-slate-300 mb-1">
                {isKa ? 'ვალუტა' : 'Currency'}
              </label>
              <select
                id="b2b-currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value as 'USD' | 'EUR' | 'GBP' | 'GEL')}
                className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white focus:border-emerald-500"
              >
                <option value="USD">USD ($)</option>
                <option value="EUR">EUR (€)</option>
                <option value="GBP">GBP (£)</option>
                <option value="GEL">GEL (₾)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            <div>
              <label htmlFor="b2b-period" className="block text-xs font-semibold text-slate-300 mb-1">
                {isKa ? 'პერიოდი' : 'Billing'}
              </label>
              <select
                id="b2b-period"
                value={billingPeriod}
                onChange={(e) => setBillingPeriod(e.target.value as 'monthly' | 'hourly' | 'annual')}
                className="w-full bg-slate-950 border border-slate-700 rounded-xl px-2.5 py-2 text-xs text-white"
              >
                <option value="monthly">{isKa ? 'თვიური' : 'Monthly'}</option>
                <option value="hourly">{isKa ? 'საათობრივი' : 'Hourly (160h)'}</option>
                <option value="annual">{isKa ? 'წლიური' : 'Annual'}</option>
              </select>
            </div>

            <div>
              <label htmlFor="b2b-fx" className="block text-xs font-semibold text-slate-300 mb-1">
                {isKa ? 'კურსი (GEL)' : 'FX Rate -> GEL'}
              </label>
              <input
                id="b2b-fx"
                type="number"
                step="0.01"
                placeholder={currency === 'GEL' ? '1.00' : 'Auto'}
                value={fxOverride}
                onChange={(e) => setFxOverride(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 rounded-xl px-2.5 py-2 text-xs text-white font-mono placeholder-slate-400"
              />
            </div>

            <div>
              <label htmlFor="b2b-fee" className="block text-xs font-semibold text-slate-300 mb-1">
                {isKa ? 'ბანკი/Wise %' : 'FX/Bank Fee %'}
              </label>
              <input
                id="b2b-fee"
                type="number"
                min={0}
                max={5}
                step={0.1}
                value={transferFeePct}
                onChange={(e) => setTransferFeePct(Math.max(0, Math.min(5, Number(e.target.value) || 0)))}
                className="w-full bg-slate-950 border border-slate-700 rounded-xl px-2.5 py-2 text-xs text-white font-mono"
              />
            </div>
          </div>

          {taxResult && (
            <div className="space-y-3 pt-2" aria-live="polite">
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3.5 rounded-xl bg-emerald-950/40 border border-emerald-600/50 space-y-1">
                  <div className="text-[11px] font-bold uppercase text-emerald-300">
                    {isKa ? `B2B ინდ. მეწარმე (${taxResult.b2b_small_business.tax_rate_pct}%)` : `IE B2B (${taxResult.b2b_small_business.tax_rate_pct}% Tax)`}
                  </div>
                  <div className="text-lg font-extrabold text-white font-mono">
                    {taxResult.b2b_small_business.net_gel.toLocaleString()} ₾
                  </div>
                  <div className="text-xs text-emerald-300 font-mono">
                    {taxResult.currency !== 'GEL'
                      ? `${taxResult.b2b_small_business.net_orig.toLocaleString()} ${taxResult.currency} / mo`
                      : `~${taxResult.b2b_small_business.hourly_net_orig.toLocaleString()} ₾ / hr`}
                  </div>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-700 space-y-1">
                  <div className="text-[11px] font-bold uppercase text-slate-300">
                    {isKa ? 'შრომითი (20%+2%)' : 'Labor Contract (21.6%)'}
                  </div>
                  <div className="text-lg font-extrabold text-slate-200 font-mono">
                    {taxResult.standard_labor_contract.net_gel.toLocaleString()} ₾
                  </div>
                  <div className="text-xs text-slate-300 font-mono">
                    {taxResult.currency !== 'GEL'
                      ? `${taxResult.standard_labor_contract.net_orig.toLocaleString()} ${taxResult.currency} / mo`
                      : 'Net Monthly'}
                  </div>
                </div>
              </div>

              <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2 text-xs">
                <div className="flex items-center justify-between text-[11px] text-slate-300 border-b border-slate-800/80 pb-1.5">
                  <span>{isKa ? 'გამოყენებული კურსი:' : 'Applied FX Rate:'}</span>
                  <span className="font-mono text-emerald-300">
                    1 {taxResult.currency} = {taxResult.fx_to_gel.toFixed(4)} GEL (
                    {taxResult.fx_source === 'nbg_live'
                      ? `NBG Official${taxResult.fx_as_of ? ` ${taxResult.fx_as_of}` : ''}`
                      : taxResult.fx_source === 'custom'
                      ? 'Custom'
                      : 'Reference Rate'}
                    )
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-300 flex items-center gap-1.5">
                    <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                    <span>{isKa ? 'ყოველთვიური B2B დანაზოგი:' : 'Monthly B2B Net Advantage:'}</span>
                  </span>
                  <strong className="text-emerald-300 font-mono">
                    +{taxResult.monthly_b2b_advantage_gel.toLocaleString()} ₾ / mo
                  </strong>
                </div>

                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-slate-300">
                      {isKa ? '500,000 ₾ წლიური ლიმიტის გამოყენება:' : '500,000 GEL Annual 1% Cap Usage:'}
                    </span>
                    <span className={`font-mono font-bold ${taxResult.under_500k_cap ? 'text-emerald-300' : 'text-amber-300'}`}>
                      {taxResult.annual_gross_gel.toLocaleString()} ₾ ({taxResult.cap_usage_pct}%)
                    </span>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className={`h-full transition-all ${taxResult.under_500k_cap ? 'bg-emerald-500' : 'bg-amber-400'}`}
                      style={{ width: `${Math.min(100, taxResult.cap_usage_pct)}%` }}
                    />
                  </div>
                </div>
              </div>
              {taxLoading && <div className="text-[11px] text-slate-300">Updating figures...</div>}
            </div>
          )}
        </div>

        {/* Section 2: Tbilisi Timezone Overlap & Contractor Readiness */}
        <div className="lg:col-span-7 space-y-6">
          <div className="glass-card rounded-2xl p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2.5">
                <Clock className="w-5 h-5 text-cyan-400" />
                <div>
                  <h2 className="text-base font-bold text-white">
                    {isKa ? 'თბილისის დროის სარტყლის თანხვედრა (GET / UTC+4)' : 'Tbilisi Remote Timezone Overlap (UTC+4 · No DST)'}
                  </h2>
                  <p className="text-xs text-slate-300">
                    {isKa ? 'აირჩიეთ სასურველი სამუშაო გრაფიკი საქართველოს დროით' : 'Plan live standup & pair-testing overlap across global regions'}
                  </p>
                </div>
              </div>

              <div>
                <label htmlFor="tz-shift" className="sr-only">
                  Preferred Tbilisi Work Shift Start
                </label>
                <select
                  id="tz-shift"
                  value={shiftStart}
                  onChange={(e) => setShiftStart(Number(e.target.value))}
                  className="bg-slate-950 border border-slate-700 rounded-xl px-3 py-1.5 text-xs text-white font-semibold"
                >
                  <option value={10}>10:00–18:00 GET</option>
                  <option value={11}>11:00–19:00 GET (Balanced EU)</option>
                  <option value={12}>12:00–20:00 GET (Full EU + UK)</option>
                  <option value={14}>14:00–22:00 GET (EU + US Morning)</option>
                  <option value={16}>16:00–00:00 GET (US East Coast)</option>
                </select>
              </div>
            </div>

            {tzMatrix && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-300 uppercase text-[11px]">
                      <th scope="col" className="py-2 pr-3">{isKa ? 'რეგიონი' : 'Hiring Region'}</th>
                      <th scope="col" className="py-2 px-3">{isKa ? 'მათი 9–17 თბილისით' : 'Client 9–5 (Tbilisi)'}</th>
                      <th scope="col" className="py-2 px-3">{isKa ? 'თანხვედრა' : 'Your Overlap'}</th>
                      <th scope="col" className="py-2 pl-3">{isKa ? 'საუკეთესო გრაფიკი' : 'Optimal Shift'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {tzMatrix.regions.map((r) => (
                      <tr key={r.region} className="hover:bg-slate-900/50">
                        <td className="py-2 pr-3 font-semibold text-white">{r.region}</td>
                        <td className="py-2 px-3 font-mono text-slate-300">{r.client_hours_tbilisi_time}</td>
                        <td className="py-2 px-3">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-md font-semibold text-[11px] ${
                              r.overlap_hours_count >= 5
                                ? 'bg-emerald-950/70 text-emerald-300 border border-emerald-700/60'
                                : r.overlap_hours_count >= 2
                                ? 'bg-cyan-950/70 text-cyan-300 border border-cyan-700/60'
                                : 'bg-slate-900 text-slate-300 border border-slate-700'
                            }`}
                          >
                            {r.overlap_hours_count}h ({r.overlap_window_get})
                          </span>
                        </td>
                        <td className="py-2 pl-3 font-mono text-emerald-300">{r.recommended_shift_get}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Section 3: International B2B Readiness Checklist */}
          <div className="glass-card rounded-2xl p-5 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <h2 className="text-base font-bold text-white">
                  {isKa ? 'საერთაშორისო B2B მზადყოფნის ჩეკლისტი' : 'Global B2B Contractor Readiness Checklist'}
                </h2>
              </div>
              <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-700/60 font-mono">
                {readinessPct}% Ready ({completedCount}/{DEFAULT_READINESS_ITEMS.length})
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {DEFAULT_READINESS_ITEMS.map((item) => {
                const done = Boolean(completedChecklist[item.id]);
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => toggleChecklistItem(item.id)}
                    aria-pressed={done}
                    className={`text-left p-3 rounded-xl border transition-all flex items-start gap-2.5 ${
                      done
                        ? 'bg-emerald-950/30 border-emerald-600/50 text-white'
                        : 'bg-slate-950 border-slate-800 hover:border-slate-600 text-slate-200'
                    }`}
                  >
                    {done ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                    ) : (
                      <Circle className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                    )}
                    <div className="space-y-0.5">
                      <div className="text-xs font-bold">{isKa ? item.labelKa : item.labelEn}</div>
                      <p className="text-[11px] text-slate-300 leading-relaxed">
                        {isKa ? item.detailKa : item.detailEn}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Section 4: Direct B2B Client Proposal & Outreach Pitch Builder */}
      <div className="glass-card rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <Send className="w-5 h-5 text-emerald-400" />
            <div>
              <h2 className="text-base font-bold text-white">
                {isKa ? 'B2B კლიენტის შეთავაზების (Pitch) გენერატორი' : 'Direct Remote B2B Proposal & Cold Outreach Generator'}
              </h2>
              <p className="text-xs text-slate-300">
                {isKa
                  ? 'უსვამს ხაზს ვიზის გარეშე მუშაობას, UTC+4 დროის თანხვედრას და 1% B2B ინვოისინგს'
                  : 'Highlights zero visa overhead, UTC+4 timezone overlap, and verified Profile Vault skills'}
              </p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1 text-[11px] text-slate-300">
            <Info className="w-3.5 h-3.5 text-emerald-400" />
            Grounded exclusively in your saved Profile Vault skills
          </span>
        </div>

        <form onSubmit={handleGenerateProposal} className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label htmlFor="prop-role" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'პოზიცია' : 'Target Role'}
            </label>
            <input
              id="prop-role"
              type="text"
              required
              value={propRole}
              onChange={(e) => setPropRole(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            />
          </div>

          <div>
            <label htmlFor="prop-company" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'კომპანია / კლიენტი' : 'Company / Client'}
            </label>
            <input
              id="prop-company"
              type="text"
              required
              value={propCompany}
              onChange={(e) => setPropCompany(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            />
          </div>

          <div>
            <label htmlFor="prop-region" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'კლიენტის რეგიონი' : 'Client Timezone / Region'}
            </label>
            <input
              id="prop-region"
              type="text"
              value={propRegion}
              onChange={(e) => setPropRegion(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            />
          </div>

          <div>
            <label htmlFor="prop-rate" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'განაკვეთი (არასავალდებულო)' : 'B2B Rate (Optional)'}
            </label>
            <input
              id="prop-rate"
              type="text"
              value={propRate}
              onChange={(e) => setPropRate(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            />
          </div>

          <div className="md:col-span-3">
            <label htmlFor="prop-notes" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'ვაკანსიის მოკლე მოთხოვნები (არასავალდებულო)' : 'Key Requirements Snippet (Optional)'}
            </label>
            <input
              id="prop-notes"
              type="text"
              value={propNotes}
              onChange={(e) => setPropNotes(e.target.value)}
              placeholder="e.g. Playwright TypeScript E2E testing, REST API QA, GitHub Actions CI"
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white placeholder-slate-400"
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={propLoading}
              className="w-full py-2.5 px-4 rounded-xl btn-primary-emerald text-xs font-bold disabled:opacity-50"
            >
              {propLoading ? 'Drafting...' : isKa ? 'B2B წერილის შექმნა' : 'Generate B2B Pitch'}
            </button>
          </div>
        </form>

        {proposal && (
          <div className="p-4 rounded-xl bg-slate-950 border border-emerald-700/50 space-y-2.5" aria-live="polite">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="text-xs font-bold text-emerald-300">
                Subject: <span className="text-white">{proposal.subject}</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(`${proposal.subject}\n\n${proposal.proposal_text}`);
                  setCopiedProp(true);
                  setTimeout(() => setCopiedProp(false), 2500);
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-white border border-slate-700"
              >
                {copiedProp ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedProp ? 'Copied!' : 'Copy Subject & Pitch'}</span>
              </button>
            </div>
            <pre className="whitespace-pre-wrap text-xs text-slate-200 font-sans leading-relaxed">
              {proposal.proposal_text}
            </pre>
          </div>
        )}
      </div>

      {/* Section 5: Georgia 1% IE Monthly Contractor Invoice Generator */}
      <div className="glass-card rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2 border-b border-slate-800 pb-3">
          <div>
            <h2 className="text-base font-bold text-white">
              {isKa ? 'B2B ყოველთვიური ინვოისის გენერატორი (1% ინდ. მეწარმე)' : 'Georgia B2B Monthly Contractor Invoice Generator'}
            </h2>
            <p className="text-xs text-slate-300">
              {isKa
                ? 'ამზადებს უცხოელი კლიენტის ინვოისს NBG კურსით და 1% rs.ge დეკლარირებისთვის'
                : 'Creates client-ready USD/EUR invoices with live NBG GEL ledger conversion for rs.ge 1% declaration'}
            </p>
          </div>
        </div>

        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setInvLoading(true);
            try {
              const res = await generateB2BInvoice({
                client_name: invClient,
                service_description: invService,
                amount: invAmount,
                currency: invCurrency,
                payment_method: invMethod,
                iban_or_account: invAccount,
                language: lang,
              });
              setInvoicePreview(res);
            } catch {
              // ignored
            } finally {
              setInvLoading(false);
            }
          }}
          className="grid grid-cols-1 md:grid-cols-6 gap-3"
        >
          <div className="md:col-span-2">
            <label htmlFor="inv-client" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'კლიენტი / კომპანია' : 'Client Company'}
            </label>
            <input
              id="inv-client"
              type="text"
              required
              value={invClient}
              onChange={(e) => setInvClient(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            />
          </div>
          <div className="md:col-span-2">
            <label htmlFor="inv-service" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'სერვისის აღწერა' : 'Service Description'}
            </label>
            <input
              id="inv-service"
              type="text"
              required
              value={invService}
              onChange={(e) => setInvService(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            />
          </div>
          <div>
            <label htmlFor="inv-amount" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'თანხა' : 'Amount'}
            </label>
            <input
              id="inv-amount"
              type="number"
              min={1}
              value={invAmount}
              onChange={(e) => setInvAmount(Math.max(1, Number(e.target.value) || 0))}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white font-mono"
            />
          </div>
          <div>
            <label htmlFor="inv-currency" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'ვალუტა' : 'Currency'}
            </label>
            <select
              id="inv-currency"
              value={invCurrency}
              onChange={(e) => setInvCurrency(e.target.value as 'USD' | 'EUR' | 'GBP' | 'GEL')}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            >
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="GBP">GBP</option>
              <option value="GEL">GEL</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <label htmlFor="inv-method" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'გადახდის არხი' : 'Payment Rail'}
            </label>
            <input
              id="inv-method"
              type="text"
              value={invMethod}
              onChange={(e) => setInvMethod(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
            />
          </div>
          <div className="md:col-span-3">
            <label htmlFor="inv-iban" className="block text-xs font-semibold text-slate-300 mb-1">
              {isKa ? 'IBAN / SWIFT ან Wise ანგარიში (არასავალდებულო)' : 'IBAN / SWIFT or Wise Account (Optional)'}
            </label>
            <input
              id="inv-iban"
              type="text"
              value={invAccount}
              onChange={(e) => setInvAccount(e.target.value)}
              placeholder="GE00TB0000000000000000"
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white font-mono placeholder-slate-400"
            />
          </div>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={invLoading}
              className="w-full py-2.5 px-4 rounded-xl btn-primary-emerald text-xs font-bold disabled:opacity-50"
            >
              {invLoading ? 'Building...' : isKa ? 'ინვოისის შექმნა' : 'Generate Invoice'}
            </button>
          </div>
        </form>

        {invoicePreview && (
          <div className="p-4 rounded-xl bg-slate-950 border border-emerald-700/50 space-y-2.5" aria-live="polite">
            <div className="flex items-center justify-between gap-2 flex-wrap text-xs">
              <div className="font-bold text-emerald-300">
                {invoicePreview.invoice_number} • NBG Ledger: {invoicePreview.gel_equivalent.toLocaleString()} GEL (1% Tax: {invoicePreview.estimated_1pct_tax_gel.toLocaleString()} GEL)
              </div>
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(invoicePreview.invoice_text);
                  setCopiedInv(true);
                  setTimeout(() => setCopiedInv(false), 2500);
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-white border border-slate-700"
              >
                {copiedInv ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedInv ? 'Copied!' : 'Copy Invoice'}</span>
              </button>
            </div>
            <pre className="whitespace-pre-wrap text-xs text-slate-200 font-mono leading-relaxed">
              {invoicePreview.invoice_text}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
};
