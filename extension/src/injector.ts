import * as vscode from 'vscode';
import { RankedChunk } from './types';

export function formatContextBlock(query: string, chunks: RankedChunk[]): string {
  const lines: string[] = [
    '--- CONTEXTWEAVE CONTEXT ---',
    `Ranked by: semantic relevance + recency | Query: ${query}`,
    '',
  ];

  for (const chunk of chunks) {
    lines.push(`### ${chunk.chunk_name} (${chunk.file_path}:${chunk.start_line}-${chunk.end_line})`);
    lines.push('```' + chunk.language);
    lines.push(chunk.content);
    lines.push('```');
    lines.push('');
  }

  lines.push('--- END CONTEXT ---');
  return lines.join('\n');
}

export async function copyToClipboard(text: string): Promise<void> {
  await vscode.env.clipboard.writeText(text);
}
