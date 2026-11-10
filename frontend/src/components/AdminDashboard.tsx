import React, { useState, useEffect } from 'react';
import {
  ShieldAlert,
  Users,
  Briefcase,
  TrendingUp,
  Activity,
  Search,
  CheckCircle,
  XCircle,
  RefreshCw,
  Shield,
  UserCheck,
  UserX,
  Lock,
} from 'lucide-react';
import { fetchAdminMetrics, fetchAdminUsers, updateAdminUser, deactivateAdminUser } from '../services/api';
import { PlatformMetrics, AdminUser, UserProfile } from '../types';

interface AdminDashboardProps {
  currentUser: UserProfile | null;
}

export const AdminDashboard: React.FC<AdminDashboardProps> = ({ currentUser }) => {
  const [metrics, setMetrics] = useState<PlatformMetrics | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (currentUser?.is_admin) {
      loadData();
    } else {
      setLoading(false);
    }
  }, [currentUser]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [m, u] = await Promise.all([fetchAdminMetrics(), fetchAdminUsers()]);
      setMetrics(m);
      setUsers(u);
    } catch (err: any) {
      setError(err.message || 'Failed to load administrator data.');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleAdmin = async (user: AdminUser) => {
    try {
      const updated = await updateAdminUser(user.id, { is_admin: !user.is_admin });
      setUsers((prev) => prev.map((u) => (u.id === user.id ? updated : u)));
    } catch (err: any) {
      alert(err.message || 'Failed to toggle admin role');
    }
  };

  const handleToggleActive = async (user: AdminUser) => {
    try {
      if (user.is_active) {
        await deactivateAdminUser(user.id);
        setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, is_active: false } : u)));
      } else {
        const updated = await updateAdminUser(user.id, { is_active: true });
        setUsers((prev) => prev.map((u) => (u.id === user.id ? updated : u)));
      }
    } catch (err: any) {
      alert(err.message || 'Failed to change user status');
    }
  };

  // 403 Forbidden Gate for Non-Admin Users
  if (!currentUser || !currentUser.is_admin) {
    return (
      <div className="max-w-2xl mx-auto py-16 px-4 text-center space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-rose-950/50 border border-rose-900/80 flex items-center justify-center text-rose-400 mx-auto shadow-xl shadow-rose-950/50">
          <Lock className="w-8 h-8" />
        </div>
        <h2 className="text-xl font-bold text-white">403 Forbidden: Admin Access Required</h2>
        <p className="text-sm text-slate-400 max-w-md mx-auto">
          The Admin Management Dashboard is strictly restricted to platform administrators.
          You can initialize or promote an admin account safely via the terminal CLI script:
        </p>
        <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 text-left font-mono text-xs text-emerald-300 max-w-lg mx-auto overflow-x-auto">
          python backend/scripts/create_admin.py --email your.email@domain.com
        </div>
      </div>
    );
  }

  const filteredUsers = users.filter((u) =>
    u.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
    u.full_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 p-6 rounded-2xl">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-bold text-white">Dedicated Admin Dashboard</h2>
              <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800">
                Root Admin
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Platform-wide user management, conversion metrics, and system security controls
            </p>
          </div>
        </div>

        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 border border-slate-700 self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Data</span>
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-900/60 text-rose-300 text-xs flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Aggregate Metrics Cards */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-1">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase">Total Users</span>
              <Users className="w-4 h-4 text-sky-400" />
            </div>
            <div className="text-2xl font-extrabold text-white">{metrics.total_users}</div>
            <div className="text-[11px] text-emerald-400 font-medium">
              {metrics.active_users} Active • {metrics.admin_users} Admins
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-1">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase">Tracked Apps</span>
              <Briefcase className="w-4 h-4 text-blue-400" />
            </div>
            <div className="text-2xl font-extrabold text-white">{metrics.total_tracked_applications}</div>
            <div className="text-[11px] text-slate-400">
              Across Kanban pipeline
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-1">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase">Interview Conversion</span>
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-2xl font-extrabold text-emerald-400">
              {metrics.interview_conversion_rate}%
            </div>
            <div className="text-[11px] text-slate-400">
              Applications reaching interview stage
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-1">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-semibold uppercase">AI Engine Status</span>
              <Activity className="w-4 h-4 text-indigo-400" />
            </div>
            <div className="text-sm font-bold text-white capitalize flex items-center gap-1.5 pt-1">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
              <span>{metrics.gemini_api_status}</span>
            </div>
            <div className="text-[11px] text-slate-400">
              {metrics.total_discovered_jobs} Vacancies Ingested
            </div>
          </div>
        </div>
      )}

      {/* User Management Section */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-white">Registered Users & RBAC Permissions</h3>
            <p className="text-xs text-slate-400">
              View registered users, application activities, and manage platform roles
            </p>
          </div>

          <div className="relative w-full sm:w-64">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by name or email..."
              className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-white focus:outline-none focus:border-sky-500"
            />
          </div>
        </div>

        {/* Responsive Table */}
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/80 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">User</th>
                <th className="py-3 px-4">Role</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Tracked Apps</th>
                <th className="py-3 px-4">Registered</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filteredUsers.map((u) => (
                <tr key={u.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="py-3 px-4">
                    <div className="font-semibold text-white">{u.full_name}</div>
                    <div className="text-[11px] text-slate-400">{u.email}</div>
                  </td>
                  <td className="py-3 px-4">
                    {u.is_admin ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-950 text-amber-300 border border-amber-800">
                        <Shield className="w-3 h-3" />
                        Admin
                      </span>
                    ) : (
                      <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">
                        Candidate
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4">
                    {u.is_active ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-400">
                        <CheckCircle className="w-3.5 h-3.5" />
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-rose-400">
                        <XCircle className="w-3.5 h-3.5" />
                        Deactivated
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-slate-300 font-mono">
                    {u.application_count}
                  </td>
                  <td className="py-3 px-4 text-slate-400 text-[11px]">
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => handleToggleAdmin(u)}
                        disabled={u.id === currentUser.id}
                        title={u.is_admin ? 'Revoke Admin' : 'Make Admin'}
                        className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-medium disabled:opacity-30"
                      >
                        {u.is_admin ? 'Demote' : 'Promote'}
                      </button>
                      <button
                        onClick={() => handleToggleActive(u)}
                        disabled={u.id === currentUser.id}
                        title={u.is_active ? 'Deactivate User' : 'Reactivate User'}
                        className={`p-1 rounded-lg text-[11px] disabled:opacity-30 ${
                          u.is_active
                            ? 'bg-rose-950/40 text-rose-400 hover:bg-rose-900/60'
                            : 'bg-emerald-950/40 text-emerald-400 hover:bg-emerald-900/60'
                        }`}
                      >
                        {u.is_active ? <UserX className="w-3.5 h-3.5" /> : <UserCheck className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filteredUsers.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-500 italic text-xs">
                    No users matching "{searchQuery}"
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
