import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiRequest } from './client';

export type HealthState = 'healthy' | 'unhealthy' | 'unknown';

export interface AdminUser {
  alias: string;
  user_id: string;
  spend: string;
  spend_value: number;
  budget: string;
  budget_value: number;
  budget_percent: number;
  models: string[];
  duration: string;
  role: string;
  rpm_limit: number | string;
  tpm_limit: number | string;
  max_parallel_requests: number | string;
  blocked: boolean;
}

export interface DeploymentHealth {
  state: HealthState;
  label: string;
  checked_at: string;
}

export interface Deployment {
  id: string;
  name: string;
  upstream: string;
  api_base: string;
  provider: string;
  weight: number | string;
  rpm: number | string;
  tpm: number | string;
  mode: string;
  blocked: boolean;
  db_model: boolean;
  health: DeploymentHealth;
}

export interface ModelGroup {
  name: string;
  deployments: Deployment[];
  deployment_count: number;
  active_count: number;
}

export interface OverviewData {
  total_spend: string;
  total_budget: string;
  user_count: number;
  model_group_count: number;
  deployment_count: number;
  total_tokens: string;
  prompt_tokens: string;
  completion_tokens: string;
  request_count: string;
  successful_request_count: string;
  failed_request_count: string;
  activity_period: string;
  users: AdminUser[];
  model_groups: ModelGroup[];
  updated_at: string;
}

export interface UsersData {
  users: AdminUser[];
  user_count: number;
  total_budget: string;
  total_spend: string;
}

export interface ModelsData {
  groups: ModelGroup[];
  group_count: number;
  deployment_count: number;
  active_count: number;
}

export interface SystemComponent {
  name: string;
  description: string;
  healthy: boolean;
  status: number | string;
  latency_ms: number;
}

export interface SystemData {
  components: SystemComponent[];
  healthy: boolean;
  updated_at: string;
}

export interface SkillSourceConfig {
  repository: string;
  ref: string;
  catalogPath: string;
}

export interface SkillsData {
  source: SkillSourceConfig;
  storage: {
    provider: string;
    bucket: string;
    region: string;
    endpoint: string;
    prefix: string;
    credentials: string;
  };
  latestRevision: string | null;
  githubError: string | null;
  currentRevision: string | null;
  publishedAt: string | null;
  githubAuthenticationConfigured: boolean;
  releases: Array<{ revision: string; publishedAt: string; skillCount: number }>;
}

export interface UserBudgetInput {
  max_budget: string;
  budget_duration: string;
  rpm_limit: string;
  tpm_limit: string;
  max_parallel_requests: string;
  blocked: boolean;
}

export interface DeploymentInput {
  model_name: string;
  upstream_model: string;
  api_base: string;
  api_key: string;
  weight: string;
  rpm: string;
  tpm: string;
}

export const adminKeys = {
  overview: ['admin', 'overview'] as const,
  users: ['admin', 'users'] as const,
  models: ['admin', 'models'] as const,
  system: ['admin', 'system'] as const,
  skills: ['admin', 'skills'] as const,
};

export function useOverview() {
  return useQuery({ queryKey: adminKeys.overview, queryFn: () => apiRequest<OverviewData>('/api/admin/overview') });
}

export function useUsers() {
  return useQuery({ queryKey: adminKeys.users, queryFn: () => apiRequest<UsersData>('/api/admin/users') });
}

export function useModels() {
  return useQuery({ queryKey: adminKeys.models, queryFn: () => apiRequest<ModelsData>('/api/admin/models') });
}

export function useSystem() {
  return useQuery({
    queryKey: adminKeys.system,
    queryFn: () => apiRequest<SystemData>('/api/admin/system'),
    refetchInterval: 30_000,
  });
}

export function useSkills() {
  return useQuery({ queryKey: adminKeys.skills, queryFn: () => apiRequest<SkillsData>('/api/admin/skills') });
}

export function useUpdateSkillSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: SkillSourceConfig) => apiRequest<{ message: string }>('/api/admin/skills/source', { method: 'PATCH', body: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.skills }),
  });
}

export function usePublishSkills() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<{ message: string; revision: string }>('/api/admin/skills/publish', { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.skills }),
  });
}

export function useRollbackSkills() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (revision: string) => apiRequest<{ message: string; revision: string }>('/api/admin/skills/rollback', { method: 'POST', body: { revision } }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.skills }),
  });
}

export function useUpdateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, input }: { userId: string; input: UserBudgetInput }) =>
      apiRequest<{ message: string }>(`/api/admin/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        body: input,
      }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: adminKeys.users }),
        client.invalidateQueries({ queryKey: adminKeys.overview }),
      ]);
    },
  });
}

export function useCreateDeployment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: DeploymentInput) =>
      apiRequest<{ id: string; message: string }>('/api/admin/deployments', { method: 'POST', body: input }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: adminKeys.models }),
        client.invalidateQueries({ queryKey: adminKeys.overview }),
      ]);
    },
  });
}

export function useUpdateDeployment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: DeploymentInput }) =>
      apiRequest<{ message: string }>(`/api/admin/deployments/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: input,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.models }),
  });
}

export function useToggleDeployment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, blocked }: { id: string; blocked: boolean }) =>
      apiRequest<{ message: string }>(`/api/admin/deployments/${encodeURIComponent(id)}/state`, {
        method: 'PATCH',
        body: { blocked },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.models }),
  });
}

export function useTestDeployment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<{ health: DeploymentHealth }>(`/api/admin/deployments/${encodeURIComponent(id)}/test`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.models }),
  });
}

export function useRefreshHealth() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<{ counts: Record<HealthState, number> }>('/api/admin/deployments/health', { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.models }),
  });
}

export function useDeleteDeployment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<{ message: string }>(`/api/admin/deployments/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: adminKeys.models }),
        client.invalidateQueries({ queryKey: adminKeys.overview }),
      ]);
    },
  });
}
