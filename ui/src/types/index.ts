/** types/index.ts — 前端全局类型定义 */

// ---------- 班级与单元 ----------

export interface ClassItem {
  class_id: string;
  name: string;
  description: string;
  unit_count: number;
  student_count: number;
}

export interface UnitItem {
  unit_id: string;
  name: string;
  description: string;
  is_default: boolean;
}

// ---------- 学生 ----------

export interface StudentItem {
  student_key: string;
  name: string;
  student_id: string;
  status: string;
  note: string;
  submit_status: 'submitted' | 'missing';
  audio_file: string | null;
}

export interface StudentForm {
  name: string;
  student_id: string;
  status: string;
  note: string;
}

// ---------- 素材 ----------

export interface FileStatus {
  standard_audio_ready: boolean;
  standard_text_ready: boolean;
  student_audio_count: number;
}

export interface StandardText {
  content: string;
  word_count: number;
  sentence_count: number;
}

// ---------- 任务 ----------

export type TaskStatus = 'idle' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface TaskProgressEvent {
  type: 'stage_progress' | 'student_progress';
  timestamp: string;
  stage?: string;
  status?: string;
  message?: string;
  student?: string;
  state?: { voice?: string; text?: string };
  current?: number;
  total?: number;
}

export interface TaskInfo {
  task_id: string;
  status: TaskStatus;
  class_id: string;
  unit_id: string;
  created_at: number;
  started_at: number;
  finished_at: number | null;
  current_stage: string;
  events: TaskProgressEvent[];
  logs: string[];
  log_path: string;
  exit_code?: number | null;
  progress?: TaskProgress;
}

export interface TaskProgress {
  total: number;
  voice_done: number;
  text_done: number;
  llm_done: number;
  stages: StageProgressItem[];
}

export interface StageProgressItem {
  stage: string;
  status: string;
  current?: number;
  total?: number;
  message?: string;
}

// ---------- 结果 ----------

export interface SummaryData {
  columns: string[];
  rows: Record<string, string | number>[];
}

export interface Statistics {
  student_count: number;
  average_score: number | null;
  max_score: number | null;
  min_score: number | null;
  pass_rate: number | null;
}

export interface StudentDetail {
  name: string;
  summary: Record<string, string | number>;
  report: string;
  errors: Record<string, unknown>;
  images: { relative_path: string }[];
  previous_student: string | null;
  next_student: string | null;
  report_relative_path: string | null;
}

// ---------- 错误分析 ----------

export type ErrorCategory = 'replace' | 'insert' | 'delete';

export interface ErrorAggregate {
  replace: Record<string, number>;
  insert: Record<string, number>;
  delete: Record<string, number>;
}

// ---------- 导出 ----------

export interface ExportFile {
  relative_path: string;
  filename: string;
  size: number;
}

// ---------- 配置 ----------

export interface LLMConfig {
  api_base: string;
  model: string;
  api_key: string;
  thinking: boolean;
  max_concurrency: number;
  timeout: number;
  max_tokens: number;
}

export interface WhisperConfig {
  model_name: string;
  full_model_name: string;
}

export interface ModuleSwitches {
  voice_analysis: boolean;
  whisper_transcribe: boolean;
  llm_compare: boolean;
  post_process: boolean;
  filter_precheck: boolean;
  error_visualize: boolean;
}

export interface AppConfig {
  llm: LLMConfig;
  whisper: WhisperConfig;
  modules: ModuleSwitches;
}

// ---------- 归档 ----------

export interface ArchivedItem {
  id: string;
  type: 'class' | 'unit' | 'student';
  name: string;
  class_id: string;
  unit_id: string;
  student_id: string;
  original_path: string;
  archived_path: string;
  archived_at: string;
}
