import { useState } from 'react';
import { Bot, Circle, CircleCheck, Pencil, Plus, Power, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { Deployment, DeploymentInput, ModelGroup } from '@/api/admin';
import {
  useCreateDeployment, useDeleteDeployment, useModels, useRefreshHealth,
  useTestDeployment, useToggleDeployment, useUpdateDeployment,
} from '@/api/admin';
import { useAuthStore } from '@/api/user';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  MorphingDialog, MorphingDialogClose, MorphingDialogContainer, MorphingDialogContent,
  MorphingDialogTrigger, useMorphingDialog,
} from '@/components/ui/morphing-dialog';
import { cn } from '@/lib/utils';
import { EmptyState, PageError, PageLoading } from './page-state';

const emptyDeployment: DeploymentInput = { model_name: '', upstream_model: '', api_base: '', api_key: '', weight: '', rpm: '', tpm: '' };

function DeploymentForm({ deployment }: { deployment?: Deployment }) {
  const session = useAuthStore((state) => state.session);
  const create = useCreateDeployment();
  const updateMutation = useUpdateDeployment();
  const remove = useDeleteDeployment();
  const { setIsOpen } = useMorphingDialog();
  const [form, setForm] = useState<DeploymentInput>(deployment ? {
    model_name: deployment.name, upstream_model: deployment.upstream, api_base: deployment.api_base,
    api_key: '', weight: String(deployment.weight || ''), rpm: String(deployment.rpm || ''), tpm: String(deployment.tpm || ''),
  } : { ...emptyDeployment, model_name: session?.allowed_models?.[0] ?? '' });
  const update = (key: keyof DeploymentInput, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const result = deployment ? await updateMutation.mutateAsync({ id: deployment.id, input: form }) : await create.mutateAsync(form);
      toast.success(result.message);
      setIsOpen(false);
    } catch (cause: unknown) {
      toast.error(cause instanceof Error ? cause.message : '保存节点失败');
    }
  };
  const deleteNode = async () => {
    if (!deployment || !window.confirm(`确定删除节点 ${deployment.provider}？`)) return;
    try { const result = await remove.mutateAsync(deployment.id); toast.success(result.message); setIsOpen(false); }
    catch (cause: unknown) { toast.error(cause instanceof Error ? cause.message : '删除节点失败'); }
  };
  const pending = create.isPending || updateMutation.isPending || remove.isPending;
  return (
    <form onSubmit={save} className="space-y-5">
      <div className="pr-10"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">{deployment ? 'EDIT DEPLOYMENT' : 'NEW DEPLOYMENT'}</p><h2 className="mt-1 text-xl font-bold">{deployment ? deployment.provider : '新增模型节点'}</h2><p className="mt-1 text-xs text-muted-foreground">同一模型组下的节点自动加入 LiteLLM 负载均衡池。</p></div>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2"><Label>公开模型组</Label><select className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm" value={form.model_name} onChange={(e) => update('model_name', e.target.value)} required>{session?.allowed_models?.map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
        <label className="space-y-2"><Label>上游模型</Label><Input value={form.upstream_model} onChange={(e) => update('upstream_model', e.target.value)} placeholder="openai/deepseek-v4-flash" required /></label>
        <label className="space-y-2 md:col-span-2"><Label>API Base</Label><Input type="url" value={form.api_base} onChange={(e) => update('api_base', e.target.value)} placeholder="https://provider.example.com/v1" required /></label>
        <label className="space-y-2 md:col-span-2"><Label>{deployment ? '新 API Key（留空保持不变）' : 'API Key'}</Label><Input type="password" autoComplete="new-password" value={form.api_key} onChange={(e) => update('api_key', e.target.value)} required={!deployment} /></label>
        <label className="space-y-2"><Label>权重</Label><Input value={form.weight} onChange={(e) => update('weight', e.target.value)} placeholder="默认随机" /></label>
        <label className="space-y-2"><Label>RPM</Label><Input value={form.rpm} onChange={(e) => update('rpm', e.target.value)} placeholder="不限制" /></label>
        <label className="space-y-2"><Label>TPM</Label><Input value={form.tpm} onChange={(e) => update('tpm', e.target.value)} placeholder="不限制" /></label>
      </div>
      <p className="rounded-xl bg-primary/10 p-3 text-xs leading-5 text-primary">密钥只发送到 Paply Gateway 服务端并由 LiteLLM 加密保存，浏览器不会再次读取。</p>
      <div className="flex items-center justify-between gap-2">{deployment ? <Button type="button" variant="destructive" onClick={deleteNode} disabled={pending}><Trash2 className="size-4" />删除</Button> : <span />}<div className="flex gap-2"><MorphingDialogClose className="static rounded-xl border border-border px-4 py-2 text-sm">取消</MorphingDialogClose><Button type="submit" className="rounded-xl" disabled={pending}>{pending ? '保存中…' : '保存节点'}</Button></div></div>
    </form>
  );
}

