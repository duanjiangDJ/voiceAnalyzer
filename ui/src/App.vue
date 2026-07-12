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

type NavKey = 'dashboard' | 'materials' | 'students' | 'audio' | 'results' | 'errors' | 'exports' | 'config';

const navItems: Array<[NavKey, string]> = [
  ['dashboard', '仪表盘'],
  ['materials', '教材管理'],
  ['students', '班级管理'],
  ['audio', '音频管理'],
  ['results', '结果总览'],
  ['errors', '错误分析'],
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
const classId = ref('');
const unitId = ref('');
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
const errorSummaryRows = ref<{ word: string; count: number; error_type: string }[]>([]);
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

// ---------- 班级管理弹窗 ----------
const csvModalOpen = ref(false);
const csvFileInput = ref<HTMLInputElement | null>(null);
const csvFileName = ref('');
const studentAddOpen = ref(false);
const newStudentName = ref('');
const newStudentId = ref('');
const editStudentOpen = ref(false);
const editStudentName = ref('');
const editStudentId = ref('');
const editStudentTarget = ref<StudentItem | null>(null);

// ---------- 音频管理 ----------
interface AudioStatusItem { index: number; name: string; student_id: string; student_key: string; submit_status: string; submit_time: string; filename: string; score_status: string; }
interface BatchAudioItem { filename: string; student_name: string; student_id: string; status: string; status_text: string; valid: boolean; _file?: File; }
const audioStatus = ref<AudioStatusItem[]>([]);
const audioSingleOpen = ref(false);
const audioSingleFile = ref<File | null>(null);
const audioSingleFileName = ref('');
const audioSingleStudentName = ref('');
const audioSingleStudentId = ref('');
const audioBatchOpen = ref(false);
const audioBatchItems = ref<BatchAudioItem[]>([]);
const audioBatchEditIdx = ref(-1);
const audioBatchEditName = ref('');
const audioBatchEditId = ref('');
const audioBatchEditOpen = ref(false);
const imagePreviewUrl = ref('');

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

// ---------- 结果排序 ----------
const sortCol = ref('总成绩');
const sortDir = ref<'asc' | 'desc'>('desc');
const sortedRows = computed(() => {
  const rows = [...summary.value.rows];
  const col = sortCol.value;
  rows.sort((a, b) => {
    const va = Number(a[col]) || 0;
    const vb = Number(b[col]) || 0;
    return sortDir.value === 'asc' ? va - vb : vb - va;
  });
  return rows;
});
function toggleSort(col: string) {
  if (sortCol.value === col) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc';
  } else {
    sortCol.value = col;
    sortDir.value = 'desc';
  }
}

// ---------- Computed ----------
const contextQuery = computed(() => `class_id=${encodeURIComponent(classId.value)}&unit_id=${encodeURIComponent(unitId.value)}`);
const title = computed(() => Object.fromEntries(navItems)[active.value]);
const pageSubtitle = computed(() => {
  const map: Record<string, string> = {
    dashboard: '系统状态概览、任务控制与成绩总览',
    materials: '管理当前单元的标准音频与标准文本',
    students: '管理班级与学生名单',
    audio: '按班级与单元管理学生的仿读音频文件',
    results: '查看评估成绩表与学生详细报告',
    errors: '错误词云、错误词频统计',
    exports: '按班级与单元下载评估结果文件',
    config: 'LLM / Whisper / 模块开关等全局运行配置',
  };
  return map[active.value] || '';
});
const renderedReport = computed(() => markdown.render(studentDetail.value?.report || ''));
const currentClassName = computed(() => classes.value.find(c => c.class_id === classId.value)?.name || classId.value || '未选择');
const currentUnitName = computed(() => units.value.find(u => u.unit_id === unitId.value)?.name || unitId.value || '未选择');
const hasClass = computed(() => !!classId.value);
const hasUnit = computed(() => !!unitId.value);
const canStartTask = computed(() => {
  const reasons: string[] = [];
  if (!hasClass.value) reasons.push('请先创建班级');
  else if (!hasUnit.value) reasons.push('请先创建单元');
  else if (!students.value.length) reasons.push('班级没有学生');
  else if (!fileStatus.value.student_audio_count) reasons.push('还没有学生上传仿读音频');
  else if (!fileStatus.value.standard_audio_ready) reasons.push('标准音频尚未上传');
  else if (!standardText.value.word_count) reasons.push('标准文本尚未上传');
  return { ok: reasons.length === 0, reasons };
});
const stageEvents = computed(() => (task.value.events || []).filter((item) => item.type === 'stage_progress'));
const latestStudentEvents = computed(() => (task.value.events || []).filter((item) => item.type === 'student_progress').slice(-8));

const stageLabelMap: Record<string, string> = {
  standard_prepare: '标准预分析', voice_analysis: '语音分析', text_analysis: '文字比对',
  wait: '等待完成', post_process: '汇总 Excel', summary: '最终汇总',
  filter_precheck: '完整性检查', error_visualize: '错题可视化',
};

