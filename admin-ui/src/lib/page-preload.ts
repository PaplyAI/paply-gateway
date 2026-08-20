import type { Page } from '@/stores/app';

export const pageImports = {
  home: () => import('@/components/paply/overview'),
  users: () => import('@/components/paply/users'),
  models: () => import('@/components/paply/models'),
  system: () => import('@/components/paply/system'),
} satisfies Record<Page, () => Promise<unknown>>;

export function preloadPage(page: Page) {
  void pageImports[page]();
}
