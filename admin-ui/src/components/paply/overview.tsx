import { ArrowDownToLine, ArrowUpFromLine, Bot, CircleDollarSign, MessageSquare, Users } from 'lucide-react';
import { useOverview } from '@/api/admin';
import { PageError, PageLoading } from './page-state';

const cards = [
  { key: 'requests', title: '请求统计', icon: MessageSquare },
  { key: 'tokens', title: 'Token 统计', icon: Bot },
  { key: 'input', title: '输入统计', icon: ArrowDownToLine },
  { key: 'output', title: '输出与费用', icon: ArrowUpFromLine },
] as const;

export function OverviewPage() {
  const query = useOverview();
  if (query.isLoading) return <PageLoading />;
  if (query.error || !query.data) return <PageError error={query.error ?? new Error('概览数据为空')} retry={() => void query.refetch()} />;
  const data = query.data;
  const values = {
    requests: [['请求次数', data.request_count], ['成功 / 失败', `${data.successful_request_count} / ${data.failed_request_count}`]],
    tokens: [['总 Token', data.total_tokens], ['模型组 / 节点', `${data.model_group_count} / ${data.deployment_count}`]],
    input: [['输入 Tokens', data.prompt_tokens], ['计量用户', String(data.user_count)]],
    output: [['输出 Tokens', data.completion_tokens], ['累计费用', data.total_spend]],
  } as const;

  return (
    <div className="h-full min-h-0 space-y-6 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <section key={card.key} className="flex items-center gap-4 rounded-3xl border border-border bg-card p-5 text-card-foreground">
            <div className="flex self-stretch flex-col items-center justify-center gap-3 border-r border-border/50 py-1 pr-4">
              <card.icon className="size-4" />
              <h2 className="text-sm font-medium [writing-mode:vertical-lr]">{card.title}</h2>
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-4">
              {values[card.key].map(([label, value]) => (
                <div key={label} className="flex items-center gap-3">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    {label.includes('用户') ? <Users className="size-5" /> : label.includes('费用') ? <CircleDollarSign className="size-5" /> : <card.icon className="size-5" />}
                  </div>
                  <div className="min-w-0"><p className="text-xs text-muted-foreground">{label}</p><p className="truncate text-xl">{value}</p></div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <section className="rounded-3xl border border-border bg-card p-5">
        <header className="mb-5 flex items-end justify-between gap-4">
          <div><h2 className="text-lg font-bold">模型组状态</h2><p className="mt-1 text-sm text-muted-foreground">稳定别名与当前 LiteLLM 节点池</p></div>
          <span className="text-xs text-muted-foreground">{data.updated_at}</span>
        </header>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {data.model_groups.map((group) => (
            <article key={group.name} className="rounded-2xl border border-border/60 bg-muted/30 p-4">
              <div className="flex items-center justify-between gap-3"><strong className="truncate">{group.name}</strong><span className="rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary">{group.active_count} 启用</span></div>
              <p className="mt-2 text-xs text-muted-foreground">共 {group.deployment_count} 个节点 · simple-shuffle</p>
            </article>
          ))}
        </div>
      </section>

      <section className="rounded-3xl border border-border bg-card p-5">
        <header className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-bold">预算概览</h2><p className="mt-1 text-sm text-muted-foreground">统计周期：{data.activity_period}</p></div><strong>{data.total_budget}</strong></header>
        <div className="space-y-3">
          {data.users.map((user) => (
            <div key={user.user_id} className="grid items-center gap-3 rounded-2xl bg-muted/30 p-3 md:grid-cols-[minmax(0,1fr)_auto_180px]">
              <div className="min-w-0"><strong className="block truncate text-sm">{user.alias}</strong><span className="block truncate text-xs text-muted-foreground">{user.user_id}</span></div>
              <span className="text-sm">{user.spend} / {user.budget}</span>
              <div className="h-2 overflow-hidden rounded-full bg-secondary"><span className="block h-full rounded-full bg-primary" style={{ width: `${user.budget_percent}%` }} /></div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
