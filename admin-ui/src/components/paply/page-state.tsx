import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function PageLoading() {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      <LoaderCircle className="mr-2 size-5 animate-spin" />
      正在读取 Gateway 数据…
    </div>
  );
}

export function PageError({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="max-w-md rounded-3xl border border-destructive/20 bg-card p-8 text-center">
        <AlertCircle className="mx-auto mb-3 size-8 text-destructive" />
        <h2 className="font-semibold">数据加载失败</h2>
        <p className="mt-2 text-sm text-muted-foreground">{error.message}</p>
        <Button type="button" variant="outline" className="mt-5 rounded-xl" onClick={retry}>
          <RefreshCw className="size-4" />重新加载
        </Button>
      </div>
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex min-h-56 items-center justify-center rounded-3xl border border-dashed border-border bg-card/50 px-6 text-center">
      <div><p className="font-semibold">{title}</p><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>
    </div>
  );
}
