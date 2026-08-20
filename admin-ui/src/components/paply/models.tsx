import { useMemo, useState } from 'react';
import { Circle, CircleCheck, CircleX, Pencil, Plus, Power, RefreshCw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import type { Deployment, DeploymentInput, ModelGroup } from '@/api/admin';
import {
  useCreateDeployment, useDeleteDeployment, useModels, useRefreshHealth,
  useTestDeployment, useToggleDeployment, useUpdateDeployment,
} from '@/api/admin';
import { useAuthStore } from '@/api/user';
import { Button } from '@/components/ui/button';
import { CopyIconButton } from '@/components/common/CopyButton';
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { getModelIcon } from '@/lib/model-icons';
import { cn } from '@/lib/utils';
import { EmptyState, PageError, PageLoading } from './page-state';

const emptyDeployment: DeploymentInput = { model_name: '', upstream_model: '', api_base: '', api_key: '', weight: '', rpm: '', tpm: '' };

function DeploymentForm({ deployment, modelName, onSaved }: { deployment?: Deployment; modelName?: string; onSaved: () => void }) {
  const session = useAuthStore((state) => state.session);
  const create = useCreateDeployment();
  const updateMutation = useUpdateDeployment();
  const [form, setForm] = useState<DeploymentInput>(deployment ? {
    model_name: deployment.name, upstream_model: deployment.upstream, api_base: deployment.api_base,
    api_key: '', weight: String(deployment.weight || ''), rpm: String(deployment.rpm || ''), tpm: String(deployment.tpm || ''),
  } : { ...emptyDeployment, model_name: modelName ?? session?.allowed_models?.[0] ?? '' });
  const update = (key: keyof DeploymentInput, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const result = deployment ? await updateMutation.mutateAsync({ id: deployment.id, input: form }) : await create.mutateAsync(form);
      toast.success(result.message);
      onSaved();
    } catch (cause: unknown) {
      toast.error(cause instanceof Error ? cause.message : '保存节点失败');
    }
  };
  const pending = create.isPending || updateMutation.isPending;
  return (
    <form onSubmit={save}>
      <DialogHeader><p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">{deployment ? '编辑节点' : '新增节点'}</p><DialogTitle>{deployment ? deployment.provider : '新增模型节点'}</DialogTitle><DialogDescription>同一模型组下的节点自动加入 LiteLLM 负载均衡池。</DialogDescription></DialogHeader>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2"><Label>公开模型组</Label><select className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm" value={form.model_name} onChange={(e) => update('model_name', e.target.value)} required>{session?.allowed_models?.map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
        <label className="space-y-2"><Label>上游模型</Label><Input value={form.upstream_model} onChange={(e) => update('upstream_model', e.target.value)} placeholder="openai/deepseek-v4-flash" required /></label>
        <label className="space-y-2 md:col-span-2"><Label>API Base</Label><Input type="url" value={form.api_base} onChange={(e) => update('api_base', e.target.value)} placeholder="https://provider.example.com/v1" required /></label>
        <label className="space-y-2 md:col-span-2"><Label>{deployment ? '新 API Key（留空保持不变）' : 'API Key'}</Label><Input type="password" autoComplete="new-password" value={form.api_key} onChange={(e) => update('api_key', e.target.value)} required={!deployment} /></label>
        <label className="space-y-2"><Label>权重</Label><Input value={form.weight} onChange={(e) => update('weight', e.target.value)} placeholder="默认随机" /></label>
        <label className="space-y-2"><Label>RPM</Label><Input value={form.rpm} onChange={(e) => update('rpm', e.target.value)} placeholder="不限制" /></label>
        <label className="space-y-2"><Label>TPM</Label><Input value={form.tpm} onChange={(e) => update('tpm', e.target.value)} placeholder="不限制" /></label>
      </div>
      <p className="mt-5 rounded-xl bg-primary/10 p-3 text-xs leading-5 text-primary">密钥只发送到 Paply Gateway 服务端并由 LiteLLM 加密保存，浏览器不会再次读取。</p>
      <DialogFooter><DialogClose asChild><Button type="button" variant="outline">取消</Button></DialogClose><Button type="submit" disabled={pending}>{pending ? '保存中…' : '保存节点'}</Button></DialogFooter>
    </form>
  );
}

export function ModelsActions() {
  const refresh = useRefreshHealth();
  const refreshHealth = async () => {
    try { const { counts } = await refresh.mutateAsync(); toast.success(`健康检查完成：${counts.healthy} 健康，${counts.unhealthy} 异常，${counts.unknown} 未知`); }
    catch (cause: unknown) { toast.error(cause instanceof Error ? cause.message : '刷新失败'); }
  };
  return <div className="flex items-center gap-1"><Button variant="ghost" size="icon" className="rounded-xl" onClick={refreshHealth} disabled={refresh.isPending} aria-label="刷新节点健康"><RefreshCw className={cn('size-4', refresh.isPending && 'animate-spin')} /></Button><CreateNodeDialog /></div>;
}

function NodeEditDialog({ node }: { node: Deployment }) {
  const [open, setOpen] = useState(false);
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button variant="ghost" size="icon" className="size-7 rounded-lg" aria-label={`编辑节点 ${node.provider}`}><Pencil className="size-3.5" /></Button></DialogTrigger><DialogContent><DeploymentForm deployment={node} onSaved={() => setOpen(false)} /></DialogContent></Dialog>;
}