const filteredErrors = computed(() => {
  return errorSummaryRows.value
    .filter(item => item.error_type === selectedErrorType.value)
    .sort((a, b) => b.count - a.count);
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

let _lastClassId = '';

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

watch(active, async (val) => {
  if (val === 'audio') await loadAudioStatus();
  if (val === 'dashboard') { await loadResults(); await loadErrors(); drawScoreChart(); }
});

async function refreshAll() {
  await loadClasses();
  await refreshContext();
  await loadConfig();
  await loadTask();
}

async function refreshContext() {
  if (hasClass.value && hasUnit.value) {
    await Promise.all([loadUnits(), loadFiles(), loadResults(), loadErrors(), loadExports(), loadAudioStatus()]);
  } else {
    await loadUnits();
  }
  // 学生是班级级数据，仅班级变化时重载
  if (hasClass.value && (!students.value.length || classId.value !== _lastClassId)) {
    await loadStudents();
    _lastClassId = classId.value;
  }
  drawScoreChart();
}

// ---------- 班级 ----------
async function loadClasses() {
  const data = await safeCall('classes', () => apiGet<{ items: ClassItem[]; current?: { class_id: string; unit_id: string } }>('/api/v1/classes'));
  if (!data) return;
  classes.value = data.items;
  // 无选中班级时取第一个
  if (!classId.value && data.current?.class_id) classId.value = data.current.class_id;
  if (!unitId.value && data.current?.unit_id) unitId.value = data.current.unit_id;
}

async function loadUnits() {
  // 单元是共享的，不依赖班级。使用占位符确保 URL 有效。
  const cid = classId.value || '_';
  const data = await safeCall('units', () => apiGet<{ items: UnitItem[] }>(`/api/v1/classes/${cid}/units`));
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
  const deletedId = classId.value;
  const result = await safeCall('classes', () => apiDelete<{ archived?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}`));
  message.value = result?.archived ? '班级已归档' : (result?.reason || '操作完成');
  await loadClasses();
  if (classId.value === deletedId && classes.value[0]) classId.value = classes.value[0].class_id;
}

async function deleteClassPermanent() {
  if (!await showConfirm('⚠️ 物理删除班级将删除该班级下所有单元、音频、结果，不可恢复！确认继续？', '删除班级')) return;
  const deletedId = classId.value;
  const result = await safeCall('classes', () => apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/permanent`));
  message.value = result?.deleted ? '班级已物理删除' : (result?.reason || '操作完成');
  await loadClasses();
  if (classId.value === deletedId && classes.value[0]) classId.value = classes.value[0].class_id;
}

// ---------- 单元 ----------
async function createUnit() {
  const name = await showPrompt('请输入单元名称', '', '新建单元');
  if (!name) return;
  // 单元是共享的，用占位符 class_id
  const cid = classId.value || '_';
  const item = await safeCall('units', () => apiPost<{ unit_id: string }>(`/api/v1/classes/${cid}/units`, { name, description: '' }), '单元已创建');
  await loadUnits();
  if (item) unitId.value = item.unit_id;
}

async function renameUnit() {
  if (!hasUnit.value) return;
  const current = units.value.find(u => u.unit_id === unitId.value);
  const name = await showPrompt('请输入新的单元名称', current?.name || unitId.value, '重命名单元');
  if (!name) return;
  const cid = classId.value || '_';
  await safeCall('units', () => apiPut(`/api/v1/classes/${cid}/units/${unitId.value}`, { name, description: current?.description || '' }), '单元已重命名');
  await loadUnits();
}

async function archiveUnit() {
  if (!hasUnit.value) return;
  if (!await showConfirm('确认归档当前单元？归档不会物理删除数据。', '归档单元')) return;
  const deletedId = unitId.value;
  const cid = classId.value || '_';
  const result = await safeCall('units', () => apiDelete<{ archived?: boolean; reason?: string }>(`/api/v1/classes/${cid}/units/${unitId.value}`));
  message.value = result?.archived ? '单元已归档' : (result?.reason || '操作完成');
  await loadUnits();
  if (unitId.value === deletedId && units.value[0]) unitId.value = units.value[0].unit_id;
}

async function deleteUnitPermanent() {
  if (!hasUnit.value) return;
  if (!await showConfirm('⚠️ 物理删除单元将删除所有班级中该单元的全部数据，不可恢复！确认继续？', '删除单元')) return;
  const deletedId = unitId.value;
  const cid = classId.value || '_';
  const result = await safeCall('units', () => apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/classes/${cid}/units/${unitId.value}/permanent`));
  message.value = result?.deleted ? '单元已物理删除' : (result?.reason || '操作完成');
  await loadUnits();
  if (unitId.value === deletedId && units.value[0]) unitId.value = units.value[0].unit_id;
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

function downloadCsvTemplate() {
  const a = document.createElement('a');
  a.href = '/api/v1/classes/students/template';
  a.download = 'student_template.csv';
  a.click();
}

function openCsvModal() {
  csvFileName.value = '';
  csvFileInput.value = null;
  csvModalOpen.value = true;
}
function closeCsvModal() { csvModalOpen.value = false; }
function onCsvFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  csvFileName.value = input.files?.[0]?.name || '';
}
async function uploadCsv() {
  const input = csvFileInput.value as HTMLInputElement | null;
  if (!input?.files?.[0]) { toast.warning('请先选择 CSV 文件'); return; }
  const form = new FormData();
  form.append('file', input.files[0]);
  const data = await safeCall('students', () => uploadForm<{ saved: unknown[]; rejected: unknown[] }>(`/api/v1/classes/${classId.value}/students/import-csv`, form));
  if (data) {
    if (data.saved.length > 0) toast.success(`成功导入 ${data.saved.length} 名学生`);
    if (data.rejected.length > 0) toast.warning(`${data.rejected.length} 行数据格式不符，已跳过`);
    await loadStudents();
    closeCsvModal();
  }
}

function openStudentAdd() {
  newStudentName.value = '';
  newStudentId.value = '';
  studentAddOpen.value = true;
}
function closeStudentAdd() { studentAddOpen.value = false; }
async function submitAddStudent() {
  if (!newStudentName.value.trim()) { toast.warning('请输入姓名'); return; }
  if (!/^\d{10}$/.test(newStudentId.value.trim())) { toast.warning('学号必须为 10 位数字'); return; }
  const data = await safeCall('saveStudent', () => apiPost<{ saved?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/students`, {
    name: newStudentName.value.trim(),
    student_id: newStudentId.value.trim(),
    status: 'active',
    note: '',
  }));
  if (data?.saved !== false) {
    toast.success('学生已添加');
    closeStudentAdd();
    await loadStudents();
  }
}

