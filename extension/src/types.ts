export interface RankedChunk {
  id: string;
  chunk_name: string;
  file_path: string;
  language: string;
  start_line: number;
  end_line: number;
  content: string;
  score: number;
  semantic_score: number;
  recency_score: number;
}

export interface RankResponse {
  query: string;
  chunks: RankedChunk[];
  total_tokens: number;
}

export interface IngestResponse {
  status: string;
  chunks: number;
  stuck: boolean;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  queue_depth: number;
  provider_healthy: boolean;
  db_healthy: boolean;
  chunks_total: number;
}

export interface StatusResponse {
  uptime_seconds: number;
  chunks_ingested_total: number;
  rank_calls_total: number;
  provider: string;
  queue_depth: number;
}

export type DaemonStatus = 'online' | 'degraded' | 'offline';
