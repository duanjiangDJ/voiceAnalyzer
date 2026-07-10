<script setup lang="ts">
import MarkdownIt from 'markdown-it';
import * as echarts from 'echarts';
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { apiDelete, apiGet, apiPost, apiPut, downloadBlob, downloadUrl, onToast, toast, uploadForm } from './api';
import type {
  AppConfig, ArchivedItem, ClassItem, ErrorAggregate, ErrorCategory, ExportFile,
  FileStatus, StandardText, Statistics, StudentDetail, StudentForm,
  StudentItem, SummaryData, TaskInfo, UnitItem,
} from './types';

type NavKey = 'dashboard' | 'materials' | 'students' | 'results' | 'errors' | 'exports' | 'config';

const navItems: Array<[NavKey, string]> = [
  ['dashboard', '仪表盘'],
  ['materials', '教材管理'],
  ['students', '学生管理'],
  ['results', '结果总览'],
  ['errors', '错题分析'],
  ['exports', '数据导出'],
  ['config', '配置中心'],
];

// ---------- Toast ----------
interface ToastMsg { id: number; text: string; level: string }
const toasts = ref<ToastMsg[]>([]);
onMounted(() => onToast((msg) => {
  toasts.value = [...toasts.value, msg];
  setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== msg.id); }, 4000);
}));

// ---------- 核心状态 ----------
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true });
const active = ref<NavKey>('dashboard');
const message = ref('数据已从 resource/classes 读取。');

// ---------- 统一弹窗（替代浏览器 prompt/confirm/alert）----------
interface ModalState {
  visible: boolean;
  type: 'confirm' | 'prompt' | 'alert';
  title: string;
  message: string;
  defaultValue: string;
  resolve: ((value: string | boolean) => void) | null;
}
const modal = reactive<ModalState>({
  visible: false, type: 'alert', title: '', message: '', defaultValue: '', resolve: null,
});
const modalInput = ref('');

function showConfirm(message: string, title = '确认'): Promise<boolean> {
  return new Promise((resolve) => {
    modal.type = 'confirm';
    modal.title = title;
    modal.message = message;
    modal.defaultValue = '';
    modal.resolve = resolve as (v: string | boolean) => void;
    modal.visible = true;
  });
}
function showPrompt(message: string, defaultValue = '', title = '输入'): Promise<string | null> {
  return new Promise((resolve) => {
    modal.type = 'prompt';
    modal.title = title;
    modal.message = message;
    modal.defaultValue = defaultValue;
    modalInput.value = defaultValue;
    modal.resolve = resolve as (v: string | boolean) => void;
    modal.visible = true;
  });
}
function showAlert(message: string, title = '提示'): Promise<void> {
  return new Promise((resolve) => {
    modal.type = 'alert';
    modal.title = title;
    modal.message = message;
    modal.defaultValue = '';
    modal.resolve = () => resolve();
    modal.visible = true;
  });
}
function modalOk() {
  if (modal.type === 'prompt') { modal.resolve?.(modalInput.value || ''); }
  else { modal.resolve?.(true); }
  modal.visible = false;
}
function modalCancel() {
  modal.resolve?.(modal.type === 'prompt' ? null as unknown as string : false);
  modal.visible = false;
}
function onModalKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') modalOk();
  if (e.key === 'Escape') modalCancel();
}
const classId = ref('default-class');
const unitId = ref('default-unit');
const classes = ref<ClassItem[]>([]);
const units = ref<UnitItem[]>([]);
const fileStatus = ref<FileStatus>({ standard_audio_ready: false, standard_text_ready: false, student_audio_count: 0 });
const standardText = ref<StandardText>({ content: '', word_count: 0, sentence_count: 0 });
const students = ref<StudentItem[]>([]);
const task = ref<TaskInfo>({ status: 'idle', logs: [], events: [] } as unknown as TaskInfo);
const summary = ref<SummaryData>({ columns: [], rows: [] });
const stats = ref<Statistics>({ student_count: 0, average_score: null, max_score: null, min_score: null, pass_rate: null });
const selectedStudent = ref<Record<string, unknown> | null>(null);
const studentDetail = ref<StudentDetail | null>(null);
const detailOpen = ref(false);
const errors = ref<ErrorAggregate>({ replace: {}, insert: {}, delete: {} });
const errorSearch = ref('');
const selectedErrorType = ref<ErrorCategory>('replace');
const exportsState = ref<{ files: ExportFile[] }>({ files: [] });
const config = ref<AppConfig | null>(null);
const actualApiKey = ref('');
const apiKeyVisible = ref(false);
const consoleEl = ref<HTMLElement | null>(null);
let _consoleUserScrolled = false;
let _scrollRaf = 0;
const studentForm = ref<StudentForm>({ name: '', student_id: '', status: 'active', note: '' });
let eventSource: EventSource | null = null;
let chartInstance: echarts.ECharts | null = null;

// ---------- Loading 状态 ----------
const loading = ref({
  classes: false, units: false, files: false, students: false,
  config: false, task: false, results: false, errors: false, exports: false,
  studentDetail: false, saveConfig: false, startTask: false, saveStudent: false,
});

// ---------- 归档 ----------
const archivedItems = ref<ArchivedItem[]>([]);
const archivedOpen = ref(false);
const loadingArchived = ref(false);

