import type { FormEvent } from 'react';
import { CheckCircle2, Cloud, GitBranch, PackageCheck, RotateCcw, Upload } from 'lucide-react';
import { toast } from 'sonner';
import {
  usePublishSkills,
  useRollbackSkills,
  useSkills,
  useUpdateSkillSource,
} from '@/api/admin';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageError, PageLoading } from './page-state';

function shortRevision(value: string | null) {
  return value ? value.slice(0, 12) : '尚未发布';
}

export function SkillsPage() {
  const query = useSkills();
  const updateSource = useUpdateSkillSource();
  const publish = usePublishSkills();
  const rollback = useRollbackSkills();
  if (query.isLoading) return <PageLoading />;
  if (query.error || !query.data) {
    return <PageError error={query.error ?? new Error('技能发布状态为空')} retry={() => void query.refetch()} />;
  }

  const data = query.data;
  const hasUpdate = data.latestRevision !== null && data.currentRevision !== data.latestRevision;

  const saveSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    try {
      const result = await updateSource.mutateAsync({
        repository: String(values.get('repository') ?? ''),
        ref: String(values.get('ref') ?? ''),
        catalogPath: String(values.get('catalogPath') ?? ''),
      });
      toast.success(result.message);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '技能源配置保存失败');
    }
  };

  const publishLatest = async () => {
    try {
      const result = await publish.mutateAsync();
      toast.success(`${result.message} ${shortRevision(result.revision)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '技能发布失败');
    }
  };

  const rollbackTo = async (revision: string) => {
    if (!window.confirm(`确认将技能目录回滚到 ${shortRevision(revision)}？`)) return;
    try {
      const result = await rollback.mutateAsync(revision);
      toast.success(`${result.message} ${shortRevision(result.revision)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '技能回滚失败');
    }
  };

  return (
    <div className="h-full min-h-0 space-y-5 overflow-y-auto overscroll-contain rounded-t-3xl pb-24 md:pb-4">
      <section className="grid gap-4 md:grid-cols-3">
        <article className="rounded-3xl border border-border bg-card p-5">
          <GitBranch className="size-5 text-primary" />
          <p className="mt-4 text-sm text-muted-foreground">GitHub 最新提交</p>
          <p className="mt-1 font-mono text-lg font-semibold">{data.githubError ? '检查失败' : shortRevision(data.latestRevision)}</p>
          {data.githubError ? <p className="mt-2 text-xs text-destructive">{data.githubError}</p> : null}
        </article>
        <article className="rounded-3xl border border-border bg-card p-5">
          <PackageCheck className="size-5 text-primary" />
          <p className="mt-4 text-sm text-muted-foreground">当前发布版本</p>
          <p className="mt-1 font-mono text-lg font-semibold">{shortRevision(data.currentRevision)}</p>
        </article>
        <article className="rounded-3xl border border-border bg-card p-5">
          <Cloud className="size-5 text-primary" />
          <p className="mt-4 text-sm text-muted-foreground">制品存储</p>
          <p className="mt-1 text-lg font-semibold">{data.storage.bucket}</p>
          <p className="mt-1 text-xs text-muted-foreground">{data.storage.region} · {data.storage.credentials}</p>
        </article>
      </section>

      <form
        key={`${data.source.repository}:${data.source.ref}:${data.source.catalogPath}`}
        className="rounded-3xl border border-border bg-card p-5"
        onSubmit={(event) => void saveSource(event)}
      >
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">SOURCE</p>
            <h2 className="mt-2 text-xl font-bold">GitHub 技能源</h2>
            <p className="mt-1 text-sm text-muted-foreground">配置保存到私有 OSS 控制区，GitHub 只提供待验证源码；服务器认证：{data.githubAuthenticationConfigured ? '已配置' : '匿名访问'}。</p>
          </div>
          <Button type="submit" variant="outline" className="rounded-xl" disabled={updateSource.isPending}>
            {updateSource.isPending ? '保存中…' : '保存配置'}
          </Button>
        </header>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <div className="space-y-2"><Label htmlFor="skills-repository">仓库</Label><Input id="skills-repository" name="repository" defaultValue={data.source.repository} /></div>
          <div className="space-y-2"><Label htmlFor="skills-ref">分支或标签</Label><Input id="skills-ref" name="ref" defaultValue={data.source.ref} /></div>
          <div className="space-y-2"><Label htmlFor="skills-catalog">Catalog 路径</Label><Input id="skills-catalog" name="catalogPath" defaultValue={data.source.catalogPath} /></div>
        </div>
      </form>

      <section className="rounded-3xl border border-border bg-card p-5">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">RELEASE</p>
            <h2 className="mt-2 text-xl font-bold">验证并发布</h2>
            <p className="mt-1 text-sm text-muted-foreground">发布失败不会切换当前版本；桌面端始终通过 Gateway 鉴权下载 OSS 制品。</p>
          </div>
          <Button className="rounded-xl" onClick={() => void publishLatest()} disabled={publish.isPending || !hasUpdate}>
            {publish.isPending ? <><Upload className="size-4 animate-pulse" />发布中…</> : data.githubError ? <>GitHub 检查失败</> : hasUpdate ? <><Upload className="size-4" />发布 GitHub 最新版本</> : <><CheckCircle2 className="size-4" />已是最新版本</>}
          </Button>
        </header>
      </section>

      <section className="rounded-3xl border border-border bg-card p-5">
        <h2 className="text-xl font-bold">发布历史</h2>
        <div className="mt-4 space-y-2">
          {data.releases.length === 0 ? <p className="text-sm text-muted-foreground">尚无已发布版本。</p> : data.releases.map((release) => (
            <div key={release.revision} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-muted/40 px-4 py-3">
              <div><p className="font-mono text-sm font-semibold">{shortRevision(release.revision)}</p><p className="mt-1 text-xs text-muted-foreground">{release.skillCount} 个技能 · {new Date(release.publishedAt).toLocaleString('zh-CN')}</p></div>
              {release.revision === data.currentRevision ? <span className="text-sm font-medium text-primary">当前版本</span> : <Button size="sm" variant="outline" className="rounded-xl" onClick={() => void rollbackTo(release.revision)} disabled={rollback.isPending}><RotateCcw className="size-4" />回滚</Button>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
