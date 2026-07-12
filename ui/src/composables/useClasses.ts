/**
 * useClasses.ts — 班级/单元数据管理
 * ================================
 * 班级和单元的 CRUD 操作，学生名单管理。
 */
import { ref } from 'vue';
import { apiGet, apiPost, apiPut, apiDelete } from '../api';
import type { ClassItem, UnitItem, StudentItem, StudentForm } from '../types';

export function useClasses() {
  const classId = ref('default-class');
  const unitId = ref('default-unit');
  const classes = ref<ClassItem[]>([]);
  const units = ref<UnitItem[]>([]);
  const students = ref<StudentItem[]>([]);
  const loading = ref({ classes: false, students: false });

  const currentClassName = () => classes.value.find(c => c.class_id === classId.value)?.name || classId.value;
  const currentUnitName = () => units.value.find(u => u.unit_id === unitId.value)?.name || unitId.value;

  async function loadClasses(modal: any) {
    loading.value.classes = true;
    try {
      const data = await apiGet<{ items: ClassItem[]; current?: { class_id: string; unit_id: string } }>('/api/v1/classes');
      classes.value = data.items;
      classId.value = data.current?.class_id || classId.value;
      unitId.value = data.current?.unit_id || unitId.value;
    } finally { loading.value.classes = false; }
  }

  async function loadUnits() {
    const data = await apiGet<{ items: UnitItem[] }>(`/api/v1/classes/${classId.value}/units`);
    units.value = data.items;
    if (!units.value.find(u => u.unit_id === unitId.value) && units.value[0]) unitId.value = units.value[0].unit_id;
  }

  async function loadStudents() {
    loading.value.students = true;
    try {
      const data = await apiGet<{ items: StudentItem[] }>(`/api/v1/classes/${classId.value}/students?unit_id=${unitId.value}`);
      students.value = data.items;
    } finally { loading.value.students = false; }
  }

  async function createClass(modal: any) {
    const name = await modal.showPrompt('请输入班级名称', '', '新建班级');
    if (!name) return;
    const item = await apiPost<{ class_id: string }>('/api/v1/classes', { name, description: '' });
    await loadClasses(modal);
    if (item) classId.value = item.class_id;
  }

  async function renameClass(modal: any) {
    const current = classes.value.find(c => c.class_id === classId.value);
    const name = await modal.showPrompt('新的班级名称', current?.name || classId.value, '重命名班级');
    if (!name) return;
    await apiPut(`/api/v1/classes/${classId.value}`, { name, description: current?.description || '' });
    await loadClasses(modal);
  }

  async function archiveClass(modal: any) {
    if (!await modal.showConfirm('确认归档当前班级？默认班级不能归档，归档不会物理删除数据。', '归档班级')) return;
    await apiDelete(`/api/v1/classes/${classId.value}`);
    await loadClasses(modal);
  }

  async function createUnit(modal: any) {
    const name = await modal.showPrompt('请输入单元名称', '', '新建单元');
    if (!name) return;
    const item = await apiPost<{ unit_id: string }>(`/api/v1/classes/${classId.value}/units`, { name, description: '' });
    await loadUnits();
    if (item) unitId.value = item.unit_id;
  }

  async function renameUnit(modal: any) {
    const current = units.value.find(u => u.unit_id === unitId.value);
    const name = await modal.showPrompt('新的单元名称', current?.name || unitId.value, '重命名单元');
    if (!name) return;
    await apiPut(`/api/v1/classes/${classId.value}/units/${unitId.value}`, { name, description: current?.description || '' });
    await loadUnits();
  }

  async function archiveUnit(modal: any) {
    if (!await modal.showConfirm('确认归档当前单元？默认单元不能归档。', '归档单元')) return;
    await apiDelete(`/api/v1/classes/${classId.value}/units/${unitId.value}`);
    await loadUnits();
  }

  return { classId, unitId, classes, units, students, loading, currentClassName, currentUnitName, loadClasses, loadUnits, loadStudents, createClass, renameClass, archiveClass, createUnit, renameUnit, archiveUnit };
}