function openEditStudent(student: StudentItem) {
  editStudentTarget.value = student;
  editStudentName.value = student.name;
  editStudentId.value = student.student_id;
  editStudentOpen.value = true;
}
function closeEditStudent() { editStudentOpen.value = false; }
async function submitEditStudent() {
  if (!editStudentTarget.value) return;
  if (!editStudentName.value.trim()) { toast.warning('请输入姓名'); return; }
  if (!/^\d{10}$/.test(editStudentId.value.trim())) { toast.warning('学号必须为 10 位数字'); return; }
  const data = await safeCall('saveStudent', () => apiPost<{ saved?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/students`, {
    name: editStudentName.value.trim(),
    student_id: editStudentId.value.trim(),
    status: editStudentTarget.value.status || 'active',
    note: editStudentTarget.value.note || '',
  }));
  if (data?.saved !== false) {
    toast.success('学生信息已更新');
    closeEditStudent();
    await loadStudents();
  }
}

async function deleteStudentPermanent(student: StudentItem) {
  if (!await showConfirm(`⚠️ 物理删除 ${student.name} 将删除其所有音频和结果，不可恢复！确认继续？`, '删除学生')) return;
  const data = await safeCall('students', () => apiDelete<{ deleted?: boolean; reason?: string }>(`/api/v1/classes/${classId.value}/students/${student.student_id}/permanent`));
  message.value = data?.deleted ? '学生已物理删除' : (data?.reason || '操作完成');
  await loadStudents();
}

// ---------- 音频管理 ----------
async function loadAudioStatus() {
  const data = await safeCall('files', () => apiGet<{ items: AudioStatusItem[] }>(`/api/v1/files/student-audio-status?${contextQuery.value}`));
  if (data) audioStatus.value = data.items;
}

// 单个上传
function openAudioSingle() {
  audioSingleFile.value = null;
  audioSingleFileName.value = '';
  audioSingleStudentName.value = '';
  audioSingleStudentId.value = '';
  audioSingleOpen.value = true;
}
function closeAudioSingle() { audioSingleOpen.value = false; }
function onAudioSingleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  audioSingleFile.value = file;
  audioSingleFileName.value = file.name;
  // 尝试从文件名解析
  const match = file.name.match(/^(.+)-(\d{10})\.(wav|mp3|m4a|flac|ogg|mp4)$/i);
  if (match) {
    audioSingleStudentName.value = match[1];
    audioSingleStudentId.value = match[2];
  }
}
async function submitAudioSingle() {
  if (!audioSingleFile.value) { toast.warning('请选择音频文件'); return; }
  const form = new FormData();
  form.append('file', audioSingleFile.value);
  const qs = `${contextQuery.value}&student_name=${encodeURIComponent(audioSingleStudentName.value)}&student_id=${encodeURIComponent(audioSingleStudentId.value)}`;
  const data = await safeCall('files', () => uploadForm(`/api/v1/files/student-audio/single?${qs}`, form));
  if (data?.saved !== false) {
    toast.success('音频已上传');
    closeAudioSingle();
    await loadAudioStatus();
  }
}

// 学生下拉选项（用于单上传和批量编辑）
function studentSelectOptions() {
  return students.value.map(s => ({ label: `${s.name} (${s.student_id})`, name: s.name, id: s.student_id }));
}
function onStudentSelectByLabel(label: string) {
  const opt = studentSelectOptions().find(o => o.label === label);
  if (opt) { audioSingleStudentName.value = opt.name; audioSingleStudentId.value = opt.id; }
}

// 批量上传
function openAudioBatch() {
  audioBatchItems.value = [];
  audioBatchOpen.value = true;
}
function closeAudioBatch() { audioBatchOpen.value = false; }
async function onAudioBatchFilesChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  if (!files.length) return;

  // 加载学生名单用于校验
  if (!students.value.length) await loadStudents();
  const studentIdSet = new Set(students.value.map(s => s.student_id));

  const items: BatchAudioItem[] = [];
  for (const file of files) {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    const validExts = ['.wav', '.mp3', '.m4a', '.flac', '.ogg', '.mp4'];
    if (!validExts.includes(ext)) {
      items.push({ filename: file.name, student_name: '-', student_id: '-', status: 'invalid_format', status_text: '格式不支持', valid: false, _file: file });
      continue;
    }
    const match = file.name.match(/^(.+)-(\d{10})\.(wav|mp3|m4a|flac|ogg|mp4)$/i);
    if (match) {
      const sid = match[2];
      if (studentIdSet.has(sid)) {
        items.push({ filename: file.name, student_name: match[1], student_id: sid, status: 'ok', status_text: '已识别', valid: true, _file: file });
      } else {
        items.push({ filename: file.name, student_name: match[1], student_id: sid, status: 'not_in_class', status_text: '不在班级中', valid: false, _file: file });
      }
    } else {
      items.push({ filename: file.name, student_name: '-', student_id: '-', status: 'unrecognized', status_text: '无法识别', valid: false, _file: file });
    }
  }
  audioBatchItems.value = items;
  input.value = '';
}

function openBatchEdit(idx: number) {
  audioBatchEditIdx.value = idx;
  const item = audioBatchItems.value[idx];
  audioBatchEditName.value = item.student_name === '-' ? '' : item.student_name;
  audioBatchEditId.value = item.student_id === '-' ? '' : item.student_id;
  audioBatchEditOpen.value = true;
}
function closeBatchEdit() { audioBatchEditOpen.value = false; }
function onBatchEditSelectByLabel(label: string) {
  const opt = studentSelectOptions().find(o => o.label === label);
  if (opt) { audioBatchEditName.value = opt.name; audioBatchEditId.value = opt.id; }
}
function submitBatchEdit() {
  const item = audioBatchItems.value[audioBatchEditIdx.value];
  if (!item) return;
  item.student_name = audioBatchEditName.value;
  item.student_id = audioBatchEditId.value;
  const studentIdSet = new Set(students.value.map(s => s.student_id));
  if (item.student_id && studentIdSet.has(item.student_id)) {
    item.status = 'ok'; item.status_text = '已识别'; item.valid = true;
  } else if (item.student_id) {
    item.status = 'not_in_class'; item.status_text = '不在班级中'; item.valid = false;
  } else {
    item.status = 'unrecognized'; item.status_text = '无法识别'; item.valid = false;
  }
  closeBatchEdit();
}

function removeBatchItem(idx: number) {
  audioBatchItems.value.splice(idx, 1);
}

async function submitAudioBatch() {
  const validItems = audioBatchItems.value.filter(i => i.valid && i._file);
  if (!validItems.length) { toast.warning('没有可提交的有效文件'); return; }
  const form = new FormData();
  const names: string[] = [];
  const ids: string[] = [];
  for (const item of validItems) {
    form.append('files', item._file!);
    names.push(item.student_name);
    ids.push(item.student_id);
  }
  const qs = `${contextQuery.value}&names=${encodeURIComponent(names.join(','))}&ids=${encodeURIComponent(ids.join(','))}`;
  const data = await safeCall('files', () => uploadForm<{ saved: string[]; failed: unknown[] }>(`/api/v1/files/student-audio/batch?${qs}`, form));
  if (data) {
    if (data.saved.length) toast.success(`成功上传 ${data.saved.length} 个音频`);
    if (data.failed.length) toast.warning(`${data.failed.length} 个文件上传失败`);
    closeAudioBatch();
    await loadAudioStatus();
  }
}

async function deleteAudioFile(filename: string) {
  if (!await showConfirm(`确认删除音频文件「${filename}」？`, '删除音频')) return;
  await safeCall('files', () => apiDelete(`/api/v1/files/student-audio/${encodeURIComponent(filename)}?${contextQuery.value}`));
  await loadAudioStatus();
}

async function deleteAudioResult(studentKey: string, studentName: string) {
  if (!await showConfirm(`确认删除「${studentName}」在当前单元的评分结果？`, '删除评分结果')) return;
  await safeCall('files', () => apiDelete(`/api/v1/files/student-result/${encodeURIComponent(studentKey)}?${contextQuery.value}`));
  await loadAudioStatus();
}

// ---------- 任务 ----------
async function loadTask() {
  const data = await safeCall('task', () => apiGet<TaskInfo>('/api/v1/tasks/current'));
  if (data) {
    task.value = data;
    // 页面刷新后，若任务仍在运行则自动重新订阅 SSE
    if (data.status === 'running' && data.task_id) {
      subscribeTask(data.task_id);
    }
  }
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
  // 立即禁用按钮，关闭 SSE（不等服务器响应）
  task.value = { ...task.value, status: 'cancelled' };
  if (eventSource) { eventSource.close(); eventSource = null; }
  toast.warning('任务已终止');
  try {
    await apiPost(`/api/v1/tasks/${task.value.task_id}/cancel`);
  } catch { /* 忽略：状态已在前端设置 */ }
  refreshContext();
}

function subscribeTask(taskId: string) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/events/tasks/${taskId}`);
  const TERMINAL = ['completed', 'failed', 'cancelled', 'not_found', 'idle'];
  eventSource.addEventListener('task', (event) => {
    const payload = JSON.parse((event as MessageEvent).data);
    task.value = payload.snapshot;
    _autoScrollConsole();
    if (TERMINAL.includes(task.value.status)) {
      eventSource?.close();
      eventSource = null;
      if (task.value.status === 'completed') { refreshContext(); toast.success('评估任务已完成'); }
      else if (task.value.status === 'failed') { refreshContext(); toast.error('评估任务失败，请查看日志'); }
    }
  });
  eventSource.onerror = () => {
    // 任务非运行中时关闭连接，阻止 EventSource 无限自动重连
    if (task.value.status !== 'running') {
      eventSource?.close();
      eventSource = null;
    }
  };
}

function _autoScrollConsole() {
  const el = consoleEl.value;
  if (!el) return;
  cancelAnimationFrame(_scrollRaf);
  _scrollRaf = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
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
  loading.value.errors = true;
  try {
    const url = `/api/v1/exports/download?${contextQuery.value}&relative_path=${encodeURIComponent('error_analysis/error_summary.csv')}`;
    const resp = await fetch(url);
    if (!resp.ok) { errorSummaryRows.value = []; return; }
    const text = await resp.text();
    const lines = text.trim().split('\n');
    if (lines.length < 2) { errorSummaryRows.value = []; return; }
    const rows: { word: string; count: number; error_type: string }[] = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = parseCSVLine(lines[i]);
      if (cols.length >= 3) {
        const word = cols[0].replace(/^"|"$/g, '').trim();
        const count = parseInt(cols[1]) || 0;
        const errorType = cols[2].trim();
        if (word && count > 0) rows.push({ word, count, error_type: errorType });
      }
    }
    errorSummaryRows.value = rows;
  } catch { errorSummaryRows.value = []; }
  finally { loading.value.errors = false; }
}

