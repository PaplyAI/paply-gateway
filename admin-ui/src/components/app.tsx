import { lazy, Suspense, useDeferredValue, useEffect, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useAuth } from '@/api/user';
import { AppShell } from '@/components/app-shell';
import { LoginForm } from '@/components/modules/login';
import { pageImports } from '@/lib/page-preload';
import { useAppStore } from '@/stores/app';

const OverviewPage = lazy(() => pageImports.home().then((module) => ({ default: module.OverviewPage })));
const UsersPage = lazy(() => pageImports.users().then((module) => ({ default: module.UsersPage })));
const ModelsPage = lazy(() => pageImports.models().then((module) => ({ default: module.ModelsPage })));
const ModelsActions = lazy(() => pageImports.models().then((module) => ({ default: module.ModelsActions })));
const SystemPage = lazy(() => pageImports.system().then((module) => ({ default: module.SystemPage })));

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
  const visiblePage = useDeferredValue(currentPage);

  useEffect(() => {
    window.addEventListener('popstate', syncFromLocation);
    return () => window.removeEventListener('popstate', syncFromLocation);
  }, [syncFromLocation]);

  if (isLoading) return null;
  if (!isAuthenticated) return <InitialLoadingGate><LoginForm /></InitialLoadingGate>;

  return (
    <InitialLoadingGate>
      <AppShell actions={visiblePage === 'models' ? <Suspense fallback={null}><ModelsActions /></Suspense> : undefined}>
        <AnimatePresence mode="sync">
          <motion.div
            key={visiblePage}
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1, transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] } }}
            exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.18 } }}
            className="absolute inset-0 min-h-0 overflow-hidden"
          >
            <Suspense fallback={null}>
              {visiblePage === 'home' ? <OverviewPage /> : null}
              {visiblePage === 'users' ? <UsersPage /> : null}
              {visiblePage === 'models' ? <ModelsPage /> : null}
              {visiblePage === 'system' ? <SystemPage /> : null}
            </Suspense>
          </motion.div>
        </AnimatePresence>
      </AppShell>
    </InitialLoadingGate>
  );
}