// ---------- Computed ----------
const contextQuery = computed(() => `class_id=${encodeURIComponent(classId.value)}&unit_id=${encodeURIComponent(unitId.value)}`);
const title = computed(() => Object.fromEntries(navItems)[active.value]);
const pageSubtitle = computed(() => {
  const map: Record<string, string> = {
    dashboard: '系统状态概览、任务控制与成绩总览',
    materials: '管理当前单元的标准音频与标准文本',
    students: '管理班级学生名单与录音提交状态',
    results: '查看评估成绩表与学生详细报告',
    errors: '错题词云、错误词频统计与类型筛选',
    exports: '按班级与单元下载评估结果文件',
    config: 'LLM / Whisper / 模块开关等全局运行配置',
  };
  return map[active.value] || '';
});
const renderedReport = computed(() => markdown.render(studentDetail.value?.report || ''));
const currentClassName = computed(() => classes.value.find(c => c.class_id === classId.value)?.name || classId.value);
const currentUnitName = computed(() => units.value.find(u => u.unit_id === unitId.value)?.name || unitId.value);
const stageEvents = computed(() => (task.value.events || []).filter((item) => item.type === 'stage_progress').slice(-10));
const latestStudentEvents = computed(() => (task.value.events || []).filter((item) => item.type === 'student_progress').slice(-8));
const filteredErrors = computed(() => {
  const keyword = errorSearch.value.trim().toLowerCase();
  const map = errors.value[selectedErrorType.value] || {};
  return Object.entries(map)
    .filter(([word]) => !keyword || String(word).includes(keyword))
    .sort((a, b) => (b[1] as number) - (a[1] as number))
    .slice(0, 80);
});

const configDescriptions: Record<string, string> = {
  api_base: 'OpenAI 兼容接口地址，例如 DeepSeek API Base。',
  model: 'LLM 比对使用的模型名称。',
  api_key: '敏感信息，仅用于本机请求，默认掩码显示。',
  thinking: '启用 DeepSeek 思考模式，提升比对质量但会增加耗时和 token。',
  max_concurrency: 'LLM 并发请求数，过高可能触发限流。',
  timeout: '单次 LLM 请求超时时间，单位秒。',
  max_tokens: '单次响应最大 token 数，思考模式需要更高上限。',
  model_name: '流水线默认 Whisper 模型。',
  full_model_name: '独立运行或高精度模式使用的 Whisper 模型。',
  voice_analysis: 'Phase 2：启用 OpenSMILE 声学维度分析。',
  whisper_transcribe: 'Phase 3：启用 Whisper 语音转写。',
  llm_compare: 'Phase 3：启用 LLM 文本比对和错误标注。',
  post_process: 'Phase 5：启用 Excel 汇总和报告后处理。',
  filter_precheck: 'Phase 7：启用音频与结果完整性预检查。',
  error_visualize: 'Phase 8：启用错题词云和历史曲线生成。',
};

// ---------- 通用 safe wrapper ----------
async function safeCall<T>(key: keyof typeof loading.value, fn: () => Promise<T>, successMsg?: string): Promise<T | undefined> {
  loading.value[key] = true;
  try {
    const result = await fn();
    if (successMsg) toast.success(successMsg);
    return result;
  } catch (err: unknown) {
    // toast 已在 api.ts request() 中 emit
    console.error(`[${key}]`, err);
    return undefined;
  } finally {
    loading.value[key] = false;
  }
}

// ---------- 生命周期 ----------
onMounted(refreshAll);
onUnmounted(() => {
  if (eventSource) eventSource.close();
  if (chartInstance) chartInstance.dispose();
});

watch([classId, unitId], async () => {
  closeStudentDialog();
  await refreshContext();
});

async function refreshAll() {
  await loadClasses();
  await refreshContext();
  await loadConfig();
  await loadTask();
}

async function refreshContext() {
  await Promise.all([loadUnits(), loadFiles(), loadStudents(), loadResults(), loadErrors(), loadExports()]);
  drawScoreChart();
}

// ---------- 班级 ----------
async function loadClasses() {
  const data = await safeCall('classes', () => apiGet<{ items: ClassItem[]; current?: { class_id: string; unit_id: string } }>('/api/v1/classes'));
  if (!data) return;
  classes.value = data.items;
  classId.value = data.current?.class_id || classId.value;
  unitId.value = data.current?.unit_id || unitId.value;
}

async function loadUnits() {
  const data = await safeCall('units', () => apiGet<{ items: UnitItem[] }>(`/api/v1/classes/${classId.value}/units`));
  if (!data) return;
  units.value = data.items;
  if (!units.value.find(u => u.unit_id === unitId.value) && units.value[0]) unitId.value = units.value[0].unit_id;
}

async function createClass() {
  const name = await showPrompt('请输入班级名称', '', '新建班级');
  if (!name) return;
  const item = await safeCall('classes', () => apiPost<{ class_id: string }>('/api/v1/classes', { name, description: '' }), '班级已创建');
  await loadClasses();
  if (item) classId.value = item.class_id;
}

async function renameClass() {
  const current = classes.value.find(c => c.class_id === classId.value);
  const name = await showPrompt('请输入新的班级名称', current?.name || classId.value, '重命名班级');
  if (!name) return;
  await safeCall('classes', () => apiPut(`/api/v1/classes/${classId.value}`, { name, description: current?.description || '' }), '班级已重命名');
  await loadClasses();
}

