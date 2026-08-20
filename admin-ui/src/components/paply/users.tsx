import { useState } from 'react';
import { Ban, CircleDollarSign, Pencil, Users } from 'lucide-react';
import { toast } from 'sonner';
import type { AdminUser, UserBudgetInput } from '@/api/admin';
import { useUpdateUser, useUsers } from '@/api/admin';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  MorphingDialog, MorphingDialogClose, MorphingDialogContainer, MorphingDialogContent,
  MorphingDialogTrigger, useMorphingDialog,
} from '@/components/ui/morphing-dialog';
import { EmptyState, PageError, PageLoading } from './page-state';

function UserBudgetForm({ user }: { user: AdminUser }) {
  const mutation = useUpdateUser();
  const { setIsOpen } = useMorphingDialog();
  const [form, setForm] = useState<UserBudgetInput>({
    max_budget: String(user.budget_value), budget_duration: user.duration,
    rpm_limit: String(user.rpm_limit || ''), tpm_limit: String(user.tpm_limit || ''),
    max_parallel_requests: String(user.max_parallel_requests || ''), blocked: user.blocked,
  });
  const update = (key: keyof UserBudgetInput, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }));
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const result = await mutation.mutateAsync({ userId: user.user_id, input: form });
      toast.success(result.message);
      setIsOpen(false);
    } catch (cause: unknown) {
      toast.error(cause instanceof Error ? cause.message : '更新失败');
    }
  };
  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="pr-10"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">用户预算</p><h2 className="mt-1 text-xl font-bold">{user.alias}</h2><p className="truncate text-xs text-muted-foreground">{user.user_id}</p></div>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2"><Label>预算上限（USD）</Label><Input value={form.max_budget} onChange={(e) => update('max_budget', e.target.value)} required /></label>
        <label className="space-y-2"><Label>预算周期</Label><Input value={form.budget_duration} onChange={(e) => update('budget_duration', e.target.value)} placeholder="30d" required /></label>
        <label className="space-y-2"><Label>RPM</Label><Input value={form.rpm_limit} onChange={(e) => update('rpm_limit', e.target.value)} placeholder="不限制" /></label>
        <label className="space-y-2"><Label>TPM</Label><Input value={form.tpm_limit} onChange={(e) => update('tpm_limit', e.target.value)} placeholder="不限制" /></label>
        <label className="space-y-2"><Label>最大并发</Label><Input value={form.max_parallel_requests} onChange={(e) => update('max_parallel_requests', e.target.value)} placeholder="不限制" /></label>
        <div className="flex items-center justify-between rounded-xl border border-border px-3"><Label htmlFor={`blocked-${user.user_id}`}>暂停模型访问</Label><Switch id={`blocked-${user.user_id}`} checked={form.blocked} onCheckedChange={(checked) => update('blocked', checked)} /></div>
      </div>
      <div className="flex justify-end gap-2"><MorphingDialogClose className="static rounded-xl border border-border px-4 py-2 text-sm">取消</MorphingDialogClose><Button type="submit" className="rounded-xl" disabled={mutation.isPending}>{mutation.isPending ? '保存中…' : '保存设置'}</Button></div>
    </form>
  );
}

export function UsersPage() {
  const query = useUsers();
  if (query.isLoading) return <PageLoading />;
  if (query.error || !query.data) return <PageError error={query.error ?? new Error('用户数据为空')} retry={() => void query.refetch()} />;
  const data = query.data;
  return (
    <div className="h-full min-h-0 space-y-5 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">
      <div className="grid gap-4 md:grid-cols-3">
        {[['计量用户', data.user_count, Users], ['已分配预算', data.total_budget, CircleDollarSign], ['累计消费', data.total_spend, CircleDollarSign]].map(([label, value, Icon]) => {
          const CardIcon = Icon as typeof Users;
          return <section key={String(label)} className="flex items-center justify-between rounded-3xl border border-border bg-card p-5"><div><p className="text-sm text-muted-foreground">{String(label)}</p><strong className="mt-5 block text-3xl">{String(value)}</strong></div><span className="grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary"><CardIcon className="size-5" /></span></section>;
        })}
      </div>
      {data.users.length === 0 ? <EmptyState title="暂无计量用户" description="用户首次登录后会自动出现在这里。" /> : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.users.map((user) => (
            <article key={user.user_id} className="flex min-h-64 flex-col rounded-3xl border border-border bg-card p-5">
              <header className="flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="truncate text-lg font-bold">{user.alias}</h2><p className="truncate text-xs text-muted-foreground">{user.user_id}</p></div><MorphingDialog><MorphingDialogTrigger ariaLabel={`编辑用户 ${user.alias}`} className="rounded-xl p-2 text-muted-foreground hover:bg-muted hover:text-foreground"><Pencil className="size-4" /></MorphingDialogTrigger><MorphingDialogContainer><MorphingDialogContent className="relative w-[calc(100vw-2rem)] max-w-2xl rounded-3xl border border-border bg-card p-6"><UserBudgetForm user={user} /></MorphingDialogContent></MorphingDialogContainer></MorphingDialog></header>
              <div className="mt-6"><div className="flex items-end justify-between"><span className="text-sm text-muted-foreground">费用 / 预算</span><strong>{user.spend} / {user.budget}</strong></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-secondary"><span className="block h-full rounded-full bg-primary" style={{ width: `${user.budget_percent}%` }} /></div></div>
              <div className="mt-5 flex flex-wrap gap-2">{user.models.map((model) => <span key={model} className="rounded-lg bg-muted px-2 py-1 text-xs">{model}</span>)}</div>
              <footer className="mt-auto flex items-center justify-between pt-5 text-xs text-muted-foreground"><span>{user.duration} · {user.role}</span>{user.blocked && <span className="inline-flex items-center gap-1 text-destructive"><Ban className="size-3" />已暂停</span>}</footer>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
