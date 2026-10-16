import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  agentApi,
  campaignApi,
  cohortApi,
  connectionApi,
  contactApi,
  dndApi,
  orgApi,
  userApi,
  workspaceApi,
  type ContactQuery,
} from "./endpoints";

export const keys = {
  orgs: ["organizations"] as const,
  org: (id: string) => ["organizations", id] as const,
  orgRate: (id: string) => ["organizations", id, "rate"] as const,
  workspaces: (orgId?: string) => ["workspaces", orgId ?? "all"] as const,
  users: (orgId?: string) => ["users", orgId ?? "all"] as const,
  agents: (workspaceId: string) => ["agents", "list", workspaceId] as const,
  agent: (id: string) => ["agents", id] as const,
  connections: (workspaceId: string) => ["connections", workspaceId] as const,
  campaigns: (workspaceId: string) => ["campaigns", "list", workspaceId] as const,
  campaign: (id: string) => ["campaign", id] as const,
  stats: (id: string) => ["campaign", id, "stats"] as const,
  cohorts: (id: string) => ["campaign", id, "cohorts"] as const,
  contacts: (id: string) => ["campaign", id, "contacts"] as const,
  contactPage: (id: string, query: ContactQuery) => ["campaign", id, "contacts", query] as const,
  contact: (id: string) => ["contact", id] as const,
  dnd: (orgId: string, query?: object) => (query ? (["dnd", orgId, query] as const) : (["dnd", orgId] as const)),
};

export function useOrganizations(enabled = true) {
  return useQuery({ queryKey: keys.orgs, queryFn: orgApi.list, enabled });
}

export function useOrganization(id: string | null | undefined) {
  return useQuery({ queryKey: keys.org(id ?? ""), queryFn: () => orgApi.get(id!), enabled: !!id });
}

export function useWorkspaces(orgId?: string, enabled = true) {
  return useQuery({ queryKey: keys.workspaces(orgId), queryFn: () => workspaceApi.list(orgId), enabled });
}

export function useUsers(orgId?: string) {
  return useQuery({ queryKey: keys.users(orgId), queryFn: () => userApi.list(orgId) });
}

export function useAgents(workspaceId: string | null) {
  return useQuery({
    queryKey: keys.agents(workspaceId ?? ""),
    queryFn: () => agentApi.list(workspaceId!),
    enabled: !!workspaceId,
  });
}

export function useAgent(id: string | null | undefined) {
  return useQuery({ queryKey: keys.agent(id ?? ""), queryFn: () => agentApi.get(id!), enabled: !!id });
}

export function useConnections(workspaceId: string | null) {
  return useQuery({
    queryKey: keys.connections(workspaceId ?? ""),
    queryFn: () => connectionApi.list(workspaceId!),
    enabled: !!workspaceId,
  });
}

const LIVE = new Set(["running", "scheduled", "paused"]);

export function useCampaigns(workspaceId: string | null) {
  return useQuery({
    queryKey: keys.campaigns(workspaceId ?? ""),
    queryFn: () => campaignApi.list(workspaceId!),
    enabled: !!workspaceId,
    // Counts come with the list, so refresh it while anything is in flight.
    refetchInterval: (query) => (query.state.data?.some((c) => LIVE.has(c.status)) ? 5000 : false),
  });
}

export function useCampaign(id: string) {
  return useQuery({ queryKey: keys.campaign(id), queryFn: () => campaignApi.get(id) });
}

export function useCampaignStats(id: string, opts: { pollMs?: number | false; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: keys.stats(id),
    queryFn: () => campaignApi.stats(id),
    refetchInterval: opts.pollMs ?? false,
    enabled: opts.enabled ?? true,
  });
}

export function useCohorts(campaignId: string) {
  return useQuery({ queryKey: keys.cohorts(campaignId), queryFn: () => cohortApi.list(campaignId) });
}

export function useContactPage(campaignId: string, query: ContactQuery, pollMs: number | false = false) {
  return useQuery({
    queryKey: keys.contactPage(campaignId, query),
    queryFn: () => contactApi.list(campaignId, query),
    placeholderData: keepPreviousData,
    refetchInterval: pollMs,
  });
}

export function useContact(id: string | null) {
  return useQuery({ queryKey: keys.contact(id ?? ""), queryFn: () => contactApi.get(id!), enabled: !!id });
}

export function useDnd(orgId: string | null | undefined, query: { search?: string; cursor?: string; limit?: number }) {
  return useQuery({
    queryKey: keys.dnd(orgId ?? "", query),
    queryFn: () => dndApi.list(orgId!, query),
    enabled: !!orgId,
    placeholderData: keepPreviousData,
  });
}

export function useOrgRate(orgId: string | null | undefined, pollMs: number) {
  return useQuery({
    queryKey: keys.orgRate(orgId ?? ""),
    queryFn: () => orgApi.rate(orgId!, 60),
    enabled: !!orgId,
    refetchInterval: pollMs,
    refetchIntervalInBackground: false,
  });
}