async function archiveClass() {
  if (!await showConfirm('确认归档当前班级？默认班级不能归档，归档不会物理删除数据。', '归档班级')) return;
  const result = await safeCall('classes', () => apiDelete<{ archived?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}`));
  message.value = result?.archived ? '班级已归档' : (result?.reason || '操作完成');
  await loadClasses();
}

async function deleteClassPermanent() {
  if (!await showConfirm('⚠️ 物理删除班级将删除该班级下所有单元、音频、结果，不可恢复！确认继续？', '删除班级')) return;
  const result = await safeCall('classes', () => apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/permanent`));
  message.value = result?.deleted ? '班级已物理删除' : (result?.reason || '操作完成');
  await loadClasses();
}

// ---------- 单元 ----------
async function createUnit() {
  const name = await showPrompt('请输入单元名称', '', '新建单元');
  if (!name) return;
  const item = await safeCall('units', () => apiPost<{ unit_id: string }>(`/api/v1/classes/${classId.value}/units`, { name, description: '' }), '单元已创建');
  await loadUnits();
  if (item) unitId.value = item.unit_id;
}

async function renameUnit() {
  const current = units.value.find(u => u.unit_id === unitId.value);
  const name = await showPrompt('请输入新的单元名称', current?.name || unitId.value, '重命名单元');
  if (!name) return;
  await safeCall('units', () => apiPut(`/api/v1/classes/${classId.value}/units/${unitId.value}`, { name, description: current?.description || '' }), '单元已重命名');
  await loadUnits();
}

async function archiveUnit() {
  if (!await showConfirm('确认归档当前单元？默认单元不能归档，归档不会物理删除数据。', '归档单元')) return;
  const result = await safeCall('units', () => apiDelete<{ archived?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/units/${unitId.value}`));
  message.value = result?.archived ? '单元已归档' : (result?.reason || '操作完成');
  await loadUnits();
}

async function deleteUnitPermanent() {
  if (!await showConfirm('⚠️ 物理删除单元将删除所有班级中该单元的全部数据，不可恢复！确认继续？', '删除单元')) return;
  const result = await safeCall('units', () => apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/units/${unitId.value}/permanent`));
  message.value = result?.deleted ? '单元已物理删除' : (result?.reason || '操作完成');
  await loadUnits();
}

// ---------- 素材 ----------
async function loadFiles() {
  const [status, text] = await Promise.all([
    safeCall('files', () => apiGet<FileStatus>(`/api/v1/files/status?${contextQuery.value}`)),
    safeCall('files', () => apiGet<StandardText>(`/api/v1/files/standard-text?${contextQuery.value}`)),
  ]);
  if (status) fileStatus.value = status;
  if (text) standardText.value = text;
}

async function saveStandardText() {
  const result = await safeCall('files', () => apiPut<StandardText>(`/api/v1/files/standard-text?${contextQuery.value}`, { content: standardText.value.content }), '标准文本已保存');
  if (result) standardText.value = result;
}

async function uploadStandardAudio(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files?.[0]) return;
  const form = new FormData();
  form.append('file', input.files[0]);
  await safeCall('files', () => uploadForm(`/api/v1/files/standard-audio?${contextQuery.value}`, form), '标准音频已上传');
  await loadFiles();
  input.value = '';
}

async function uploadStudentFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files?.length) return;
  const form = new FormData();
  Array.from(input.files).forEach(file => form.append('files', file));
  const data = await safeCall('files', () => uploadForm<{ saved: unknown[]; rejected: unknown[] }>(`/api/v1/files/student-audios?${contextQuery.value}`, form));
  if (data) message.value = `已导入 ${data.saved.length} 个文件，拒绝 ${data.rejected.length} 个`;
  await Promise.all([loadStudents(), loadFiles()]);
  input.value = '';
}

// ---------- 学生 ----------
async function loadStudents() {
  const data = await safeCall('students', () => apiGet<{ items: StudentItem[] }>(`/api/v1/classes/${classId.value}/students?unit_id=${unitId.value}`));
  if (data) students.value = data.items;
}

async function saveStudent() {
  const data = await safeCall('saveStudent', () => apiPost<{ saved?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/students`, studentForm.value), '学生已保存');
  if (data?.saved !== false) {
    studentForm.value = { name: '', student_id: '', status: 'active', note: '' };
    await loadStudents();
  }
}

function editStudent(student: StudentItem) {
  studentForm.value = { name: student.name, student_id: student.student_id, status: student.status || 'active', note: student.note || '' };
}

async function archiveStudent(student: StudentItem) {
  if (!await showConfirm(`确认归档 ${student.name}？不会删除已上传音频和历史结果。`, '归档学生')) return;
  const data = await safeCall('students', () => apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/students/${student.student_id}`));
  message.value = data?.deleted ? '学生已归档' : (data?.reason || '操作完成');
  await loadStudents();
}

