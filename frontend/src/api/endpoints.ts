import { api } from "./client";
import type {
  Agent,
  AgentInput,
  Campaign,
  CampaignCreate,
  CampaignStats,
  CampaignStatus,
  CampaignUpdate,
  Cohort,
  CohortUploadResult,
  Connection,
  ConnectionInput,
  Contact,
  ContactDetail,
  ContactPage,
  ContactStatus,
  DndAddResult,
  DndPage,
  LifecycleAction,
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  OrgRate,
  TokenResponse,
  User,
  UserCreate,
  UserUpdate,
  Workspace,
  WorkspaceInput,
} from "./types";

export const authApi = {
  login: (email: string, password: string) => api.post<TokenResponse>("/auth/login", { email, password }),
  me: () => api.get<User>("/auth/me"),
};

export const orgApi = {
  list: () => api.get<Organization[]>("/organizations"),
  get: (id: string) => api.get<Organization>(`/organizations/${id}`),
  create: (body: OrganizationCreate) => api.post<Organization>("/organizations", body),
  update: (id: string, body: OrganizationUpdate) => api.patch<Organization>(`/organizations/${id}`, body),
  rate: (id: string, seconds = 60) => api.get<OrgRate>(`/organizations/${id}/rate`, { seconds }),
};

export const workspaceApi = {
  list: (orgId?: string) => api.get<Workspace[]>("/workspaces", { org_id: orgId }),
  create: (body: WorkspaceInput, orgId?: string) => api.post<Workspace>("/workspaces", body, { org_id: orgId }),
  update: (id: string, body: WorkspaceInput) => api.patch<Workspace>(`/workspaces/${id}`, body),
};

export const userApi = {
  list: (orgId?: string) => api.get<User[]>("/users", { org_id: orgId }),
  create: (body: UserCreate) => api.post<User>("/users", body),
  update: (id: string, body: UserUpdate) => api.patch<User>(`/users/${id}`, body),
};

export const agentApi = {
  list: (workspaceId: string) => api.get<Agent[]>(`/workspaces/${workspaceId}/agents`),
  get: (id: string) => api.get<Agent>(`/agents/${id}`),
  create: (workspaceId: string, body: AgentInput) => api.post<Agent>(`/workspaces/${workspaceId}/agents`, body),
  update: (id: string, body: Partial<AgentInput>) => api.patch<Agent>(`/agents/${id}`, body),
  sampleCsv: (id: string) => api.blob(`/agents/${id}/sample-cohort.csv`),
  /** Checks a cohort CSV against the agent's variables; nothing is stored. */
  validateCohort: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload<CohortUploadResult>(`/agents/${id}/validate-cohort`, form);
  },
};

export const connectionApi = {
  list: (workspaceId: string) => api.get<Connection[]>(`/workspaces/${workspaceId}/connections`),
  create: (workspaceId: string, body: ConnectionInput) =>
    api.post<Connection>(`/workspaces/${workspaceId}/connections`, body),
  update: (id: string, body: Partial<ConnectionInput>) => api.patch<Connection>(`/connections/${id}`, body),
};

export const campaignApi = {
  list: (workspaceId: string, status?: CampaignStatus) =>
    api.get<Campaign[]>(`/workspaces/${workspaceId}/campaigns`, { status }),
  get: (id: string) => api.get<Campaign>(`/campaigns/${id}`),
  create: (workspaceId: string, body: CampaignCreate) =>
    api.post<Campaign>(`/workspaces/${workspaceId}/campaigns`, body),
  update: (id: string, body: CampaignUpdate) => api.patch<Campaign>(`/campaigns/${id}`, body),
  duplicate: (id: string) => api.post<Campaign>(`/campaigns/${id}/duplicate`),
  exportCsv: (id: string) => api.blob(`/campaigns/${id}/contacts.csv`),
  remove: (id: string) => api.delete(`/campaigns/${id}`),
  setStatus: (id: string, action: LifecycleAction) => api.put<Campaign>(`/campaigns/${id}/status`, { action }),
  stats: (id: string) => api.get<CampaignStats>(`/campaigns/${id}/stats`),
};

export interface ContactQuery {
  status?: ContactStatus;
  q?: string;
  cursor?: string;
  limit?: number;
}

export const cohortApi = {
  list: (campaignId: string) => api.get<Cohort[]>(`/campaigns/${campaignId}/cohorts`),
  upload: (campaignId: string, file: File, opts: { dryRun: boolean; skipInvalid: boolean }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", String(opts.dryRun));
    form.append("skip_invalid", String(opts.skipInvalid));
    return api.upload<CohortUploadResult>(`/campaigns/${campaignId}/cohorts`, form);
  },
  errorReport: (cohortId: string) => api.blob(`/cohorts/${cohortId}/errors.csv`),
};

export const contactApi = {
  list: (campaignId: string, query: ContactQuery) =>
    api.get<ContactPage>(`/campaigns/${campaignId}/contacts`, { ...query }),
  get: (id: string) => api.get<ContactDetail>(`/contacts/${id}`),
  cancel: (id: string) => api.post<Contact>(`/contacts/${id}/cancel`),
};

export const dndApi = {
  list: (orgId: string, query: { search?: string; cursor?: string; limit?: number }) =>
    api.get<DndPage>(`/organizations/${orgId}/dnd`, { ...query }),
  add: (orgId: string, phoneNumbers: string[], reason: string) =>
    api.post<DndAddResult>(`/organizations/${orgId}/dnd`, { phone_numbers: phoneNumbers, reason }),
  upload: (orgId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload<DndAddResult>(`/organizations/${orgId}/dnd/upload`, form);
  },
  remove: (orgId: string, phone: string) => api.delete(`/organizations/${orgId}/dnd/${encodeURIComponent(phone)}`),
};