function parseCSVLine(line: string): string[] {
  const result: string[] = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') { inQuotes = !inQuotes; }
    else if (ch === ',' && !inQuotes) { result.push(current); current = ''; }
    else { current += ch; }
  }
  result.push(current);
  return result;
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
      xAxis: { type: 'category', data: summary.value.rows.map((row) => String(row['学生']).replace(/-\d{10}$/, '')), axisLabel: { rotate: 28 } },
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

// ---------- Markdown 比对解析 ----------
interface ComparisonItem { index: number; original: string; originalHtml: string; recognized: string; recognizedHtml: string; details: string; detailsHtml: string; knowledgeHtml: string; }
interface ReportStat { label: string; value: string; }
interface ParsedReport { transcription: string; standard: string; comparisons: ComparisonItem[]; stats: ReportStat[]; }
function parseReport(report: string): ParsedReport {
  const result: ParsedReport = { transcription: '', standard: '', comparisons: [], stats: [] };
  if (!report) return result;
  // 提取转写文本（兼容 **=== 标题 ===**）
  const transMatch = report.match(/\*{0,2}===+\s*转写文本\s*===+\*{0,2}\s*\n([\s\S]*?)(?=\n\*{0,2}===+\s*标准文本)/);
  if (transMatch) result.transcription = transMatch[1].trim();
  // 提取标准文本
  const stdMatch = report.match(/\*{0,2}===+\s*标准文本\s*===+\*{0,2}\s*\n([\s\S]*?)(?=\n\*{0,2}===+\s*LLM\s*比对结果)/);
  if (stdMatch) result.standard = stdMatch[1].trim();
  // 提取最终统计信息
  const statMatch = report.match(/统计信息[：:]\s*([^\n]+)/);
  if (statMatch) {
    result.stats = statMatch[1].split('|').map(part => {
      const trimmed = part.trim();
      const pieces = trimmed.split(/\s+/);
      return { label: pieces.slice(0, -1).join(' ') || trimmed, value: pieces.slice(-1)[0] || '' };
    });
  }
  // 提取比对条目
  const entries = report.split(/###\s*条目\s*(\d+)\s*\n/);
  for (let i = 1; i < entries.length; i += 2) {
    const idx = parseInt(entries[i]);
    const body = (entries[i + 1] || '').replace(/\n---[\s\S]*$/, '');
    const origMatch = body.match(/- \*\*标准原句\*\*[：:]\s*(.*)/);
    const recMatch = body.match(/- \*\*识别结果\*\*[：:]\s*(.*)/);
    const detailMatch = body.match(/- \*\*差异详情\*\*[：:]\s*([\s\S]*?)(?=\n- \*\*关联|\n---|\n统计信息|$)/);
    const knowledgeMatch = body.match(/- \*\*关联知识点\*\*[：:]?\s*([\s\S]*?)$/);
    const originalMd = origMatch ? origMatch[1].trim() : '';
    const recognizedMd = recMatch ? recMatch[1].trim() : '';
    const original = originalMd.replace(/\*\*/g, '').trim();
    const recognized = recognizedMd.replace(/\*\*/g, '').trim();
    const originalHtml = markdown.renderInline(originalMd);
    const recognizedHtml = markdown.renderInline(recognizedMd);
    let details = '';
    let detailsHtml = '';
    if (detailMatch) {
      const rawDetails = detailMatch[1];
      const lines = rawDetails.split('\n').map(l => l.trim()).filter(l => l);
      const detailHtmlLines: string[] = [];
      for (const line of lines) {
        let cleaned = line.replace(/^-\s*/, '').replace(/\*\*/g, '');
        const linkMatch = cleaned.match(/^(.+?)\[([^\]]+)\]\(([^)]+)\)(.*)$/);
        if (linkMatch) {
          const prefix = linkMatch[1], linkText = linkMatch[2], linkUrl = linkMatch[3], suffix = linkMatch[4];
          detailHtmlLines.push(`<b>·</b> ${prefix}<a href="${linkUrl}" target="_blank" style="color:#2563eb">${linkText}</a>${suffix}`);
        } else {
          detailHtmlLines.push(`<b>·</b> ${cleaned}`);
        }
      }
      details = detailHtmlLines.map(h => h.replace(/<[^>]+>/g, '')).join('\n');
      detailsHtml = detailHtmlLines.join('<br>');
    }
    // 解析关联知识点（可能包含链接）
    let knowledgeHtml = '';
    if (knowledgeMatch) {
      const kLines = knowledgeMatch[1].split('\n').map(l => l.trim().replace(/^-\s*/, '')).filter(l => l);
      const kHtmlLines: string[] = [];
      for (const line of kLines) {
        let cleaned = line.replace(/\*\*/g, '');
        const linkMatch = cleaned.match(/^(.+?)\[([^\]]+)\]\(([^)]+)\)(.*)$/);
        if (linkMatch) {
          kHtmlLines.push(`${linkMatch[1]}<a href="${linkMatch[3]}" target="_blank" style="color:#2563eb">${linkMatch[2]}</a>${linkMatch[4]}`);
        } else if (cleaned) {
          kHtmlLines.push(cleaned);
        }
      }
      knowledgeHtml = kHtmlLines.join('<br>');
    }
    result.comparisons.push({ index: idx, original, originalHtml, recognized, recognizedHtml, details, detailsHtml, knowledgeHtml });
  }
  return result;
}
const parsedReport = computed(() => studentDetail.value?.report ? parseReport(studentDetail.value.report) : null);
</script>

