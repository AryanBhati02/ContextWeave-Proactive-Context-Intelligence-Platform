import * as vscode from 'vscode';
import { DaemonClient } from './daemon-client';
import { RankResponse, RankedChunk } from './types';
import { formatContextBlock, copyToClipboard } from './injector';

export class ContextPanel {
  public static currentPanel: ContextPanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private readonly _client: DaemonClient;
  private readonly _outputChannel: vscode.OutputChannel;
  private readonly _workspaceId: string;
  private _currentFilePath: string;
  private _disposables: vscode.Disposable[] = [];

  private constructor(
    panel: vscode.WebviewPanel,
    client: DaemonClient,
    outputChannel: vscode.OutputChannel,
    workspaceId: string,
    currentFilePath: string
  ) {
    this._panel = panel;
    this._client = client;
    this._outputChannel = outputChannel;
    this._workspaceId = workspaceId;
    this._currentFilePath = currentFilePath;

    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    this._panel.webview.onDidReceiveMessage(
      async (message: { command: string }) => {
        await this._handleMessage(message.command);
      },
      null,
      this._disposables
    );

    void this._update(currentFilePath);
  }

  public static createOrShow(
    extensionUri: vscode.Uri,
    client: DaemonClient,
    outputChannel: vscode.OutputChannel,
    workspaceId: string,
    currentFilePath: string
  ): void {
    const column = vscode.ViewColumn.Beside;

    if (ContextPanel.currentPanel) {
      ContextPanel.currentPanel._currentFilePath = currentFilePath;
      ContextPanel.currentPanel._panel.reveal(column, true);
      void ContextPanel.currentPanel._update(currentFilePath);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'contextweavePanel',
      'ContextWeave Context',
      { viewColumn: column, preserveFocus: true },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'dist')],
      }
    );

    ContextPanel.currentPanel = new ContextPanel(
      panel,
      client,
      outputChannel,
      workspaceId,
      currentFilePath
    );
  }

  public refreshFor(filePath: string): void {
    this._currentFilePath = filePath;
    void this._update(filePath);
  }

  private async _handleMessage(command: string): Promise<void> {
    try {
      if (command === 'copyContext') {
        const rankResponse = await this._client.rank(
          this._currentFilePath,
          8,
          this._workspaceId
        );
        if (rankResponse) {
          const block = formatContextBlock(rankResponse.query, rankResponse.chunks);
          await copyToClipboard(block);
          this._outputChannel.appendLine('[INFO] Context copied to clipboard');
        }
      } else if (command === 'askAI') {
        const rankResponse = await this._client.rank(
          this._currentFilePath,
          8,
          this._workspaceId
        );
        if (rankResponse) {
          const block = formatContextBlock(rankResponse.query, rankResponse.chunks);
          await copyToClipboard(block);
          await vscode.env.openExternal(vscode.Uri.parse('https://claude.ai/new'));
          this._outputChannel.appendLine('[INFO] Context copied; opened claude.ai');
        }
      } else if (command === 'notStuck') {
        await this._client.dismissStuck(this._currentFilePath, this._workspaceId);
        this._outputChannel.appendLine(`[INFO] Dismissed stuck for ${this._currentFilePath}`);
        this.dispose();
      }
    } catch (err) {
      this._outputChannel.appendLine(`[DEBUG] Panel message handler error: ${String(err)}`);
    }
  }

  private async _update(currentFilePath: string): Promise<void> {
    try {
      const rankResponse = await this._client.rank(currentFilePath, 8, this._workspaceId);
      this._panel.webview.html = this._getHtmlForWebview(rankResponse, currentFilePath);
    } catch (err) {
      this._outputChannel.appendLine(`[DEBUG] Panel update error: ${String(err)}`);
      this._panel.webview.html = this._getHtmlForWebview(null, currentFilePath);
    }
  }

  private _getHtmlForWebview(response: RankResponse | null, filePath: string): string {
    const fileName = filePath.split(/[\\/]/).pop() ?? filePath;
    const chunks = response?.chunks ?? [];
    const totalTokens = response?.total_tokens ?? 0;

    const chunkCards = chunks.length === 0
      ? `<div class="empty-state">
           <div class="empty-icon">⏳</div>
           <p>No ranked chunks yet. Save a file to begin ingestion.</p>
         </div>`
      : chunks.map((c: RankedChunk) => this._renderChunkCard(c)).join('');

    return  `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';" />
  <title>ContextWeave Context</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:        var(--vscode-editor-background);
      --fg:        var(--vscode-editor-foreground);
      --border:    var(--vscode-panel-border);
      --surface:   var(--vscode-sideBar-background, var(--vscode-editor-background));
      --accent:    var(--vscode-focusBorder, #007acc);
      --muted:     var(--vscode-descriptionForeground, #888);
      --code-bg:   var(--vscode-textCodeBlock-background, rgba(0,0,0,0.2));
      --btn-bg:    var(--vscode-button-background, #007acc);
      --btn-fg:    var(--vscode-button-foreground, #fff);
      --btn-hover: var(--vscode-button-hoverBackground, #005fa3);
      --success:   #3fb950;
      --warning:   #d29922;
      --radius: 6px;
      --gap: 12px;
    }

    body {
      background: var(--bg);
      color: var(--fg);
      font-family: var(--vscode-font-family, 'Segoe UI', system-ui, sans-serif);
      font-size: var(--vscode-font-size, 13px);
      padding: 16px;
      line-height: 1.5;
    }

    /* ── Header ── */
    .header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 14px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border);
    }
    .header-logo { font-size: 18px; }
    .header-title {
      font-size: 15px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    .header-meta {
      margin-left: auto;
      font-size: 11px;
      color: var(--muted);
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 2px;
    }
    .file-badge {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 2px 6px;
      font-size: 11px;
      font-family: var(--vscode-editor-font-family, monospace);
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    /* ── Action Buttons ── */
    .actions {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 6px 14px;
      border-radius: var(--radius);
      border: none;
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      transition: background 0.15s, transform 0.1s;
      outline: none;
    }
    .btn:active { transform: scale(0.97); }
    .btn-primary {
      background: var(--btn-bg);
      color: var(--btn-fg);
    }
    .btn-primary:hover { background: var(--btn-hover); }
    .btn-secondary {
      background: transparent;
      color: var(--fg);
      border: 1px solid var(--border);
    }
    .btn-secondary:hover { background: var(--code-bg); }
    .btn-danger {
      background: transparent;
      color: #f85149;
      border: 1px solid #f85149;
    }
    .btn-danger:hover { background: rgba(248, 81, 73, 0.12); }

    /* ── Toast ── */
    .toast {
      position: fixed;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%) translateY(60px);
      background: var(--btn-bg);
      color: var(--btn-fg);
      padding: 8px 18px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 500;
      opacity: 0;
      transition: transform 0.25s ease, opacity 0.25s ease;
      pointer-events: none;
      z-index: 999;
    }
    .toast.show {
      transform: translateX(-50%) translateY(0);
      opacity: 1;
    }

    /* ── Chunk Cards ── */
    .chunks-list { display: flex; flex-direction: column; gap: var(--gap); }

    .chunk-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
      transition: border-color 0.15s;
    }
    .chunk-card:hover { border-color: var(--accent); }

    .chunk-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      background: var(--code-bg);
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
    }
    .chunk-rank {
      font-size: 10px;
      font-weight: 700;
      color: var(--muted);
      background: var(--border);
      border-radius: 3px;
      padding: 1px 5px;
      flex-shrink: 0;
    }
    .chunk-name {
      font-weight: 600;
      font-size: 12px;
      font-family: var(--vscode-editor-font-family, monospace);
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .lang-badge {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 3px;
      background: rgba(0, 122, 204, 0.18);
      color: var(--accent);
      border: 1px solid rgba(0, 122, 204, 0.25);
      flex-shrink: 0;
    }
    .line-range {
      font-size: 10px;
      color: var(--muted);
      font-family: var(--vscode-editor-font-family, monospace);
      flex-shrink: 0;
    }

    /* ── Score Bar ── */
    .score-bar-wrap {
      padding: 6px 12px 4px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .score-bar-track {
      flex: 1;
      height: 5px;
      background: var(--border);
      border-radius: 3px;
      overflow: hidden;
      display: flex;
    }
    .score-bar-semantic {
      background: var(--success);
      height: 100%;
      transition: width 0.3s ease;
    }
    .score-bar-recency {
      background: var(--warning);
      height: 100%;
      transition: width 0.3s ease;
    }
    .score-label {
      font-size: 10px;
      color: var(--muted);
      white-space: nowrap;
    }
    .score-legend {
      display: flex;
      gap: 10px;
      padding: 0 12px 6px;
    }
    .score-legend-item {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 10px;
      color: var(--muted);
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
    .dot-semantic { background: var(--success); }
    .dot-recency  { background: var(--warning); }

    /* ── Code Block ── */
    .chunk-code {
      margin: 0 12px 12px;
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      overflow: auto;
      max-height: 220px;
    }
    .chunk-code pre {
      margin: 0;
      padding: 10px 12px;
      font-family: var(--vscode-editor-font-family, 'Cascadia Code', monospace);
      font-size: 11.5px;
      white-space: pre;
      line-height: 1.55;
    }

    /* ── Empty State ── */
    .empty-state {
      text-align: center;
      padding: 40px 20px;
      color: var(--muted);
    }
    .empty-icon { font-size: 32px; margin-bottom: 10px; }

    /* ── Footer ── */
    .footer {
      margin-top: 16px;
      padding-top: 10px;
      border-top: 1px solid var(--border);
      font-size: 10px;
      color: var(--muted);
      display: flex;
      justify-content: space-between;
    }
  </style>
</head>
<body>
  <div class="header">
    <span class="header-logo">⚡</span>
    <span class="header-title">ContextWeave</span>
    <div class="header-meta">
      <span class="file-badge" title="${escapeHtml(filePath)}">${escapeHtml(fileName)}</span>
      <span>${chunks.length} chunk${chunks.length !== 1 ? 's' : ''} · ${totalTokens} tokens</span>
    </div>
  </div>

  <div class="actions">
    <button class="btn btn-primary" id="btn-copy" onclick="sendCommand('copyContext')">
      📋 Copy Context
    </button>
    <button class="btn btn-secondary" id="btn-askai" onclick="sendCommand('askAI')">
      🤖 Ask AI
    </button>
    <button class="btn btn-danger" id="btn-notstuck" onclick="sendCommand('notStuck')">
      ✓ Not Stuck
    </button>
  </div>

  <div class="chunks-list">${chunkCards}</div>

  <div class="footer">
    <span>ContextWeave · semantic + recency ranking</span>
    <span>Query: <code>${escapeHtml(response?.query ?? fileName)}</code></span>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    const vscode = acquireVsCodeApi();

    function sendCommand(command) {
      vscode.postMessage({ command });
      if (command === 'copyContext') showToast('✓ Context copied!');
      if (command === 'askAI')     showToast('✓ Copied · Opening claude.ai…');
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      if (!t) return;
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 2200);
    }
  </script>
</body>
</html>`;

    function escapeHtml(str: string): string {
      return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }
  }

  private _renderChunkCard(chunk: RankedChunk, index?: number): string {
    const escapeHtml = (str: string): string =>
      str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');

    const totalScore = chunk.semantic_score + chunk.recency_score;
    const semanticPct = totalScore > 0 ? (chunk.semantic_score / totalScore) * 100 : 50;
    const recencyPct  = totalScore > 0 ? (chunk.recency_score  / totalScore) * 100 : 50;
    const scoreLabel  = (chunk.score * 100).toFixed(1) + '%';
    const fileName    = chunk.file_path.split(/[\\/]/).pop() ?? chunk.file_path;
    const rank        = index !== undefined ? index + 1 : '';

    return `
<div class="chunk-card">
  <div class="chunk-header">
    ${rank !== '' ? `<span class="chunk-rank">#${rank}</span>` : ''}
    <span class="chunk-name" title="${escapeHtml(chunk.chunk_name)}">${escapeHtml(chunk.chunk_name)}</span>
    <span class="lang-badge">${escapeHtml(chunk.language)}</span>
    <span class="line-range" title="${escapeHtml(chunk.file_path)}">${escapeHtml(fileName)} :${chunk.start_line}–${chunk.end_line}</span>
  </div>
  <div class="score-bar-wrap">
    <div class="score-bar-track">
      <div class="score-bar-semantic" style="width:${semanticPct.toFixed(1)}%"></div>
      <div class="score-bar-recency"  style="width:${recencyPct.toFixed(1)}%"></div>
    </div>
    <span class="score-label">${scoreLabel}</span>
  </div>
  <div class="score-legend">
    <span class="score-legend-item"><span class="dot dot-semantic"></span>Semantic ${(chunk.semantic_score * 100).toFixed(1)}%</span>
    <span class="score-legend-item"><span class="dot dot-recency"></span>Recency ${(chunk.recency_score * 100).toFixed(1)}%</span>
  </div>
  <div class="chunk-code"><pre>${escapeHtml(chunk.content)}</pre></div>
</div>`;
  }

  public dispose(): void {
    ContextPanel.currentPanel = undefined;
    this._panel.dispose();
    for (const d of this._disposables) {
      d.dispose();
    }
    this._disposables = [];
  }
}
