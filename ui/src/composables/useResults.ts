/**
 * useResults.ts — 结果数据管理
 * ============================
 * 成绩总览、统计、学生详情、错误聚合、导出文件列表。
 */
import { ref } from 'vue';
import { apiGet } from '../api';
import type { SummaryData, Statistics, StudentDetail, ErrorAggregate, ExportFile } from '../types';

export function useResults() {
  const summary = ref<SummaryData>({ columns: [], rows: [] });
  const stats = ref<Statistics>({ student_count: 0, average_score: null, max_score: null, min_score: null, pass_rate: null });
  const studentDetail = ref<StudentDetail | null>(null);
  const detailOpen = ref(false);
  const errors = ref<ErrorAggregate>({ replace: {}, insert: {}, delete: {} });
  const exportsState = ref<{ files: ExportFile[] }>({ files: [] });
  const loading = ref({ results: false, studentDetail: false, errors: false, exports: false });

  async function loadResults(classId: string, unitId: string) {
    loading.value.results = true;
    try {
      const query = `class_id=${encodeURIComponent(classId)}&unit_id=${encodeURIComponent(unitId)}`;
      const [summaryData, statsData] = await Promise.all([
        apiGet<SummaryData>(`/api/v1/results/summary?${query}`),
        apiGet<Statistics>(`/api/v1/results/statistics?${query}`),
      ]);
      summary.value = summaryData;
      stats.value = statsData;
    } finally { loading.value.results = false; }
  }

  async function openStudent(row: Record<string, unknown>, classId: string, unitId: string) {
    loading.value.studentDetail = true;
    try {
      const query = `class_id=${encodeURIComponent(classId)}&unit_id=${encodeURIComponent(unitId)}`;
      studentDetail.value = await apiGet<StudentDetail>(`/api/v1/results/students/${encodeURIComponent(String(row['学生']))}?${query}`);
      detailOpen.value = true;
    } finally { loading.value.studentDetail = false; }
  }

  function closeStudentDialog() { detailOpen.value = false; }

  async function loadErrors(classId: string, unitId: string) {
    loading.value.errors = true;
    try {
      const query = `class_id=${encodeURIComponent(classId)}&unit_id=${encodeURIComponent(unitId)}`;
      errors.value = await apiGet<ErrorAggregate>(`/api/v1/results/errors/aggregate?${query}`);
    } finally { loading.value.errors = false; }
  }

  async function loadExports(classId: string, unitId: string) {
    loading.value.exports = true;
    try {
      const query = `class_id=${encodeURIComponent(classId)}&unit_id=${encodeURIComponent(unitId)}`;
      exportsState.value = await apiGet<{ files: ExportFile[] }>(`/api/v1/exports/available?${query}`);
    } finally { loading.value.exports = false; }
  }

  return { summary, stats, studentDetail, detailOpen, errors, exportsState, loading, loadResults, openStudent, closeStudentDialog, loadErrors, loadExports };
}
