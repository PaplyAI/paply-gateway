import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useLogin } from '@/api/user';
import Logo from '@/components/modules/logo';
import { Button } from '@/components/ui/button';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

export function LoginForm() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const login = useLogin();

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await login.mutateAsync({ username, password });
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : '登录失败，请稍后重试。');
    }
  };

  return (
    <main className="flex min-h-screen animate-in items-center justify-center px-6 text-foreground fade-in duration-300">
      <section className="w-full max-w-sm rounded-3xl border border-border bg-card p-8 shadow-lg">
        <header className="mb-8 flex flex-col items-center gap-3 text-center">
          <Logo size={56} />
          <div>
            <h1 className="text-2xl font-bold">Paply Gateway</h1>
            <p className="mt-1 text-sm text-muted-foreground">模型路由与用量管理中心</p>
          </div>
        </header>

        <form onSubmit={handleSubmit} className="space-y-5">
          <Field>
            <FieldLabel htmlFor="username">管理员账号</FieldLabel>
            <Input id="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} disabled={login.isPending} required />
          </Field>
          <Field>
            <FieldLabel htmlFor="password">登录密码</FieldLabel>
            <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={login.isPending} required />
          </Field>
          {error && <FieldDescription className="text-destructive">{error}</FieldDescription>}
          <Button type="submit" disabled={login.isPending} className="w-full rounded-xl">
            <ShieldCheck className="size-4" />
            {login.isPending ? '正在验证…' : '进入管理中心'}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs leading-5 text-muted-foreground">
          Provider 密钥仅在服务端写入 LiteLLM，不会进入浏览器。
        </p>
      </section>
    </main>
  );
}