async function deleteStudentPermanent(student: StudentItem) {
  if (!await showConfirm(`⚠️ 物理删除 ${student.name} 将删除其所有音频和结果，不可恢复！确认继续？`, '删除学生')) return;
  const data = await safeCall('students', () => apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/students/${student.student_id}/permanent`));
  message.value = data?.deleted ? '学生已物理删除' : (data?.reason || '操作完成');
  await loadStudents();
}

async function importStudentsCsv(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files?.[0]) return;
  const form = new FormData();
  form.append('file', input.files[0]);
  const data = await safeCall('students', () => uploadForm<{ saved: unknown[]; rejected: unknown[] }>(`/api/v1/classes/${classId.value}/students/import-csv`, form));
  if (data) message.value = `导入 ${data.saved.length} 名学生，拒绝 ${data.rejected.length} 行`;
  await loadStudents();
  input.value = '';
}

// ---------- 任务 ----------
async function loadTask() {
  const data = await safeCall('task', () => apiGet<TaskInfo>('/api/v1/tasks/current'));
  if (data) task.value = data;
}

async function startTask() {
  loading.value.startTask = true;
  try {
    const data = await apiPost<{ task_id: string } & TaskInfo>('/api/v1/tasks', { class_id: classId.value, unit_id: unitId.value });
    task.value = data;
    active.value = 'dashboard';
    subscribeTask(data.task_id);
  } catch { /* toast already emitted */ }
  finally { loading.value.startTask = false; }
}

async function cancelTask() {
  if (!task.value.task_id) return;
  await safeCall('task', () => apiPost(`/api/v1/tasks/${task.value.task_id}/cancel`));
  await loadTask();
}

function subscribeTask(taskId: string) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/events/tasks/${taskId}`);
  eventSource.addEventListener('task', (event) => {
    const payload = JSON.parse((event as MessageEvent).data);
    task.value = payload.snapshot;
    _autoScrollConsole();
    if (['completed', 'failed', 'cancelled'].includes(task.value.status)) {
      eventSource?.close();
      refreshContext();
      if (task.value.status === 'completed') toast.success('评估任务已完成');
      else if (task.value.status === 'failed') toast.error('评估任务失败，请查看日志');
      else toast.warning('任务已取消');
    }
  });
  eventSource.onerror = () => {
    toast.warning('SSE 连接中断，将自动重连');
  };
}

function _autoScrollConsole() {
  const el = consoleEl.value;
  if (!el) return;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  if (!_consoleUserScrolled || atBottom) {
    cancelAnimationFrame(_scrollRaf);
    _scrollRaf = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
    _consoleUserScrolled = false;
  }
}
function _onConsoleScroll() {
  const el = consoleEl.value;
  if (!el) return;
  _consoleUserScrolled = el.scrollHeight - el.scrollTop - el.clientHeight >= 40;
}
function _stageLabel(stage: string): string {
  const map: Record<string, string> = {
    init: '初始化', standard_prepare: '标准预分析', student_scan: '音频扫描',
    voice_analysis: '语音分析', text_analysis: '文字比对', wait: '等待完成',
    post_process: '汇总 Excel', summary: '最终汇总', filter_precheck: '完整性检查',
    error_visualize: '错题可视化', completed: '完成',
  };
  return map[stage] || stage;
}

// ---------- 结果 ----------
async function loadResults() {
  const [summaryData, statsData] = await Promise.all([
    safeCall('results', () => apiGet<SummaryData>(`/api/v1/results/summary?${contextQuery.value}`)),
    safeCall('results', () => apiGet<Statistics>(`/api/v1/results/statistics?${contextQuery.value}`)),
  ]);
  if (summaryData) summary.value = summaryData;
  if (statsData) stats.value = statsData;
}

async function openStudent(row: Record<string, unknown>) {
  loading.value.studentDetail = true;
  selectedStudent.value = row;
  try {
    studentDetail.value = await apiGet<StudentDetail>(`/api/v1/results/students/${encodeURIComponent(String(row['学生']))}?${contextQuery.value}`);
    detailOpen.value = true;
  } catch {
    studentDetail.value = null;
  } finally {
    loading.value.studentDetail = false;
  }
}

async function openAdjacentStudent(studentKey: string | null) {
  if (!studentKey) return;
  await openStudent({ 学生: studentKey });
}

function closeStudentDialog() {
  detailOpen.value = false;
  selectedStudent.value = null;
  studentDetail.value = null;
}

// ---------- 错题 ----------
async function loadErrors() {
  const data = await safeCall('errors', () => apiGet<ErrorAggregate>(`/api/v1/results/errors/aggregate?${contextQuery.value}`));
  if (data) errors.value = data;
}

// ---------- 导出 ----------
async function loadExports() {
  const data = await safeCall('exports', () => apiGet<{ files: ExportFile[] }>(`/api/v1/exports/available?${contextQuery.value}`));
  if (data) exportsState.value = data;
}

function exportFile(file: ExportFile) {
  downloadBlob(`/api/v1/exports/download?${contextQuery.value}&relative_path=${encodeURIComponent(file.relative_path)}`, file.filename).catch(() => {
    // 回退到直接下载
    downloadUrl(`/api/v1/exports/download?${contextQuery.value}&relative_path=${encodeURIComponent(file.relative_path)}`);
  });
}

function previewUrl(relativePath: string) {
  return `/api/v1/exports/download?${contextQuery.value}&relative_path=${encodeURIComponent(relativePath)}`;
}

// ---------- 配置 ----------
async function loadConfig() {
  const data = await safeCall('config', () => apiGet<AppConfig & { __actual_api_key?: string }>('/api/v1/config'));
  if (data) {
    config.value = data;
    actualApiKey.value = (data as Record<string, unknown>).__actual_api_key as string || '';
  }
}

async function saveConfig() {
  loading.value.saveConfig = true;
  try {
    const data = await apiPut<{ saved?: boolean; config?: AppConfig }>('/api/v1/config', { config: config.value });
    if (data.config) config.value = data.config;
    toast.success('配置已保存');
  } catch { /* toast already emitted */ }
  finally { loading.value.saveConfig = false; }
}

// ---------- 归档管理 ----------
async function loadArchived() {
  loadingArchived.value = true;
  try {
    const data = await apiGet<{ items: ArchivedItem[] }>('/api/v1/archived');
    archivedItems.value = data.items || [];
  } catch { /* toast already emitted */ }
  finally { loadingArchived.value = false; }
}