function CreateNodeDialog({ modelName, compact = false }: { modelName?: string; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className={compact ? 'size-8 rounded-lg' : 'rounded-xl'} aria-label={modelName ? `向 ${modelName} 添加节点` : '新增模型节点'}>
          <Plus className={compact ? 'size-4' : 'size-5'} />
        </Button>
      </DialogTrigger>
      <DialogContent><DeploymentForm modelName={modelName} onSaved={() => setOpen(false)} /></DialogContent>
    </Dialog>
  );
}

function DeleteNodeDialog({ node }: { node: Deployment }) {
  const [open, setOpen] = useState(false);
  const remove = useDeleteDeployment();
  const deleteNode = async () => {
    try {
      const result = await remove.mutateAsync(node.id);
      toast.success(result.message);
      setOpen(false);
    } catch (cause: unknown) {
      toast.error(cause instanceof Error ? cause.message : '删除节点失败');
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button type="button" className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive" aria-label={`删除节点 ${node.upstream}`}>
          <X className="size-3.5" />
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>删除这个节点？</DialogTitle>
          <DialogDescription>将从 {node.name} 的负载均衡池中移除 {node.upstream}。该操作不可撤销。</DialogDescription>
        </DialogHeader>
        <DialogFooter><DialogClose asChild><Button variant="outline">取消</Button></DialogClose><Button variant="destructive" onClick={deleteNode} disabled={remove.isPending}><Trash2 className="size-4" />{remove.isPending ? '删除中…' : '删除节点'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
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
  const unhealthy = node.health.state === 'unhealthy';
  const { Icon, className: iconClassName } = useMemo(() => getModelIcon(node.upstream), [node.upstream]);
  return (
    <div className={cn('group rounded-xl border border-border/70 bg-background p-3 transition-colors hover:border-primary/30', node.blocked && 'opacity-55')}>
      <div className="flex items-center gap-2.5">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-sm font-semibold text-primary">{index + 1}</span>
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-[#4e70ff]/10"><Icon aria-hidden="true" className={cn('size-5', iconClassName)} /></span>
        <div className="min-w-0 flex-1">
          <Tooltip><TooltipTrigger asChild><p className="truncate text-sm font-semibold">{node.upstream}</p></TooltipTrigger><TooltipContent side="top">{node.upstream}</TooltipContent></Tooltip>
          <Tooltip><TooltipTrigger asChild><p className="truncate text-xs text-muted-foreground">{node.provider}</p></TooltipTrigger><TooltipContent side="top">{node.api_base}</TooltipContent></Tooltip>
        </div>
        <Tooltip><TooltipTrigger asChild><button type="button" className={cn('rounded-md p-1 transition-colors hover:bg-muted', healthy ? 'text-primary' : unhealthy ? 'text-destructive' : 'text-muted-foreground')} onClick={testNode} disabled={test.isPending} aria-label={`检测节点 ${node.upstream}`}>{healthy ? <CircleCheck className="size-4" /> : unhealthy ? <CircleX className="size-4" /> : <Circle className={cn('size-4', test.isPending && 'animate-pulse')} />}</button></TooltipTrigger><TooltipContent side="top">{test.isPending ? '检测中…' : node.health.label}</TooltipContent></Tooltip>
        <NodeEditDialog node={node} />
        <Tooltip><TooltipTrigger asChild><button type="button" className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground" onClick={toggleNode} disabled={toggle.isPending} aria-label={node.blocked ? `启用节点 ${node.upstream}` : `停用节点 ${node.upstream}`}><Power className="size-3.5" /></button></TooltipTrigger><TooltipContent side="top">{node.blocked ? '启用' : '停用'}</TooltipContent></Tooltip>
        <DeleteNodeDialog node={node} />
      </div>
      <div className="mt-2 flex items-center gap-3 pl-18 text-[11px] text-muted-foreground"><span>权重 <b className="font-medium text-foreground">{node.weight || '默认'}</b></span><span>RPM <b className="font-medium text-foreground">{node.rpm || '—'}</b></span><span>TPM <b className="font-medium text-foreground">{node.tpm || '—'}</b></span></div>
    </div>
  );
}

function GroupCard({ group }: { group: ModelGroup }) {
  return (
    <article className="flex min-h-112 flex-col rounded-3xl border border-border bg-card p-4 text-card-foreground">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0"><h2 className="truncate text-lg font-bold">{group.name}</h2><p className="mt-1 text-xs text-muted-foreground">{group.active_count} 启用 · {group.deployment_count} 节点</p></div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Tooltip><TooltipTrigger asChild><span><CopyIconButton text={group.name} className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground" copyIconClassName="size-4" checkIconClassName="size-4 text-primary" /></span></TooltipTrigger><TooltipContent side="top">复制模型名</TooltipContent></Tooltip>
          <CreateNodeDialog modelName={group.name} compact />
        </div>
      </header>
      <div className="mb-3 flex items-center justify-between rounded-xl bg-muted/60 px-3 py-2 text-xs"><span className="font-medium text-primary">随机分流</span><span className="text-muted-foreground">simple-shuffle · 支持权重</span></div>
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
  return <div className="h-full min-h-0 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">{query.data.groups.length === 0 ? <EmptyState title="暂无模型组" description="点击右上角加号创建第一个节点。" /> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data.groups.map((group) => <GroupCard key={group.name} group={group} />)}</div>}</div>;
}
