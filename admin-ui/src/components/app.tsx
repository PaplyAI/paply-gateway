import { useEffect, type ReactNode } from 'react';
import { useAuth } from '@/api/user';
import { AppShell } from '@/components/app-shell';
import { LoginForm } from '@/components/modules/login';
import { ModelsActions, ModelsPage } from '@/components/paply/models';
import { OverviewPage } from '@/components/paply/overview';
import { SystemPage } from '@/components/paply/system';
import { UsersPage } from '@/components/paply/users';
import { useAppStore } from '@/stores/app';

function InitialLoadingGate({ children }: { children: ReactNode }) {
  useEffect(() => {
    const loader = document.getElementById('initial-loader');
    if (!loader || loader.dataset.state === 'hidden') return;
    loader.dataset.state = 'hidden';
    loader.classList.add('octo-hide');
    window.setTimeout(() => loader.remove(), 220);
  }, []);

  return children;
}

export function AppContainer() {
  const { isAuthenticated, isLoading } = useAuth();
  const currentPage = useAppStore((state) => state.currentPage);
  const syncFromLocation = useAppStore((state) => state.syncFromLocation);

  useEffect(() => {
    window.addEventListener('popstate', syncFromLocation);
    return () => window.removeEventListener('popstate', syncFromLocation);
  }, [syncFromLocation]);

  if (isLoading) return null;
  if (!isAuthenticated) return <InitialLoadingGate><LoginForm /></InitialLoadingGate>;

  return (
    <InitialLoadingGate>
      <AppShell actions={currentPage === 'models' ? <ModelsActions /> : undefined}>
        <div className="absolute inset-0 min-h-0 overflow-hidden">
          {currentPage === 'home' ? <OverviewPage /> : null}
          {currentPage === 'users' ? <UsersPage /> : null}
          {currentPage === 'models' ? <ModelsPage /> : null}
          {currentPage === 'system' ? <SystemPage /> : null}
        </div>
      </AppShell>
    </InitialLoadingGate>
  );
}