<template>
  <div class="shell">
    <!-- ========== 侧边栏 ========== -->
    <aside class="sidebar">
      <div class="brand"><strong>语音仿读评估系统</strong><span>多维度评估仿读质量</span></div>
      <div class="context-card">
        <label>班级</label>
        <select v-model="classId"><option value="" disabled>-- 请选择或新建班级 --</option><option v-for="item in classes" :key="item.class_id" :value="item.class_id">{{ item.name }}</option></select>
        <label>单元</label>
        <select v-model="unitId"><option value="" disabled>-- 请选择或新建单元 --</option><option v-for="item in units" :key="item.unit_id" :value="item.unit_id">{{ item.name }}</option></select>
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
          <div class="panel dash-chart"><h2>成绩分布<span v-if="loading.results" class="spinner inline-spinner"></span></h2>
            <div v-if="loading.results"></div>
            <div v-else-if="!sortedRows?.length" class="empty-state"><p>暂无成绩数据</p><small>启动评估任务后此处将显示成绩分布图。</small></div>
            <div v-else id="scoreChart" class="chart"></div>
          </div>
        </div>

        <!-- 第二行：任务控制 -->
        <div class="panel task-panel">
          <div class="task-head">
            <div><h2>评估任务<span v-if="hasClass && hasUnit" style="font-weight:400;font-size:16px;color:var(--muted);margin-left:10px">{{ currentClassName }} / {{ currentUnitName }}</span></h2><p v-if="task.status==='idle'">点击「启动评估」开始运行当前班级/单元的完整流水线。</p></div>
            <div class="task-state"><span class="status" :class="task.status">{{ task.status || 'idle' }}</span><small>{{ stageLabelMap[task.current_stage] || task.current_stage || '就绪' }}</small></div>
          </div>

          <div class="actions" style="margin-bottom:14px">
            <button :class="{ loading: loading.startTask }" @click="startTask" :disabled="task.status === 'running' || loading.startTask || !canStartTask.ok" :title="canStartTask.reasons.join('；') || ''">启动评估</button>
            <button class="danger" @click="cancelTask" :disabled="task.status !== 'running'">终止</button>
          </div>

          <div class="console" ref="consoleEl" @scroll="_onConsoleScroll"><div v-for="(line, index) in task.logs" :key="index" :class="{ error: line.includes('ERROR') || line.includes('Traceback'), warn: line.includes('警告') || line.includes('WARNING') }">{{ line }}</div></div>
        </div>
      </section>

      <!-- ========== 教材管理 ========== -->
      <section v-if="active === 'materials'" class="view stack fade-in">
        <div class="materials-row">
          <div class="panel"><h2>单元管理</h2><div class="inline-fields"><select v-model="unitId"><option value="" disabled>-- 请选择或新建 --</option><option v-for="item in units" :key="item.unit_id" :value="item.unit_id">{{ item.name }}</option></select><button class="secondary" @click="createUnit">新建单元</button><button class="secondary" @click="renameUnit" :disabled="!hasUnit">重命名单元</button><button class="danger" @click="archiveUnit" :disabled="!hasUnit">归档单元</button><button class="dark" @click="deleteUnitPermanent" :disabled="!hasUnit">删除</button></div><p class="hint">单元为共享教材，所有班级可见。请先新建或选择一个单元。</p></div>
          <div class="panel audio-panel">
            <h2>标准音频</h2>
            <div v-if="!hasUnit" class="empty-state"><p>请先选择或新建单元</p></div>
            <div v-else class="audio-card">
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
        <div class="panel"><h2>当前单元标准文本</h2><p v-if="!hasUnit" class="hint">请先选择或新建单元。</p><textarea v-else v-model="standardText.content" :disabled="loading.files"></textarea><div class="actions"><button @click="saveStandardText" :disabled="loading.files || !hasUnit">保存文本</button><span class="pill">{{ standardText.sentence_count }} 句 / {{ standardText.word_count }} 词</span></div></div>
      </section>

      <!-- ========== 班级管理 ========== -->
      <section v-if="active === 'students'" class="view stack fade-in">
        <div class="materials-row">
          <!-- 左侧：班级操作 -->
          <div class="panel"><h2>班级操作</h2><div class="inline-fields"><select v-model="classId"><option value="" disabled>-- 请选择或新建 --</option><option v-for="item in classes" :key="item.class_id" :value="item.class_id">{{ item.name }}</option></select><button class="secondary" @click="createClass">新建班级</button><button class="secondary" @click="renameClass" :disabled="!hasClass">重命名班级</button><button class="danger" @click="archiveClass" :disabled="!hasClass">归档班级</button><button class="dark" @click="deleteClassPermanent" :disabled="!hasClass">删除</button></div><p class="hint">新建班级后请在此选择，下方名单自动更新。</p></div>
          <!-- 右侧：学生名单操作 -->
          <div class="panel"><h2>学生名单</h2>
            <div class="actions" style="margin-top:0">
              <button class="secondary" @click="openCsvModal" :disabled="!hasClass">上传名单</button>
              <button class="secondary" @click="openCsvModal" :disabled="!hasClass">更换名单</button>
              <button class="secondary" @click="openStudentAdd" :disabled="!hasClass">添加学生</button>
            </div>
            <p class="hint"><template v-if="!hasClass">请先选择或新建班级。</template><template v-else>支持 CSV 批量导入或逐个添加。上传/更换将弹出操作面板。</template></p>
          </div>
        </div>
        <!-- 学生名单表格 -->
        <div class="panel">
          <h2>{{ currentClassName }} · 学生名单<span v-if="loading.students" class="spinner inline-spinner"></span></h2>
          <div v-if="!students.length && !loading.students" class="empty-state"><p>暂无学生数据</p><small>请通过上方「上传名单」或「添加学生」录入。</small></div>
          <div v-else class="table-wrap"><table><thead><tr><th style="width:60px">序号</th><th>姓名</th><th>学号</th><th style="width:140px">操作</th></tr></thead><tbody><tr v-for="(item, idx) in students" :key="item.student_key"><td>{{ idx + 1 }}</td><td>{{ item.name }}</td><td>{{ item.student_id }}</td><td><button class="secondary" @click="openEditStudent(item)">编辑</button><button class="dark" @click="deleteStudentPermanent(item)">删除</button></td></tr></tbody></table></div>
        </div>
      </section>

      <!-- ========== 音频管理 ========== -->
      <section v-if="active === 'audio'" class="view stack fade-in">
        <div class="panel">
          <h2>音频上传</h2>
          <div class="actions" style="margin-top:0">
            <button class="secondary" @click="openAudioSingle" :disabled="!hasClass || !hasUnit">上传单个学生</button>
            <button class="secondary" @click="openAudioBatch" :disabled="!hasClass || !hasUnit">批量上传</button>
          </div>
          <p class="hint"><template v-if="!hasClass">请先在「班级管理」中创建班级。</template><template v-else-if="!hasUnit">请先在「教材管理」中创建单元。</template><template v-else>音频将存入侧栏所选班级与单元的仿读音频目录。支持 .mp3 .wav .m4a .flac .ogg .mp4 格式。</template></p>
        </div>
        <div class="panel">
          <h2>{{ currentClassName }} / {{ currentUnitName }} · 音频提交状态<span v-if="loading.files" class="spinner inline-spinner"></span></h2>
          <div v-if="!audioStatus.length && !loading.files" class="empty-state"><p>暂无学生数据</p><small>请先在「班级管理」中添加学生名单。</small></div>
          <div v-else class="table-wrap"><table><thead><tr><th style="width:50px">序号</th><th>姓名</th><th>学号</th><th>提交状态</th><th>提交时间</th><th>文件名称</th><th>评分状态</th><th style="width:180px">操作</th></tr></thead><tbody><tr v-for="item in audioStatus" :key="item.student_key" style="text-align:center">
            <td>{{ item.index }}</td>
            <td>{{ item.name }}</td>
            <td>{{ item.student_id }}</td>
            <td><span class="badge" :class="item.submit_status">{{ item.submit_status === 'submitted' ? '已提交' : '未提交' }}</span></td>
            <td>{{ item.submit_time }}</td>
            <td style="text-align:left">{{ item.filename }}</td>
            <td><span class="badge" :class="{ missing: item.score_status==='未评分', submitted: item.score_status==='已评分' }">{{ item.score_status }}</span></td>
            <td>
              <button class="secondary" style="padding:4px 8px;font-size:12px" :disabled="item.score_status==='未评分'" @click="deleteAudioResult(item.student_key, item.name)">删结果</button>
              <button class="dark" style="padding:4px 8px;font-size:12px" :disabled="item.submit_status==='missing'" @click="deleteAudioFile(item.filename)">删音频</button>
            </td>
          </tr></tbody></table></div>
        </div>
      </section>

      <!-- ========== 结果总览 ========== -->
      <section v-if="active === 'results'" class="view stack fade-in">
        <div class="panel"><h2>结果总览</h2><p class="hint">当前查看：{{ currentClassName }} / {{ currentUnitName }}</p>
          <div v-if="!loading.results && !summary.rows?.length" class="empty-state"><p>暂无评估结果</p><small>请先在仪表盘启动评估任务。</small></div>
          <div v-else class="table-wrap"><table><thead><tr><th v-for="col in summary.columns" :key="col" :style="col==='学生' ? '' : 'cursor:pointer;user-select:none'" @click="col!=='学生' && toggleSort(col)">{{ col }}<span v-if="col!=='学生'" style="margin-left:4px;font-size:11px">{{ sortCol===col ? (sortDir==='asc' ? '▲' : '▼') : '⇅' }}</span></th></tr></thead><tbody><tr v-for="row in sortedRows" :key="String(row['学生'])" @click="openStudent(row)"><td v-for="col in summary.columns" :key="col">{{ row[col] }}</td></tr></tbody></table></div>
        </div>
      </section>

      <!-- ========== 错误分析 ========== -->
      <section v-if="active === 'errors'" class="view stack fade-in">
        <div class="wordclouds"><div class="panel" v-for="type in ['replace', 'insert', 'delete', 'all']" :key="type"><h2>{{ type }}</h2><img :src="previewUrl(`error_analysis/wordcloud_${type}.png`)" class="wordcloud zoomable-image" @error="($event.target as HTMLImageElement).style.display = 'none'" @click="imagePreviewUrl = previewUrl(`error_analysis/wordcloud_${type}.png`)" alt="词云图"><p class="hint">若图片为空，请在仪表盘启动评估或可视化阶段。</p></div></div>
        <div class="panel"><h2>错误词频<span v-if="loading.errors" class="spinner inline-spinner"></span></h2>
          <template v-if="!loading.errors">
            <div class="actions"><button v-for="type in ['replace', 'insert', 'delete']" :key="type" :class="{ secondary: selectedErrorType !== type }" @click="selectedErrorType = type as ErrorCategory">{{ type }}</button></div>
            <div class="table-wrap"><table><thead><tr><th>单词</th><th>频率（次）</th></tr></thead><tbody><tr v-for="item in filteredErrors" :key="item.word"><td>{{ item.word }}</td><td>{{ item.count }}</td></tr></tbody></table></div>
          </template>
        </div>
      </section>

      <!-- ========== 数据导出 ========== -->
      <section v-if="active === 'exports'" class="view stack fade-in">
        <div class="panel"><h2>按班级 / 单元导出<span v-if="loading.exports" class="spinner inline-spinner"></span></h2><p class="hint">导出内容限定为当前侧栏选择的班级与单元。</p>
          <div v-if="!loading.exports && !exportsState.files?.length" class="empty-state"><p>当前单元尚未生成可导出文件</p><small>评估完成后自动生成 Excel、CSV、PNG 等导出文件。</small></div>
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

    <!-- ========== 单个音频上传弹窗 ========== -->
    <div v-if="audioSingleOpen" class="modal-backdrop" @click.self="closeAudioSingle">
      <div class="app-modal" style="width: min(520px, 90vw)">
        <header><h3>上传单个学生音频</h3></header>
        <div class="modal-msg" style="max-height:60vh;overflow:auto">
          <div style="display:grid;gap:12px">
            <div>
              <label class="upload primary" style="display:inline-flex">选择音频文件<input type="file" accept=".wav,.mp3,.m4a,.flac,.ogg,.mp4" @change="onAudioSingleFileChange"></label>
              <span v-if="audioSingleFileName" style="margin-left:10px;color:var(--muted)">{{ audioSingleFileName }}</span>
            </div>
            <p class="hint" v-if="!audioSingleFileName">支持格式：.mp3 .wav .m4a .flac .ogg .mp4<br>文件名如含「姓名-学号」格式将自动识别。</p>
            <div>
              <label style="font-size:13px;color:var(--muted)">选择学生（下拉选择后自动填入）：</label>
              <select style="width:100%;margin-top:4px" @change="onStudentSelectByLabel(($event.target as HTMLSelectElement).value)">
                <option value="">-- 请选择或由文件名自动识别 --</option>
                <option v-for="s in students" :key="s.student_id" :value="`${s.name} (${s.student_id})`">{{ s.name }} ({{ s.student_id }})</option>
              </select>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
              <div><label style="font-size:13px;color:var(--muted)">姓名</label><input v-model="audioSingleStudentName" placeholder="自动识别或手动填写" style="width:100%"></div>
              <div><label style="font-size:13px;color:var(--muted)">学号</label><input v-model="audioSingleStudentId" placeholder="10位数字" style="width:100%"></div>
            </div>
          </div>
        </div>
        <footer>
          <button class="secondary" @click="closeAudioSingle">取消</button>
          <button @click="submitAudioSingle" :disabled="!audioSingleFile">上传</button>
        </footer>
      </div>
    </div>

    <!-- ========== 批量音频上传弹窗 ========== -->
    <div v-if="audioBatchOpen" class="modal-backdrop" @click.self="closeAudioBatch">
      <div class="app-modal" style="width: min(800px, 92vw); max-height: 85vh; display: flex; flex-direction: column;">
        <header><h3>批量上传音频</h3></header>
        <div class="modal-msg" style="flex:1;overflow:auto">
          <div style="margin-bottom:12px">
            <label class="upload primary" style="display:inline-flex">选择音频文件（可多选）<input type="file" multiple accept=".wav,.mp3,.m4a,.flac,.ogg,.mp4,.zip" @change="onAudioBatchFilesChange"></label>
            <span style="margin-left:10px;color:var(--muted);font-size:13px">支持音频文件及 .zip 压缩包</span>
          </div>
          <div v-if="audioBatchItems.length" class="table-wrap">
            <table><thead><tr><th style="width:50px">序号</th><th>姓名</th><th>学号</th><th>校验状态</th><th>文件名称</th><th style="width:100px">操作</th></tr></thead><tbody>
              <tr v-for="(item, idx) in audioBatchItems" :key="idx" :style="{ background: item.valid ? '' : '#fff0f0' }">
                <td>{{ idx + 1 }}</td>
                <td>{{ item.student_name }}</td>
                <td>{{ item.student_id }}</td>
                <td><span class="badge" :class="{ missing: !item.valid }">{{ item.status_text }}</span></td>
                <td>{{ item.filename }}</td>
                <td>
                  <button class="secondary" @click="openBatchEdit(idx)" style="padding:4px 8px;font-size:12px">编辑</button>
                  <button class="dark" @click="removeBatchItem(idx)" style="padding:4px 8px;font-size:12px">删除</button>
                </td>
              </tr>
            </tbody></table>
          </div>
          <p v-if="audioBatchItems.length" class="hint" style="margin-top:8px">浅红底色行需手动编辑以指定姓名学号。</p>
          <p v-else class="empty-state"><small>请先选择音频文件，支持多选或上传 .zip 压缩包。</small></p>
        </div>
        <footer>
          <button class="secondary" @click="closeAudioBatch">取消</button>
          <button @click="submitAudioBatch" :disabled="!audioBatchItems.filter(i=>i.valid).length">确认上传</button>
        </footer>
      </div>
    </div>

    <!-- ========== 批量编辑弹窗 ========== -->
    <div v-if="audioBatchEditOpen" class="modal-backdrop" @click.self="closeBatchEdit">
      <div class="app-modal">
        <header><h3>编辑学生信息</h3></header>
        <div class="modal-msg">
          <p class="hint">为「{{ audioBatchItems[audioBatchEditIdx]?.filename }}」指定姓名学号。</p>
          <div style="margin-bottom:10px">
            <select style="width:100%" @change="onBatchEditSelectByLabel(($event.target as HTMLSelectElement).value)">
              <option value="">-- 选择学生 --</option>
              <option v-for="s in students" :key="s.student_id" :value="`${s.name} (${s.student_id})`">{{ s.name }} ({{ s.student_id }})</option>
            </select>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
            <input v-model="audioBatchEditName" placeholder="姓名">
            <input v-model="audioBatchEditId" placeholder="学号">
          </div>
        </div>
        <footer>
          <button class="secondary" @click="closeBatchEdit">取消</button>
          <button @click="submitBatchEdit">确定</button>
        </footer>
      </div>
    </div>

    <!-- ========== CSV 上传弹窗 ========== -->
    <div v-if="csvModalOpen" class="modal-backdrop" @click.self="closeCsvModal">
      <div class="app-modal" style="width: min(520px, 90vw)">
        <header><h3>导入学生名单</h3></header>
        <div class="modal-msg">
          <p>请按以下格式准备 CSV 文件：第一列<strong>姓名</strong>，第二列<strong>学号</strong>（10 位数字）。</p>
          <p><button class="secondary" @click="downloadCsvTemplate">下载 CSV 模板</button></p>
          <div style="margin-top:12px">
            <label class="upload primary" style="display:inline-flex">选择 CSV 文件<input type="file" accept=".csv" @change="onCsvFileChange" ref="csvFileInput"></label>
            <span v-if="csvFileName" style="margin-left:10px;color:var(--muted)">{{ csvFileName }}</span>
          </div>
        </div>
        <footer>
          <button class="secondary" @click="closeCsvModal">取消</button>
          <button @click="uploadCsv" :disabled="!csvFileName">上传并导入</button>
        </footer>
      </div>
    </div>

    <!-- ========== 添加学生弹窗 ========== -->
    <div v-if="studentAddOpen" class="modal-backdrop" @click.self="closeStudentAdd">
      <div class="app-modal" @keydown.enter="submitAddStudent">
        <header><h3>添加学生</h3></header>
        <div class="modal-msg">
          <div style="display:grid;gap:10px">
            <input v-model="newStudentName" placeholder="姓名" autofocus>
            <input v-model="newStudentId" placeholder="10位学号">
          </div>
        </div>
        <footer>
          <button class="secondary" @click="closeStudentAdd">取消</button>
          <button @click="submitAddStudent">确定添加</button>
        </footer>
      </div>
    </div>

    <!-- ========== 编辑学生弹窗 ========== -->
    <div v-if="editStudentOpen" class="modal-backdrop" @click.self="closeEditStudent">
      <div class="app-modal" @keydown.enter="submitEditStudent">
        <header><h3>编辑学生</h3></header>
        <div class="modal-msg">
          <div style="display:grid;gap:10px">
            <input v-model="editStudentName" placeholder="姓名" autofocus>
            <input v-model="editStudentId" placeholder="10位学号">
          </div>
        </div>
        <footer>
          <button class="secondary" @click="closeEditStudent">取消</button>
          <button @click="submitEditStudent">保存</button>
        </footer>
      </div>
    </div>

    <!-- ========== 学生详情 Modal ========== -->
    <div v-if="detailOpen" class="modal-backdrop" @click.self="closeStudentDialog">
      <section class="student-modal">
        <!-- 头部：标题 + 关闭 -->
        <header>
          <div><h2>{{ studentDetail?.name }}</h2><p>总分 {{ studentDetail?.summary?.['总成绩'] || '-' }} · 语音综合分 {{ studentDetail?.summary?.['语音综合分'] || '-' }} · 单词准确率 {{ studentDetail?.summary?.['单词准确率'] || '-' }}</p></div>
          <button class="secondary" @click="closeStudentDialog">关闭</button>
        </header>
        <!-- 按钮组 -->
        <div class="modal-actions">
          <button class="secondary" :disabled="!studentDetail?.previous_student" @click="openAdjacentStudent(studentDetail!.previous_student)">上一位</button>
          <button class="secondary" :disabled="!studentDetail?.next_student" @click="openAdjacentStudent(studentDetail!.next_student)">下一位</button>
          <button v-if="studentDetail?.report_relative_path" @click="downloadBlob(previewUrl(studentDetail.report_relative_path), studentDetail.report_relative_path.split('/').pop() || 'report.md')">下载 Markdown</button>
          <button v-if="studentDetail?.images?.length" @click="downloadBlob(previewUrl(studentDetail.images[0].relative_path), studentDetail.images[0].filename || 'chart.png')">下载音频评分图</button>
        </div>
        <div class="modal-body-new">
          <div v-if="loading.studentDetail" class="loading-overlay"><span class="spinner large"></span></div>
          <template v-else>
            <!-- 3x3 音频结果图 -->
            <div class="detail-images" v-if="studentDetail?.images?.length">
              <h3>音频评分图表</h3>
              <div class="detail-img-grid">
                <img v-for="image in studentDetail.images" :key="image.relative_path" :src="previewUrl(image.relative_path)" class="report-image zoomable-image" alt="报告图表" @click="imagePreviewUrl = previewUrl(image.relative_path)">
              </div>
            </div>
            <!-- 统计信息 -->
            <div v-if="parsedReport?.stats?.length" class="panel stats-panel">
              <h3>统计信息</h3>
              <table><tbody><tr><th v-for="item in parsedReport.stats" :key="item.label">{{ item.label }}</th></tr><tr><td v-for="item in parsedReport.stats" :key="item.label">{{ item.value }}</td></tr></tbody></table>
            </div>
            <!-- 单词准确率 · 比对结果 -->
            <h3>单词准确率 · 逐句比对</h3>
            <div class="comparison-cards" v-if="parsedReport?.comparisons?.length">
              <div class="cmp-card" v-for="item in parsedReport.comparisons" :key="item.index">
                <div class="cmp-header">条目 {{ item.index }}</div>
                <div class="cmp-row"><span class="cmp-label">标准原句</span><span class="cmp-text" v-html="item.originalHtml"></span></div>
                <div class="cmp-row"><span class="cmp-label">识别结果</span><span class="cmp-text" v-html="item.recognizedHtml"></span></div>
                <div class="cmp-row" v-if="item.details"><span class="cmp-label">差异详情</span><span class="cmp-text cmp-detail" v-html="item.detailsHtml"></span></div>
                <div class="cmp-row" v-if="item.knowledgeHtml"><span class="cmp-label">关联知识</span><span class="cmp-text" v-html="item.knowledgeHtml" style="color:#2563eb"></span></div>
              </div>
            </div>
            <div v-else class="empty-state"><p>无法解析比对结果</p></div>
            <!-- 标准文本 / 转写文本 双栏 -->
            <div class="text-compare" style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px">
              <div class="panel"><h3>标准文本</h3><div class="text-block">{{ parsedReport?.standard || '无标准文本' }}</div></div>
              <div class="panel"><h3>转写文本</h3><div class="text-block">{{ parsedReport?.transcription || '无转写文本' }}</div></div>
            </div>
          </template>
        </div>
      </section>
    </div>

    <!-- ========== 图片放大预览 ========== -->
    <div v-if="imagePreviewUrl" class="image-preview" @click="imagePreviewUrl = ''">
      <img :src="imagePreviewUrl" alt="放大图表">
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
