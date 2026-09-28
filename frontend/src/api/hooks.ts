import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, uploadRepository } from "./client";
import type { ArchitectureResponse, ChangeImpactResponse, FlowTraceResponse, IndexState, ModelComparisonResponse, ModelSlot, RepositoryAnswer } from "./types";

const terminalStates: IndexState[] = ["READY", "PARTIAL", "FAILED"];

export function useRegister() {
  return useMutation({ mutationFn: ({ email, password }: { email: string; password: string }) => api.register(email, password) });
}
export function useLogin() {
  return useMutation({ mutationFn: ({ email, password }: { email: string; password: string }) => api.login(email, password) });
}
export function useInstallUrl() { return useMutation({ mutationFn: api.installUrl }); }
export function useInstallations() { return useQuery({ queryKey: ["installations"], queryFn: api.installations }); }
export function useInstallationRepositories(id: string | null) {
  return useQuery({ queryKey: ["installation-repositories", id], queryFn: () => api.installationRepositories(id!), enabled: !!id });
}
export function useBranches(installationId: string | null, repositoryId: number | null) {
  return useQuery({
    queryKey: ["branches", installationId, repositoryId],
    queryFn: () => api.branches(installationId!, repositoryId!),
    enabled: !!installationId && repositoryId !== null,
  });
}
export function useRepositories() { return useQuery({ queryKey: ["repositories"], queryFn: api.repositories }); }
export function useRepository(id: string) {
  return useQuery({ queryKey: ["repository", id], queryFn: () => api.repository(id), enabled: !!id });
}
export function useIndexStatus(id: string) {
  return useQuery({
    queryKey: ["index-status", id], queryFn: () => api.indexStatus(id), enabled: !!id,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state && terminalStates.includes(state) ? false : 2000;
    },
  });
}
export function useCreateGitHubRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ repositoryId, branch }: { repositoryId: number; branch: string }) => api.createGitHubRepository(repositoryId, branch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["repositories"] }),
  });
}
export function useUploadRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: File; onProgress: (percent: number) => void }) => uploadRepository(file, onProgress),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["repositories"] }),
  });
}

export function useModelsConfig() { return useQuery({ queryKey: ["models-config"], queryFn: api.modelsConfig }); }
export function useFiles(id: string, path: string) {
  return useQuery({ queryKey: ["files", id, path], queryFn: () => api.files(id, path), enabled: !!id });
}
export function useSymbols(id: string, query: string) {
  return useQuery({ queryKey: ["symbols", id, query], queryFn: () => api.symbols(id, query), enabled: !!id && !!query.trim() });
}
export function useFileContent(id: string, path: string | null, startLine?: number, endLine?: number) {
  return useQuery({
    queryKey: ["file-content", id, path, startLine, endLine],
    queryFn: () => api.fileContent(id, path!, startLine, endLine), enabled: !!id && !!path,
  });
}
export function useAgentTrace(runId: string | null) {
  return useQuery({ queryKey: ["agent-trace", runId], queryFn: () => api.agentTrace(runId!), enabled: !!runId });
}
export function useRepositoryMemory(id: string) {
  return useQuery({ queryKey: ["memory", id], queryFn: () => api.memory(id), enabled: !!id });
}
export function useFindings(id: string) {
  return useQuery({ queryKey: ["findings", id], queryFn: () => api.findings(id), enabled: !!id });
}
export function useResolvedEvidence(id: string, evidenceIds: string[]) {
  return useQuery({
    queryKey: ["resolved-evidence", id, evidenceIds],
    queryFn: async () => {
      const batches: string[][] = [];
      for (let index = 0; index < evidenceIds.length; index += 100) batches.push(evidenceIds.slice(index, index + 100));
      return (await Promise.all(batches.map((batch) => api.resolveEvidence(id, batch)))).flat();
    }, enabled: !!id && evidenceIds.length > 0,
  });
}
export function useSaveFinding(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ type, content, evidenceIds }: { type: "FLOW_TRACE" | "IMPACT"; content: Record<string, unknown>; evidenceIds: string[] }) =>
      api.saveFinding(id, type, content, evidenceIds),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["findings", id] }),
  });
}
export function useAnalysis(id: string) {
  type AnalysisResponse = { agent_run_id: string; answer: RepositoryAnswer }
    | { agent_run_id: string; trace: FlowTraceResponse }
    | { agent_run_id: string; impact: ChangeImpactResponse }
    | ArchitectureResponse | ModelComparisonResponse;
  return useMutation<AnalysisResponse, Error, { type: "ask" | "flow" | "impact" | "architecture" | "compare"; question: string; modelSlot: ModelSlot }>({
    mutationFn: async ({ type, question, modelSlot }) => {
      switch (type) {
        case "ask": return await api.ask(id, question, modelSlot);
        case "flow": return await api.flowTrace(id, question, modelSlot);
        case "impact": return await api.changeImpact(id, question, modelSlot);
        case "architecture": return await api.architecture(id, modelSlot);
        case "compare": return await api.compareModels(id, question);
      }
    },
  });
}
