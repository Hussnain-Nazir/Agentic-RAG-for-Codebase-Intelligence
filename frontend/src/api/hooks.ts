import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, uploadRepository } from "./client";
import type { IndexState } from "./types";

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
