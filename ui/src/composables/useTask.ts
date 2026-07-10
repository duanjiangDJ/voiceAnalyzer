/**
 * useTask.ts — 任务状态与 SSE 订阅 composable
 * ==========================================
 * 管理评估任务的全生命周期：启动、进度、日志、取消、SSE 连接。
 */
import { ref, computed } from 'vue';
import { apiGet, apiPost } from '../api';
import type { TaskInfo } from '../types';

let eventSource: EventSource | null = null;
let _consoleUserScrolled = false;
let _scrollRaf = 0;

export function useTask() {
  const task = ref<TaskInfo>({ status: 'idle', logs: [], events: [] } as unknown as TaskInfo);
  const loading = ref({ startTask: false });
  const consoleEl = ref<HTMLElement | null>(null);

  const stageEvents = computed(() => (task.value.events || []).filter((item: any) => item.type === 'stage_progress').slice(-12));
  const latestStudentEvents = computed(() => (task.value.events || []).filter((item: any) => item.type === 'student_progress').slice(-8));

  async function loadTask() {
    try { task.value = await apiGet<TaskInfo>('/api/v1/tasks/current'); } catch { /* silent */ }
  }

  async function startTask(classId: string, unitId: string) {
    loading.value.startTask = true;
    try {
      const data = await apiPost<{ task_id: string } & TaskInfo>('/api/v1/tasks', { class_id: classId, unit_id: unitId });
      task.value = data;
      subscribeTask(data.task_id);
    } finally { loading.value.startTask = false; }
  }

  async function cancelTask() {
    if (!task.value.task_id) return;
    await apiPost(`/api/v1/tasks/${task.value.task_id}/cancel`);
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
      }
    });
    eventSource.onerror = () => { /* will auto-reconnect */ };
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

  return { task, loading, consoleEl, stageEvents, latestStudentEvents, loadTask, startTask, cancelTask, _onConsoleScroll, _stageLabel };
}