async function restoreArchivedItem(item: ArchivedItem) {
  if (!await showConfirm(`确认复原「${item.name}」？将恢复到原始位置。`, '复原归档')) return;
  const result = await apiPost<{ restored?: boolean; reason?: string }>(`/api/v1/archived/${item.id}/restore`);
  if (result.restored) {
    toast.success(`${item.name} 已复原`);
    await loadArchived();
    await loadClasses();
  } else {
    toast.warning(result.reason || '复原失败');
  }
}

async function deleteArchivedPermanent(item: ArchivedItem) {
  if (!await showConfirm(`⚠️ 物理删除归档项「${item.name}」将彻底移除数据，不可恢复！确认继续？`, '删除归档')) return;
  const result = await apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/archived/${item.id}`);
  if (result.deleted) {
    toast.success(`${item.name} 已彻底删除`);
    archivedItems.value = archivedItems.value.filter(a => a.id !== item.id);
  }
}

function openArchived() {
  archivedOpen.value = true;
  loadArchived();
}

function closeArchived() {
  archivedOpen.value = false;
}

async function revealApiKey() {
  if (apiKeyVisible.value) {
    apiKeyVisible.value = false;
    return;
  }
  const ok = await showConfirm('API Key 是敏感信息。确认后将在当前页面短时显示，请避免截屏或共享屏幕。', '显示 API Key');
  if (!ok) return;
  apiKeyVisible.value = true;
  window.setTimeout(() => { apiKeyVisible.value = false; }, 15000);
}

// ---------- 图表 ----------
function drawScoreChart() {
  nextTick(() => {
    const el = document.getElementById('scoreChart');
    if (!el || !summary.value.rows?.length) return;
    // 复用或创建 ECharts 实例，防止内存泄漏
    const existing = echarts.getInstanceByDom(el);
    const chart = existing || echarts.init(el);
    if (!existing) chartInstance = chart;
    chart.setOption({
      tooltip: {},
      grid: { left: 36, right: 18, top: 24, bottom: 58 },
      xAxis: { type: 'category', data: summary.value.rows.map((row) => row['学生']), axisLabel: { rotate: 28 } },
      yAxis: { type: 'value', min: 0, max: 100 },
      series: [{ type: 'bar', data: summary.value.rows.map((row) => Number(row['总成绩'] || 0)), itemStyle: { color: '#2563eb', borderRadius: [4, 4, 0, 0] } }],
    });
  });
}

function sizeText(size: number) {
  if (!size) return '0 B';
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024).toFixed(1)} KB`;
}

const anyLoading = computed(() => Object.values(loading.value).some(Boolean));
</script>

