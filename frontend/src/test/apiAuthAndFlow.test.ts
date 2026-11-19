import { describe, it, expect, vi } from 'vitest';
import { apiFetch, loginUser, logoutUser, BACKEND_ORIGIN } from '../services/api';

describe('API Auth, Single-Flight Refresh, and Logout', () => {
  it('loginUser stores access token cleanly without storing refresh token in localStorage', async () => {
    localStorage.setItem('talentflow_refresh_token', 'legacy-stale-token');
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: 'access-jwt-123',
          token_type: 'bearer',
          user: {
            id: 1,
            email: 'nino@example.ge',
            full_name: 'Nino Beridze',
            is_active: true,
            is_admin: false,
            has_gmail_oauth: false,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    );

    const auth = await loginUser('nino@example.ge', 'StrongPass123!');
    expect(auth.user.email).toBe('nino@example.ge');
    expect(localStorage.getItem('talentflow_token')).toBe('access-jwt-123');
    expect(localStorage.getItem('talentflow_refresh_token')).toBeNull();
    expect(fetchSpy).toHaveBeenCalledWith(
      `${BACKEND_ORIGIN}/api/auth/login`,
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    );
  });

  it('apiFetch refreshes token via HttpOnly cookie on 401 and retries original request', async () => {
    localStorage.setItem('talentflow_token', 'expired-access-token');
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('Unauthorized', { status: 401 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: 'fresh-access-token',
            token_type: 'bearer',
            user: { id: 1, email: 'nino@example.ge', full_name: 'Nino', is_active: true, is_admin: false, has_gmail_oauth: false },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    const res = await apiFetch(`${BACKEND_ORIGIN}/api/applications`);
    expect(res.status).toBe(200);
    expect(localStorage.getItem('talentflow_token')).toBe('fresh-access-token');
    expect(fetchSpy).toHaveBeenCalledTimes(3);
    expect(fetchSpy.mock.calls[1][0]).toBe(`${BACKEND_ORIGIN}/api/auth/refresh`);
    expect(fetchSpy.mock.calls[1][1]).toEqual(expect.objectContaining({ credentials: 'include' }));
  });

  it('dispatches talentflow:auth-expired and logs out when refresh fails, and logoutUser revokes server cookie', async () => {
    localStorage.setItem('talentflow_token', 'expired-access-token');
    const expiredSpy = vi.fn();
    window.addEventListener('talentflow:auth-expired', expiredSpy);

    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('Unauthorized', { status: 401 }))
      .mockResolvedValueOnce(new Response('Refresh Expired', { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'logged_out' }), { status: 200 }));

    const res = await apiFetch(`${BACKEND_ORIGIN}/api/ground-truth`);
    expect(res.status).toBe(401);
    expect(expiredSpy).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('talentflow_token')).toBeNull();

    logoutUser();
    expect(fetchSpy).toHaveBeenLastCalledWith(
      `${BACKEND_ORIGIN}/api/auth/logout`,
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    );
    window.removeEventListener('talentflow:auth-expired', expiredSpy);
  });
});
