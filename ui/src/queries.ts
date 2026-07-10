// TanStack Query hooks with consistent poll cadences (ADR-08: poll, no websockets). Active
// pages refresh every 2s so a live incident's trace visibly grows; calm data every 10s.
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

const LIVE = 2000;
const CALM = 10000;

export const useIncidents = (status?: string) =>
  useQuery({
    queryKey: ["incidents", status ?? "all"],
    queryFn: () => api.listIncidents(status),
    refetchInterval: LIVE,
  });

export const useIncident = (id: string) =>
  useQuery({ queryKey: ["incident", id], queryFn: () => api.getIncident(id), refetchInterval: LIVE });

export const useSpans = (id: string) =>
  useQuery({ queryKey: ["spans", id], queryFn: () => api.getSpans(id), refetchInterval: LIVE });

export const useApprovals = (status?: string) =>
  useQuery({
    queryKey: ["approvals", status ?? "all"],
    queryFn: () => api.listApprovals(status),
    refetchInterval: LIVE,
  });

export const useMemories = (query: string, kind?: string) =>
  useQuery({
    queryKey: ["memories", query, kind ?? "all"],
    queryFn: () => api.listMemories(query, kind),
    refetchInterval: CALM,
  });

export const useDashboard = () =>
  useQuery({ queryKey: ["dashboard"], queryFn: () => api.dashboard(), refetchInterval: CALM });

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 15000 });

export const useEvalRuns = () =>
  useQuery({ queryKey: ["evalRuns"], queryFn: () => api.evalRuns(), refetchInterval: CALM });
