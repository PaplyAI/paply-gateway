import { create } from 'zustand';
import type { LucideIcon } from 'lucide-react';
import { FolderTree, Home, Settings, Users } from 'lucide-react';

// Page 表示应用支持的固定页面集合。
export type Page = 'home' | 'users' | 'models' | 'system';

// NavItem 描述导航按钮使用的页面标识、文案和图标。
type NavItem = { id: Page; label: string; icon: LucideIcon };

// NAV_ITEMS 是桌面和移动导航共用的固定导航定义。
export const NAV_ITEMS: NavItem[] = [
    { id: 'home', label: '运行概览', icon: Home },
    { id: 'users', label: '用户与预算', icon: Users },
    { id: 'models', label: '模型与节点', icon: FolderTree },
    { id: 'system', label: '系统状态', icon: Settings },
];

const PAGE_PATHS: Record<Page, string> = {
    home: '/overview',
    users: '/users',
    models: '/models',
    system: '/system',
};

export function pageFromPath(pathname: string): Page {
    const entry = Object.entries(PAGE_PATHS).find(([, path]) => path === pathname);
    return (entry?.[0] as Page | undefined) ?? 'home';
}

interface AppState {
    currentPage: Page; // 当前选中的固定页面。
    setCurrentPage: (page: Page) => void; // 切换当前页面。
    syncFromLocation: () => void;
}

// useAppStore 保存应用当前页面及页面名称切换方向。
export const useAppStore = create<AppState>((set, get) => ({
    currentPage: pageFromPath(window.location.pathname),
    setCurrentPage: (page) => {
        if (page === get().currentPage) return;
        window.history.pushState({}, '', PAGE_PATHS[page]);
        set({ currentPage: page });
    },
    syncFromLocation: () => {
        const page = pageFromPath(window.location.pathname);
        set({ currentPage: page });
    },
}));
