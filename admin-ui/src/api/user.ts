import { useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { create } from 'zustand';
import { apiRequest, apiUnauthorizedEvent, setCSRFToken } from './client';

interface UserLoginRequest {
  username: string;
  password: string;
}

export interface AdminSession {
  authenticated: boolean;
  username?: string;
  csrf_token?: string;
  version?: string;
  allowed_models?: string[];
  litellm_ui_url?: string | null;
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  session: AdminSession | null;
  setAuth: (session: AdminSession) => void;
  checkAuth: () => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  isAuthenticated: false,
  isLoading: true,
  session: null,
  setAuth: (session) => {
    setCSRFToken(session.csrf_token ?? null);
    if (window.location.pathname === '/login' || window.location.pathname === '/') {
      window.history.replaceState({}, '', '/overview');
    }
    set({ isAuthenticated: true, isLoading: false, session });
  },
  checkAuth: async () => {
    try {
      const session = await apiRequest<AdminSession>('/api/admin/session', {
        dispatchUnauthorized: false,
      });
      if (!session.authenticated) {
        get().logout();
        return;
      }
      get().setAuth(session);
    } catch {
      get().logout();
    }
  },
  logout: () => {
    setCSRFToken(null);
    set({ isAuthenticated: false, isLoading: false, session: null });
  },
}));

export function useLogin() {
  const setAuth = useAuthStore((state) => state.setAuth);
  return useMutation({
    mutationFn: (data: UserLoginRequest) => apiRequest<AdminSession>('/api/admin/session', {
      method: 'POST',
      body: data,
      dispatchUnauthorized: false,
    }),
    onSuccess: setAuth,
  });
}

export function useLogout() {
  const logout = useAuthStore((state) => state.logout);
  return useMutation({
    mutationFn: () => apiRequest<AdminSession>('/api/admin/session', { method: 'DELETE' }),
    onSettled: logout,
  });
}

export function useAuth() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);

  useEffect(() => {
    const handleUnauthorized = () => useAuthStore.getState().logout();
    window.addEventListener(apiUnauthorizedEvent, handleUnauthorized);
    void useAuthStore.getState().checkAuth();
    return () => window.removeEventListener(apiUnauthorizedEvent, handleUnauthorized);
  }, []);

  return { isAuthenticated, isLoading };
}
