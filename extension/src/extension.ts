import * as vscode from 'vscode';
import { createHash } from 'crypto';
import { DaemonClient } from './daemon-client';
import { ContextPanel } from './context-panel';
import { getConfig } from './config';
import { DaemonStatus, HealthResponse } from './types';

const SUPPORTED_LANGUAGES = new Set(['python', 'typescript', 'javascript', 'go', 'rust']);
const HEALTH_POLL_INTERVAL_MS = 30_000;

function getWorkspaceId(): string {
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? 'default';
  return createHash('sha256').update(workspaceRoot).digest('hex').slice(0, 8);
}

export function activate(context: vscode.ExtensionContext): void {
  
  const output = vscode.window.createOutputChannel('ContextWeave');
  output.appendLine('[INFO] ContextWeave activating…');

  
  const config = getConfig();
  const workspaceId = getWorkspaceId();

  
  const client = new DaemonClient(config.daemonHost, config.daemonPort, output);

  
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = 'contextweave.showContext';
  statusBar.text    = '$(sync~spin) CW…';
  statusBar.tooltip = 'ContextWeave — click to show context panel';
  statusBar.show();
  context.subscriptions.push(statusBar);

  
  function applyStatusBar(health: HealthResponse | null): void {
    if (!health) {
      statusBar.text  = '$(circle-slash) CW: Offline';
      statusBar.color = new vscode.ThemeColor('disabledForeground');
      statusBar.tooltip = 'ContextWeave daemon is unreachable';
      return;
    }

    if (health.status === 'ok' && health.provider_healthy) {
      statusBar.text  = '$(check) CW: OK';
      statusBar.color = '#3fb950'; 
      statusBar.tooltip = `ContextWeave · v${health.version} · ${health.chunks_total} chunks`;
    } else {
      statusBar.text  = '$(warning) CW: Degraded';
      statusBar.color = '#d29922'; 
      statusBar.tooltip = `ContextWeave degraded · provider_healthy=${health.provider_healthy}`;
    }
  }

  function daemonStatusFromHealth(health: HealthResponse | null): DaemonStatus {
    if (!health) return 'offline';
    return health.status === 'ok' ? 'online' : 'degraded';
  }

  
  void (async () => {
    const health = await client.health();
    applyStatusBar(health);
    const status = daemonStatusFromHealth(health);
    output.appendLine(`[INFO] Daemon status: ${status}`);
  })();

  
  let debounceTimer: ReturnType<typeof setTimeout> | undefined;

  const saveListener = vscode.workspace.onDidSaveTextDocument(async (document) => {
    if (!config.enabled) return;
    if (!SUPPORTED_LANGUAGES.has(document.languageId)) return;

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      output.appendLine(`[INFO] Ingesting ${document.fileName} (${document.languageId})`);

      const response = await client.ingest(
        document.fileName,
        document.getText(),
        document.languageId,
        workspaceId
      );

      if (!response) {
        output.appendLine('[DEBUG] Ingest returned null — daemon may be offline');
        return;
      }

      output.appendLine(
        `[INFO] Ingest complete: ${response.chunks} chunks, stuck=${response.stuck}`
      );

      if (response.stuck && config.autoOpenPanel) {
        output.appendLine('[INFO] Developer stuck — opening context panel');
        ContextPanel.createOrShow(
          context.extensionUri,
          client,
          output,
          workspaceId,
          document.fileName
        );
      } else if (response.stuck === false && ContextPanel.currentPanel) {
        
        ContextPanel.currentPanel.refreshFor(document.fileName);
      }
    }, config.debounceMs);
  });
  context.subscriptions.push(saveListener);

  
  const healthPollId = setInterval(async () => {
    const health = await client.health();
    applyStatusBar(health);
  }, HEALTH_POLL_INTERVAL_MS);

  context.subscriptions.push({ dispose: () => clearInterval(healthPollId) });

  
  const showCommand = vscode.commands.registerCommand('contextweave.showContext', () => {
    const activeFile =
      vscode.window.activeTextEditor?.document.fileName ?? '';
    if (!activeFile) {
      output.appendLine('[INFO] No active file — cannot open context panel');
      return;
    }
    ContextPanel.createOrShow(context.extensionUri, client, output, workspaceId, activeFile);
  });
  context.subscriptions.push(showCommand);

  
  context.subscriptions.push({
    dispose: () => clearTimeout(debounceTimer),
  });

  output.appendLine('[INFO] ContextWeave activated');
}

export function deactivate(): void {
  
}
