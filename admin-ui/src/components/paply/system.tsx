import { Activity, ExternalLink, LogOut, Server, ShieldCheck, Timer } from 'lucide-react';
import { useSystem } from '@/api/admin';
import { useAuthStore, useLogout } from '@/api/user';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { PageError, PageLoading } from './page-state';

export function SystemPage() {
  const query = useSystem();
  const session = useAuthStore((state) => state.session);
  const logout = useLogout();

  if (query.isLoading) return <PageLoading />;
  if (query.error || !query.data) {
    return <PageError error={query.error ?? new Error('系统状态为空')} retry={() => void query.refetch()} />;
  }

  const data = query.data;

  return (
    <div className="h-full min-h-0 space-y-5 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">
      <section className="grid gap-4 md:grid-cols-2">
        {data.components.map((component) => (
          <article key={component.name} className="rounded-3xl border border-border bg-card p-5 text-card-foreground">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">SERVICE</p>
                <h2 className="mt-2 truncate text-lg font-bold">{component.name}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{component.description}</p>
              </div>
              <span className={cn('grid size-11 shrink-0 place-items-center rounded-2xl', component.healthy ? 'bg-primary/10 text-primary' : 'bg-destructive/10 text-destructive')}>
                {component.healthy ? <ShieldCheck className="size-5" /> : <Server className="size-5" />}
              </span>
            </div>
            <div className="mt-6 flex items-center justify-between rounded-2xl bg-muted/40 px-4 py-3 text-sm">
              <span className={component.healthy ? 'text-primary' : 'text-destructive'}>{component.healthy ? '运行正常' : `异常 · ${component.status}`}</span>
              <span className="inline-flex items-center gap-1.5 text-muted-foreground"><Timer className="size-3.5" />{component.latency_ms} ms</span>
            </div>
          </article>
        ))}
      </section>

      <section className="rounded-3xl border border-border bg-card p-5">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">PAPLY GATEWAY</p>
            <h2 className="mt-2 text-xl font-bold">管理端信息</h2>
            <p className="mt-1 text-sm text-muted-foreground">当前页面只管理 Gateway 控制面；LiteLLM 继续承载模型数据面。</p>
          </div>
          <span className={cn('inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm', data.healthy ? 'bg-primary/10 text-primary' : 'bg-destructive/10 text-destructive')}>
            <Activity className="size-4" />{data.healthy ? '全部服务可用' : '存在异常服务'}
          </span>
        </header>

        <dl className="mt-6 grid gap-3 text-sm md:grid-cols-3">
          <div className="rounded-2xl bg-muted/40 p-4"><dt className="text-muted-foreground">管理员</dt><dd className="mt-2 font-medium">{session?.username ?? '—'}</dd></div>
          <div className="rounded-2xl bg-muted/40 p-4"><dt className="text-muted-foreground">Gateway 版本</dt><dd className="mt-2 font-medium">{session?.version ?? '—'}</dd></div>
          <div className="rounded-2xl bg-muted/40 p-4"><dt className="text-muted-foreground">状态更新时间</dt><dd className="mt-2 font-medium">{data.updated_at}</dd></div>
        </dl>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-5">
          <div className="flex flex-wrap gap-2">
            {session?.litellm_ui_url ? <Button asChild variant="outline" className="rounded-xl"><a href={session.litellm_ui_url} target="_blank" rel="noreferrer">LiteLLM 高级控制台<ExternalLink className="size-4" /></a></Button> : null}
            <Button asChild variant="outline" className="rounded-xl"><a href="https://github.com/bestruirui/octopus" target="_blank" rel="noreferrer">界面上游与许可<ExternalLink className="size-4" /></a></Button>
          </div>
          <Button variant="destructive" className="rounded-xl" onClick={() => logout.mutate()} disabled={logout.isPending}><LogOut className="size-4" />{logout.isPending ? '退出中…' : '退出登录'}</Button>
        </div>
      </section>
    </div>
  );
}
