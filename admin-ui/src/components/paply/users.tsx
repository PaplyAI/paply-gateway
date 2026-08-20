import { useState } from 'react';
import { Ban, CircleDollarSign, Pencil, Users } from 'lucide-react';
import { toast } from 'sonner';
import type { AdminUser, UserBudgetInput } from '@/api/admin';
import { useUpdateUser, useUsers } from '@/api/admin';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { EmptyState, PageError, PageLoading } from './page-state';

function UserBudgetForm({ user, onSaved }: { user: AdminUser; onSaved: () => void }) {
  const mutation = useUpdateUser();
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
      onSaved();
    } catch (cause: unknown) {
      toast.error(cause instanceof Error ? cause.message : '更新失败');
    }
  };
  return (
    <form onSubmit={submit}>
      <DialogHeader>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">用户预算</p>
        <DialogTitle>{user.alias}</DialogTitle>
        <DialogDescription className="truncate">{user.user_id}</DialogDescription>
      </DialogHeader>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2"><Label>预算上限（USD）</Label><Input value={form.max_budget} onChange={(e) => update('max_budget', e.target.value)} required /></label>
        <label className="space-y-2"><Label>预算周期</Label><Input value={form.budget_duration} onChange={(e) => update('budget_duration', e.target.value)} placeholder="30d" required /></label>
        <label className="space-y-2"><Label>RPM</Label><Input value={form.rpm_limit} onChange={(e) => update('rpm_limit', e.target.value)} placeholder="不限制" /></label>
        <label className="space-y-2"><Label>TPM</Label><Input value={form.tpm_limit} onChange={(e) => update('tpm_limit', e.target.value)} placeholder="不限制" /></label>
        <label className="space-y-2"><Label>最大并发</Label><Input value={form.max_parallel_requests} onChange={(e) => update('max_parallel_requests', e.target.value)} placeholder="不限制" /></label>
        <div className="flex min-h-16 items-center justify-between rounded-xl border border-border px-3"><Label htmlFor={`blocked-${user.user_id}`}>暂停模型访问</Label><Switch id={`blocked-${user.user_id}`} checked={form.blocked} onCheckedChange={(checked) => update('blocked', checked)} /></div>
      </div>
      <DialogFooter>
        <DialogClose asChild><Button type="button" variant="outline">取消</Button></DialogClose>
        <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? '保存中…' : '保存设置'}</Button>
      </DialogFooter>
    </form>
  );
}

function UserEditDialog({ user }: { user: AdminUser }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="size-8 rounded-lg" aria-label={`编辑用户 ${user.alias}`}><Pencil className="size-4" /></Button>
      </DialogTrigger>
      <DialogContent><UserBudgetForm user={user} onSaved={() => setOpen(false)} /></DialogContent>
    </Dialog>
  );
}

export function UsersPage() {
  const query = useUsers();
  if (query.isLoading) return <PageLoading />;
  if (query.error || !query.data) return <PageError error={query.error ?? new Error('用户数据为空')} retry={() => void query.refetch()} />;
  const data = query.data;
  const summaries = [
    { label: '计量用户', value: String(data.user_count), icon: Users },
    { label: '已分配预算', value: data.total_budget, icon: CircleDollarSign },
    { label: '累计消费', value: data.total_spend, icon: CircleDollarSign },
  ];
  return (
    <div className="h-full min-h-0 space-y-4 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">
      <section className="grid divide-y divide-border/60 rounded-2xl border border-border bg-card sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {summaries.map(({ label, value, icon: Icon }) => (
          <div key={label} className="flex items-center gap-3 px-4 py-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><Icon className="size-4" /></span>
            <div className="min-w-0"><p className="text-xs text-muted-foreground">{label}</p><strong className="block truncate text-lg font-semibold">{value}</strong></div>
          </div>
        ))}
      </section>

      {data.users.length === 0 ? <EmptyState title="暂无计量用户" description="用户首次登录后会自动出现在这里。" /> : (
        <section className="overflow-hidden rounded-2xl border border-border bg-card">
          <div className="hidden grid-cols-[minmax(160px,1.2fr)_minmax(180px,1.4fr)_minmax(180px,1.3fr)_190px_120px_40px] gap-4 border-b border-border/60 bg-muted/20 px-5 py-3 text-xs font-medium text-muted-foreground lg:grid">
            <span>用户</span><span>用户标识</span><span>可用模型</span><span>费用 / 预算</span><span>周期 / 状态</span><span />
          </div>
          <div className="divide-y divide-border/60">
            {data.users.map((user) => (
              <div key={user.user_id} className="grid gap-3 px-5 py-4 lg:grid-cols-[minmax(160px,1.2fr)_minmax(180px,1.4fr)_minmax(180px,1.3fr)_190px_120px_40px] lg:items-center lg:gap-4">
                <div className="min-w-0"><strong className="block truncate text-sm">{user.alias}</strong><span className="mt-0.5 block text-xs text-muted-foreground lg:hidden">{user.role}</span></div>
                <span className="truncate font-mono text-xs text-muted-foreground">{user.user_id}</span>
                <div className="flex min-w-0 flex-wrap gap-1.5">{user.models.map((model) => <span key={model} className="rounded-md bg-muted px-2 py-1 text-[11px]">{model}</span>)}</div>
                <div className="min-w-0"><div className="flex justify-between gap-2 text-xs tabular-nums"><span className="text-muted-foreground lg:hidden">费用 / 预算</span><span>{user.spend} / {user.budget}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary"><span className="block h-full rounded-full bg-primary" style={{ width: `${user.budget_percent}%` }} /></div></div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground"><span>{user.duration}</span>{user.blocked ? <span className="inline-flex items-center gap-1 text-destructive"><Ban className="size-3" />已暂停</span> : <span className="text-primary">正常</span>}</div>
                <div className="justify-self-end"><UserEditDialog user={user} /></div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
