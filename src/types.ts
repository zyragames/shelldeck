export type HostStatus = 'idle' | 'connected' | 'error';

export interface Host {
  id: string;
  name: string;
  hostname: string;
  user: string;
  port: number;
  groupId?: string;
  status: HostStatus;
  tags?: string[];
  identityFile?: string;
  extraArgs?: string;
}

export interface Group {
  id: string;
  name: string;
  isExpanded: boolean;
}

export interface Tab {
  id: string;
  hostId: string;
  isActive: boolean;
}