export function ModelsActions() {
  const refresh = useRefreshHealth();
  const refreshHealth = async () => {
    try { const { counts } = await refresh.mutateAsync(); toast.success(`健康检查完成：${counts.healthy} 健康，${counts.unhealthy} 异常，${counts.unknown} 未知`); }
    catch (cause: unknown) { toast.error(cause instanceof Error ? cause.message : '刷新失败'); }
  };
  return <div className="flex items-center gap-2"><Button variant="ghost" size="icon" className="rounded-xl" onClick={refreshHealth} disabled={refresh.isPending} aria-label="刷新节点健康"><RefreshCw className={cn('size-4', refresh.isPending && 'animate-spin')} /></Button><MorphingDialog><MorphingDialogTrigger ariaLabel="新增模型节点" className="grid size-9 place-items-center rounded-xl text-muted-foreground transition-colors hover:text-foreground"><Plus className="size-5" /></MorphingDialogTrigger><MorphingDialogContainer><MorphingDialogContent className="relative max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-2xl overflow-y-auto rounded-3xl border border-border bg-card p-6"><DeploymentForm /></MorphingDialogContent></MorphingDialogContainer></MorphingDialog></div>;
}

function NodeItem({ node, index }: { node: Deployment; index: number }) {
  const test = useTestDeployment();
  const toggle = useToggleDeployment();
  const testNode = async () => {
    try {
      const result = await test.mutateAsync(node.id);
      if (result.health.state === 'healthy') toast.success('节点健康');
      else toast.error(result.health.label);
    } catch (cause: unknown) {
      toast.error(cause instanceof Error ? cause.message : '检测失败');
    }
  };
  const toggleNode = async () => { try { const result = await toggle.mutateAsync({ id: node.id, blocked: !node.blocked }); toast.success(result.message); } catch (cause: unknown) { toast.error(cause instanceof Error ? cause.message : '状态更新失败'); } };
  const healthy = node.health.state === 'healthy';
  return (
    <div className={cn('rounded-xl border border-border/50 bg-background px-3 py-2.5 transition-opacity', node.blocked && 'opacity-55')}>
      <div className="flex items-center gap-2">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-sm font-semibold text-primary">{index + 1}</span>
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-[#4e70ff] text-white"><Bot className="size-4" /></span>
        <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{node.upstream}</p><p className="truncate text-[10px] text-muted-foreground">{node.provider}</p></div>
        <button type="button" className={cn('p-1', healthy ? 'text-primary' : 'text-muted-foreground')} onClick={testNode} disabled={test.isPending} title={node.health.label}>{healthy ? <CircleCheck className="size-4" /> : <Circle className="size-4" />}</button>
        <MorphingDialog><MorphingDialogTrigger ariaLabel={`编辑节点 ${node.provider}`} className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"><Pencil className="size-3.5" /></MorphingDialogTrigger><MorphingDialogContainer><MorphingDialogContent className="relative max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-2xl overflow-y-auto rounded-3xl border border-border bg-card p-6"><DeploymentForm deployment={node} /></MorphingDialogContent></MorphingDialogContainer></MorphingDialog>
        <button type="button" className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" onClick={toggleNode} disabled={toggle.isPending} title={node.blocked ? '启用' : '停用'}><Power className="size-3.5" /></button>
      </div>
      <div className="mt-2 flex items-center gap-2 pl-17 text-[10px] text-muted-foreground"><span>权重 {node.weight || '默认'}</span><span>RPM {node.rpm || '—'}</span><span>TPM {node.tpm || '—'}</span></div>
    </div>
  );
}

function GroupCard({ group }: { group: ModelGroup }) {
  return (
    <article className="flex min-h-120 flex-col rounded-3xl border border-border bg-card p-4 text-card-foreground">
      <header className="mb-3 flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="truncate text-lg font-bold">{group.name}</h2><p className="mt-1 text-xs text-muted-foreground">{group.active_count} 启用 · {group.deployment_count} 节点</p></div><span className="rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary">simple-shuffle</span></header>
      <div className="mb-3 grid grid-cols-2 gap-2"><span className="rounded-xl bg-primary px-3 py-2 text-center text-xs text-primary-foreground">随机分流</span><span className="rounded-xl bg-secondary px-3 py-2 text-center text-xs">支持权重</span></div>
      <section className="flex-1 space-y-2 overflow-y-auto rounded-xl border border-border/50 bg-muted/30 p-2">
        {group.deployments.map((node, index) => <NodeItem key={node.id} node={node} index={index} />)}
      </section>
    </article>
  );
}

export function ModelsPage() {
  const query = useModels();
  if (query.isLoading) return <PageLoading />;
  if (query.error || !query.data) return <PageError error={query.error ?? new Error('模型数据为空')} retry={() => void query.refetch()} />;
  return <div className="h-full min-h-0 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">{query.data.groups.length === 0 ? <EmptyState title="暂无模型组" description="点击右上角加号创建第一个节点。" /> : <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">{query.data.groups.map((group) => <GroupCard key={group.name} group={group} />)}</div>}</div>;
}
