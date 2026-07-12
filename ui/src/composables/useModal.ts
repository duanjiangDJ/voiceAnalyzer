/**
 * useModal.ts — 统一弹窗 composable
 * ================================
 * 替代浏览器 prompt/confirm/alert，使用 AppModal 组件渲染。
 * 返回 showConfirm / showPrompt / showAlert 三个函数。
 */
import { reactive, ref } from 'vue';

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

export function useModal() {
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

  return { modal, modalInput, showConfirm, showPrompt, showAlert, modalOk, modalCancel, onModalKeydown };
}
