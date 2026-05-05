import * as vscode from 'vscode';
import { RankResponse, IngestResponse, HealthResponse, StatusResponse } from './types';

export class DaemonClient {
  private readonly baseUrl: string;
  private readonly outputChannel: vscode.OutputChannel;
  private readonly timeoutMs = 2000;

  constructor(host: string, port: number, outputChannel: vscode.OutputChannel) {
    this.baseUrl = `http://${host}:${port}`;
    this.outputChannel = outputChannel;
  }

  async health(): Promise<HealthResponse | null> {
    return this.fetchWithTimeout<HealthResponse>(`${this.baseUrl}/health`);
  }

  async ingest(
    filePath: string,
    content: string,
    language: string,
    workspaceId: string
  ): Promise<IngestResponse | null> {
    return this.fetchWithTimeout<IngestResponse>(`${this.baseUrl}/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_path: filePath,
        content,
        language,
        workspace_id: workspaceId,
      }),
    });
  }

  async rank(
    query: string,
    topK: number = 8,
    workspaceId: string = 'default'
  ): Promise<RankResponse | null> {
    const params = new URLSearchParams({
      q: query,
      top_k: String(topK),
      workspace_id: workspaceId,
    });
    return this.fetchWithTimeout<RankResponse>(`${this.baseUrl}/rank?${params.toString()}`);
  }

  async dismissStuck(filePath: string, workspaceId: string = 'default'): Promise<boolean> {
    const params = new URLSearchParams({
      file_path: filePath,
      workspace_id: workspaceId,
    });
    const result = await this.fetchWithTimeout<{ reset: boolean }>(
      `${this.baseUrl}/stuck/dismiss?${params.toString()}`,
      { method: 'POST' }
    );
    return result?.reset ?? false;
  }

  async status(): Promise<StatusResponse | null> {
    return this.fetchWithTimeout<StatusResponse>(`${this.baseUrl}/status`);
  }

  private async fetchWithTimeout<T>(url: string, options?: RequestInit): Promise<T | null> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timeoutId);
      if (!response.ok) {
        this.outputChannel.appendLine(`[DEBUG] ${url} returned ${response.status}`);
        return null;
      }
      return (await response.json()) as T;
    } catch (error) {
      clearTimeout(timeoutId);
      this.outputChannel.appendLine(`[DEBUG] Daemon call failed: ${String(error)}`);
      return null;
    }
  }
}