<template>
  <div class="shell">
    <!-- ========== 侧边栏 ========== -->
    <aside class="sidebar">
      <div class="brand"><strong>语音仿读评估系统</strong><span>多维度评估仿读质量</span></div>
      <div class="context-card">
        <label>结果班级</label>
        <select v-model="classId"><option v-for="item in classes" :key="item.class_id" :value="item.class_id">{{ item.name }}</option></select>
        <label>结果单元</label>
        <select v-model="unitId"><option v-for="item in units" :key="item.unit_id" :value="item.unit_id">{{ item.name }}</option></select>
        <small>用于查看结果、错题和导出。</small>
      </div>
      <nav><button v-for="item in navItems" :key="item[0]" :class="{ active: active === item[0] }" @click="active = item[0]; drawScoreChart()">{{ item[1] }}</button></nav>
    </aside>

    <!-- ========== 主区域 ========== -->
    <main class="main">
      <header class="topbar">
        <div><h1>{{ title }}<span v-if="anyLoading" class="spinner inline-spinner"></span></h1><p>{{ pageSubtitle }}</p></div>
        <span class="pill">{{ currentClassName }} / {{ currentUnitName }}</span>
      </header>

      <!-- ========== 仪表盘 ========== -->
      <section v-if="active === 'dashboard'" class="view stack fade-in">
        <!-- 第一行：概览卡片 (3) + 成绩图 (7) -->
        <div class="dash-row">
          <div class="dash-cards">
            <div class="dash-card">
              <div class="dash-card-icon" :class="fileStatus.standard_audio_ready ? 'okay' : 'warn'">{{ fileStatus.standard_audio_ready ? '✓' : '!' }}</div>
              <div class="dash-card-body"><span>标准音频</span><strong>{{ fileStatus.standard_audio_ready ? '已就绪' : '缺失' }}</strong></div>
            </div>
            <div class="dash-card">
              <div class="dash-card-icon okay">{{ standardText.word_count > 0 ? '✓' : '!' }}</div>
              <div class="dash-card-body"><span>标准文本</span><strong>{{ standardText.word_count || 0 }} 词</strong><small>{{ standardText.sentence_count || 0 }} 句</small></div>
            </div>
            <div class="dash-card">
              <div class="dash-card-icon accent">{{ fileStatus.student_audio_count || 0 }}</div>
              <div class="dash-card-body"><span>已提交录音</span><strong>{{ fileStatus.student_audio_count || 0 }} 人</strong></div>
            </div>
            <div class="dash-card">
              <div class="dash-card-icon score">{{ stats.average_score ? (stats.average_score >= 70 ? '↑' : '↓') : '—' }}</div>
              <div class="dash-card-body"><span>班级均分</span><strong>{{ stats.average_score ?? '—' }}</strong><small>共 {{ stats.student_count || 0 }} 人</small></div>
            </div>
          </div>
          <div class="panel dash-chart"><h2>成绩分布</h2>
            <div v-if="loading.results" class="loading-overlay"><span class="spinner large"></span></div>
            <div v-else-if="!summary.rows?.length" class="empty-state"><p>暂无成绩数据</p><small>启动评估任务后此处将显示成绩分布图。</small></div>
            <div v-else id="scoreChart" class="chart"></div>
          </div>
        </div>

        <!-- 第二行：任务控制 -->
        <div class="panel task-panel">
          <div class="task-head">
            <div><h2>评估任务</h2><p v-if="task.status==='idle'">点击「启动评估」开始运行当前班级/单元的完整流水线。</p></div>
            <div class="task-state"><span class="status" :class="task.status">{{ task.status || 'idle' }}</span><small>{{ task.current_stage || '就绪' }}</small></div>
          </div>

          <!-- 进度条区域 -->
          <div class="progress-bars" v-if="stageEvents.length">
            <div class="pbar" v-for="event in stageEvents" :key="event.timestamp">
              <span class="pbar-label">{{ _stageLabel(event.stage) }}</span>
              <div class="pbar-track"><div class="pbar-fill" :class="event.status" :style="{ width: event.status==='done' ? '100%' : (event.status==='running' ? '65%' : event.status==='cancelled' ? '30%' : '0%') }"></div></div>
              <small class="pbar-msg">{{ event.message }}</small>
            </div>
          </div>

          <div class="student-events" v-if="latestStudentEvents.length"><span v-for="event in latestStudentEvents" :key="event.timestamp" class="pill">{{ event.student }} · V:{{ event.state?.voice || '-' }} T:{{ event.state?.text || '-' }}</span></div>

          <div class="actions" style="margin-bottom:14px">
            <button :class="{ loading: loading.startTask }" @click="startTask" :disabled="task.status === 'running' || loading.startTask">启动评估</button>
            <button class="danger" @click="cancelTask" :disabled="task.status !== 'running'">终止</button>
          </div>

          <div class="console" ref="consoleEl" @scroll="_onConsoleScroll"><div v-for="(line, index) in task.logs" :key="index" :class="{ error: line.includes('ERROR') || line.includes('Traceback'), warn: line.includes('警告') || line.includes('WARNING') }">{{ line }}</div></div>
        </div>
      </section>

      <!-- ========== 教材管理 ========== -->
      <section v-if="active === 'materials'" class="view stack fade-in">
        <div class="materials-row">
          <div class="panel"><h2>单元切换</h2><div class="inline-fields"><select v-model="unitId"><option v-for="item in units" :key="item.unit_id" :value="item.unit_id">{{ item.name }}</option></select><button class="secondary" @click="createUnit">新建单元</button><button class="secondary" @click="renameUnit">重命名单元</button><button class="danger" @click="archiveUnit">归档单元</button><button class="dark" @click="deleteUnitPermanent">删除</button></div><p class="hint"> 在此处切换单元。</p></div>
          <div class="panel audio-panel">
            <h2>标准音频</h2>
            <div class="audio-card">
              <div class="audio-card-icon" :class="fileStatus.standard_audio_ready ? 'okay' : 'warn'">{{ fileStatus.standard_audio_ready ? '✓' : '!' }}</div>
              <div class="audio-card-info">
                <strong v-if="fileStatus.standard_audio_ready && fileStatus.standard_audios?.[0]">{{ fileStatus.standard_audios[0].filename }}</strong>
                <strong v-else>尚未上传</strong>
                <small v-if="fileStatus.standard_audio_ready && fileStatus.standard_audios?.[0]">{{ sizeText(fileStatus.standard_audios[0].size) }}</small>
              </div>
              <label class="upload" :class="{ primary: !fileStatus.standard_audio_ready }">
                {{ fileStatus.standard_audio_ready ? '更换音频' : '选择音频' }}
                <input type="file" accept=".wav,.mp3,.m4a,.flac,.ogg,.mp4" @change="uploadStandardAudio" :disabled="loading.files">
              </label>
            </div>
          </div>
        </div>
        <div class="panel"><h2>当前单元标准文本</h2><textarea v-model="standardText.content" :disabled="loading.files"></textarea><div class="actions"><button @click="saveStandardText" :disabled="loading.files">保存文本</button><span class="pill">{{ standardText.sentence_count }} 句 / {{ standardText.word_count }} 词</span></div></div>
      </section>

      <!-- ========== 学生管理 ========== -->
      <section v-if="active === 'students'" class="view stack fade-in">
        <div class="panel page-context"><h2>班级 / 单元切换</h2><div class="inline-fields"><select v-model="classId"><option v-for="item in classes" :key="item.class_id" :value="item.class_id">{{ item.name }}</option></select><select v-model="unitId"><option v-for="item in units" :key="item.unit_id" :value="item.unit_id">{{ item.name }}</option></select><button class="secondary" @click="createClass">新建班级</button><button class="secondary" @click="renameClass">重命名班级</button><button class="danger" @click="archiveClass">归档班级</button><button class="dark" @click="deleteClassPermanent">删除班级</button></div><p class="hint">学生名单属于班级；录音提交状态属于当前单元。</p></div>
        <div class="panel"><h2>学生名单与上传</h2><div class="student-form"><input v-model="studentForm.name" placeholder="姓名"><input v-model="studentForm.student_id" placeholder="10位学号"><input v-model="studentForm.note" placeholder="备注"><button :class="{ loading: loading.saveStudent }" @click="saveStudent" :disabled="loading.saveStudent">保存学生</button><label class="upload">导入学生 CSV<input type="file" accept=".csv" @change="importStudentsCsv"></label><label class="upload primary">上传录音/压缩包<input type="file" multiple accept=".wav,.mp3,.m4a,.flac,.ogg,.mp4,.zip" @change="uploadStudentFiles"></label></div></div>
        <div class="panel"><h2>学生提交状态</h2>
          <div v-if="loading.students" class="loading-overlay"><span class="spinner large"></span></div>
          <div v-else-if="!students.length" class="empty-state"><p>暂无学生数据</p><small>请先添加学生名单或上传学生音频。</small></div>
          <div v-else class="table-wrap"><table><thead><tr><th>姓名</th><th>学号</th><th>名单状态</th><th>提交</th><th>音频</th><th>操作</th></tr></thead><tbody><tr v-for="item in students" :key="item.student_key"><td>{{ item.name }}</td><td>{{ item.student_id }}</td><td>{{ item.status }}</td><td><span class="badge" :class="item.submit_status">{{ item.submit_status === 'submitted' ? '已提交' : '未提交' }}</span></td><td>{{ item.audio_file || '-' }}</td><td><button class="secondary" @click="editStudent(item)">编辑</button><button class="danger" @click="archiveStudent(item)">归档</button><button class="dark" @click="deleteStudentPermanent(item)">删除</button></td></tr></tbody></table></div>
        </div>
      </section>

      <!-- ========== 结果总览 ========== -->
      <section v-if="active === 'results'" class="view stack fade-in">
        <div class="panel"><h2>结果总览</h2><p class="hint">当前查看：{{ currentClassName }} / {{ currentUnitName }}</p>
          <div v-if="loading.results" class="loading-overlay"><span class="spinner large"></span></div>
          <div v-else-if="!summary.rows?.length" class="empty-state"><p>暂无评估结果</p><small>请先在仪表盘启动评估任务。</small></div>
          <div v-else class="table-wrap"><table><thead><tr><th v-for="col in summary.columns" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="row in summary.rows" :key="String(row['学生'])" @click="openStudent(row)"><td v-for="col in summary.columns" :key="col">{{ row[col] }}</td></tr></tbody></table></div>
        </div>
      </section>

      <!-- ========== 错题分析 ========== -->
      <section v-if="active === 'errors'" class="view stack fade-in">
        <div class="wordclouds"><div class="panel" v-for="type in ['replace', 'insert', 'delete', 'all']" :key="type"><h2>{{ type }}</h2><img :src="previewUrl(`error_analysis/wordcloud_${type}.png`)" class="wordcloud" @error="($event.target as HTMLImageElement).style.display = 'none'" alt="词云图"><p class="hint">若图片为空，请在仪表盘启动评估或可视化阶段。</p></div></div>
        <div class="panel"><h2>错误词频</h2>
          <div v-if="loading.errors" class="loading-overlay"><span class="spinner"></span></div>
          <template v-else>
            <div class="actions"><button v-for="type in ['replace', 'insert', 'delete']" :key="type" :class="{ secondary: selectedErrorType !== type }" @click="selectedErrorType = type as ErrorCategory">{{ type }}</button><input v-model="errorSearch" placeholder="搜索单词"></div>
            <table><tbody><tr v-for="item in filteredErrors" :key="item[0]"><td>{{ item[0] }}</td><td>{{ item[1] }}</td></tr></tbody></table>
          </template>
        </div>
      </section>

      <!-- ========== 数据导出 ========== -->
      <section v-if="active === 'exports'" class="view stack fade-in">
        <div class="panel"><h2>按班级 / 单元导出</h2><p class="hint">导出内容限定为当前侧栏选择的班级与单元。</p>
          <div v-if="loading.exports" class="loading-overlay"><span class="spinner large"></span></div>
          <div v-else-if="!exportsState.files?.length" class="empty-state"><p>当前单元尚未生成可导出文件</p><small>评估完成后自动生成 Excel、CSV、PNG 等导出文件。</small></div>
          <div v-else class="table-wrap"><table><thead><tr><th>文件</th><th>类型</th><th>大小</th><th>操作</th></tr></thead><tbody><tr v-for="file in exportsState.files" :key="file.relative_path"><td>{{ file.relative_path }}</td><td>{{ file.filename.split('.').pop() }}</td><td>{{ sizeText(file.size) }}</td><td><button @click="exportFile(file)">下载</button></td></tr></tbody></table></div>
        </div>
      </section>

      <!-- ========== 配置中心 ========== -->
      <section v-if="active === 'config' && config" class="view stack fade-in">
        <div class="panel config-top"><h2>全局配置</h2><p>修改下方配置后点击「保存配置」使设置生效。</p><div class="actions"><button :class="{ loading: loading.saveConfig }" @click="saveConfig" :disabled="loading.saveConfig">保存配置</button><button class="dark" @click="openArchived">查看归档</button></div></div>
        <div class="panel"><h2>LLM 配置</h2><div class="config-grid"><div v-for="(value, key) in config.llm" :key="String(key)" class="config-item"><b>{{ key }}</b><span>{{ configDescriptions[String(key)] || '运行配置项。' }}</span><template v-if="key === 'api_key'"><span class="key-field"><input :type="apiKeyVisible ? 'text' : 'password'" :value="apiKeyVisible && actualApiKey ? actualApiKey : config.llm[key as keyof typeof config.llm]" @input="(e: Event) => { config!.llm[key as keyof typeof config.llm] = (e.target as HTMLInputElement).value; }"><button class="inline-btn" @click="revealApiKey">{{ apiKeyVisible ? '隐藏' : '显示' }}</button></span></template><input v-else v-model="config.llm[key as keyof typeof config.llm]"></div></div></div>
        <div class="panel"><h2>Whisper 配置</h2><div class="config-grid"><div v-for="(value, key) in config.whisper" :key="String(key)" class="config-item"><b>{{ key }}</b><span>{{ configDescriptions[String(key)] || '模型配置项。' }}</span><input v-model="config.whisper[key as keyof typeof config.whisper]"></div></div></div>
        <div class="panel"><h2>模块开关</h2><div class="switches"><label v-for="(_, key) in config.modules" :key="String(key)"><input type="checkbox" v-model="config.modules[key as keyof typeof config.modules]"><span>{{ key }}</span><small>{{ configDescriptions[String(key)] }}</small></label></div></div>
      </section>
    </main>

    <!-- ========== 学生详情 Modal ========== -->
    <div v-if="detailOpen" class="modal-backdrop" @click.self="closeStudentDialog">
      <section class="student-modal">
        <header><div><h2>{{ studentDetail?.name }}</h2><p>{{ studentDetail?.summary?.['单词准确率'] || '-' }} · 总分 {{ studentDetail?.summary?.['总成绩'] || '-' }} · 语音 {{ studentDetail?.summary?.['语音综合分'] || '-' }}</p></div><button class="secondary" @click="closeStudentDialog">关闭</button></header>
        <div class="modal-actions"><button class="secondary" :disabled="!studentDetail?.previous_student" @click="openAdjacentStudent(studentDetail!.previous_student)">上一位</button><button class="secondary" :disabled="!studentDetail?.next_student" @click="openAdjacentStudent(studentDetail!.next_student)">下一位</button><button v-if="studentDetail?.report_relative_path" @click="downloadBlob(previewUrl(studentDetail.report_relative_path), studentDetail.report_relative_path.split('/').pop() || 'report.md')">下载 Markdown</button></div>
        <div class="modal-body">
          <div v-if="loading.studentDetail" class="loading-overlay"><span class="spinner large"></span></div>
          <template v-else>
            <article class="report" v-html="renderedReport"></article>
            <aside><h3>图表</h3><img v-for="image in studentDetail?.images" :key="image.relative_path" :src="previewUrl(image.relative_path)" class="report-image" alt="报告图表"><h3>错误数据</h3><pre>{{ JSON.stringify(studentDetail?.errors || {}, null, 2) }}</pre></aside>
          </template>
        </div>
      </section>
    </div>

    <!-- ========== 归档管理弹窗 ========== -->
    <div v-if="archivedOpen" class="modal-backdrop" @click.self="closeArchived">
      <div class="app-modal" style="width: min(720px, 90vw); max-height: 80vh; display: flex; flex-direction: column;">
        <header><h3>归档管理</h3></header>
        <div class="modal-msg" style="flex: 1; overflow: auto;">
          <div v-if="loadingArchived" class="loading-overlay"><span class="spinner"></span>加载中...</div>
          <div v-else-if="!archivedItems.length" class="empty-state"><p>暂无归档内容</p><small>归档的班级、单元、学生将显示在此处。</small></div>
          <table v-else><thead><tr><th>类型</th><th>名称</th><th>归属</th><th>归档时间</th><th>操作</th></tr></thead><tbody>
            <tr v-for="item in archivedItems" :key="item.id">
              <td><span class="badge">{{ item.type === 'class' ? '班级' : item.type === 'unit' ? '单元' : '学生' }}</span></td>
              <td>{{ item.name }}</td>
              <td>{{ item.class_id }}{{ item.unit_id ? ' / ' + item.unit_id : '' }}</td>
              <td>{{ item.archived_at }}</td>
              <td><button class="secondary" @click="restoreArchivedItem(item)">复原</button><button class="dark" @click="deleteArchivedPermanent(item)">删除</button></td>
            </tr>
          </tbody></table>
        </div>
        <footer><button class="secondary" @click="closeArchived">关闭</button></footer>
      </div>
    </div>

    <!-- ========== 统一弹窗 ========== -->
    <div v-if="modal.visible" class="modal-backdrop" @click.self="modalCancel">
      <div class="app-modal" @keydown="onModalKeydown">
        <header><h3>{{ modal.title }}</h3></header>
        <div class="modal-msg"><p>{{ modal.message }}</p></div>
        <div v-if="modal.type === 'prompt'" class="modal-prompt"><input v-model="modalInput" @keydown="onModalKeydown" autofocus></div>
        <footer>
          <button v-if="modal.type !== 'alert'" class="secondary" @click="modalCancel">取消</button>
          <button @click="modalOk">{{ modal.type === 'confirm' || modal.type === 'prompt' ? '确定' : '关闭' }}</button>
        </footer>
      </div>
    </div>

    <!-- ========== Toast 通知 ========== -->
    <div class="toast-container">
      <div v-for="t in toasts" :key="t.id" :class="['toast-item', t.level]">
        <span>{{ t.text }}</span>
        <button @click="toasts = toasts.filter(x => x.id !== t.id)">&times;</button>
      </div>
    </div>
  </div>
</template>
