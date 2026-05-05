import * as vscode from 'vscode';

export interface ContextWeaveConfig {
  daemonPort: number;
  daemonHost: string;
  enabled: boolean;
  languages: string[];
  maxContextTokens: number;
  autoOpenPanel: boolean;
  debounceMs: number;
}

export function getConfig(): ContextWeaveConfig {
  const cfg = vscode.workspace.getConfiguration('contextweave');
  return {
    daemonPort: cfg.get<number>('daemonPort', 7331),
    daemonHost: cfg.get<string>('daemonHost', '127.0.0.1'),
    enabled: cfg.get<boolean>('enabled', true),
    languages: cfg.get<string[]>('languages', ['python', 'typescript', 'javascript', 'go', 'rust']),
    maxContextTokens: cfg.get<number>('maxContextTokens', 6000),
    autoOpenPanel: cfg.get<boolean>('autoOpenPanel', true),
    debounceMs: cfg.get<number>('debounceMs', 800),
  };
}
