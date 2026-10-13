import { api } from "./client";

export interface Identity {
  uid: string;
  username: string;
  isAdmin: boolean;
}

export interface ModuleTab {
  id: string;
  name: string;
}

export interface ModuleMeta {
  id: string;
  displayName: string;
  icon: string;
  route: string;
  tabs: ModuleTab[];
}

export const sessionApi = {
  get: () => api<Identity>("session"),
  modules: () => api<{ modules: ModuleMeta[] }>("modules"),
};
