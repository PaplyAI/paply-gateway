import type { LucideIcon } from 'lucide-react';
import { ArrowDownToLine, ArrowUpFromLine, Bot, CircleDollarSign, MessageSquare } from 'lucide-react';
import { useOverview } from '@/api/admin';
import { PageError, PageLoading } from './page-state';

interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  secondaryLabel: string;
  secondaryValue: string;
}

function MetricCard({ icon: Icon, label, value, secondaryLabel, secondaryValue }: MetricCardProps) {
  return (
    <article className="rounded-2xl border border-border bg-card p-4 text-card-foreground">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <strong className="mt-2 block truncate text-2xl font-semibold tracking-tight">{value}</strong>
        </div>
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <Icon className="size-4" />
        </span>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-border/60 pt-3 text-xs">
        <span className="text-muted-foreground">{secondaryLabel}</span>
        <span className="truncate font-medium">{secondaryValue}</span>
      </div>
    </article>
  );
}

export function OverviewPage() {
  const query = useOverview();
  if (query.isLoading) return <PageLoading />;
  if (query.error || !query.data) return <PageError error={query.error ?? new Error('概览数据为空')} retry={() => void query.refetch()} />;
  const data = query.data;

  const metrics: MetricCardProps[] = [
    { icon: MessageSquare, label: '请求次数', value: data.request_count, secondaryLabel: '成功 / 失败', secondaryValue: `${data.successful_request_count} / ${data.failed_request_count}` },
    { icon: Bot, label: '总 Token', value: data.total_tokens, secondaryLabel: '模型组 / 节点', secondaryValue: `${data.model_group_count} / ${data.deployment_count}` },
    { icon: ArrowDownToLine, label: '输入 Tokens', value: data.prompt_tokens, secondaryLabel: '计量用户', secondaryValue: String(data.user_count) },
    { icon: ArrowUpFromLine, label: '输出 Tokens', value: data.completion_tokens, secondaryLabel: '累计费用', secondaryValue: data.total_spend },
  ];

  return (
    <div className="h-full min-h-0 space-y-5 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => <MetricCard key={metric.label} {...metric} />)}
      </div>

      <section className="rounded-2xl border border-border bg-card">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-5 py-4">
          <div><h2 className="font-semibold">模型组状态</h2><p className="mt-0.5 text-xs text-muted-foreground">稳定别名与当前 LiteLLM 节点池</p></div>
          <span className="text-xs text-muted-foreground">{data.updated_at}</span>
        </header>
        <div className="divide-y divide-border/60 px-5">
          {data.model_groups.map((group) => (
            <div key={group.name} className="grid items-center gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:gap-6">
              <strong className="truncate text-sm">{group.name}</strong>
              <span className="text-xs text-muted-foreground">{group.deployment_count} 个节点</span>
              <span className="w-fit rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary">{group.active_count} 启用</span>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-card">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-5 py-4">
          <div><h2 className="font-semibold">预算概览</h2><p className="mt-0.5 text-xs text-muted-foreground">统计周期：{data.activity_period}</p></div>
          <strong className="inline-flex items-center gap-1.5 text-sm"><CircleDollarSign className="size-4 text-primary" />{data.total_budget}</strong>
        </header>
        <div className="divide-y divide-border/60 px-5">
          {data.users.map((user) => (
            <div key={user.user_id} className="grid items-center gap-3 py-3 md:grid-cols-[minmax(0,1fr)_auto_180px]">
              <div className="min-w-0"><strong className="block truncate text-sm">{user.alias}</strong><span className="block truncate text-xs text-muted-foreground">{user.user_id}</span></div>
              <span className="text-sm tabular-nums">{user.spend} / {user.budget}</span>
              <div className="h-1.5 overflow-hidden rounded-full bg-secondary"><span className="block h-full rounded-full bg-primary" style={{ width: `${user.budget_percent}%` }} /></div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
