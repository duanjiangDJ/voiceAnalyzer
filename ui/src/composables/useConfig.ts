/**
 * useConfig.ts — 配置中心 composable
 * ================================
 * 全局配置的读取、保存和 API Key 显示/隐藏。
 */
import { ref } from 'vue';
import { apiGet, apiPut } from '../api';
import type { AppConfig } from '../types';

export function useConfig(modal: any) {
  const config = ref<AppConfig | null>(null);
  const actualApiKey = ref('');
  const apiKeyVisible = ref(false);
  const loading = ref({ config: false, saveConfig: false });

  async function loadConfig() {
    loading.value.config = true;
    try {
      const data = await apiGet<AppConfig & { __actual_api_key?: string }>('/api/v1/config');
      config.value = data;
      actualApiKey.value = (data as Record<string, unknown>).__actual_api_key as string || '';
    } finally { loading.value.config = false; }
  }

  async function saveConfig() {
    loading.value.saveConfig = true;
    try {
      const data = await apiPut<{ saved?: boolean; config?: AppConfig }>('/api/v1/config', { config: config.value });
      if (data.config) config.value = data.config;
    } finally { loading.value.saveConfig = false; }
  }

  async function revealApiKey() {
    if (apiKeyVisible.value) { apiKeyVisible.value = false; return; }
    const ok = await modal.showConfirm('API Key 是敏感信息。确认后将在当前页面短时显示，请避免截屏或共享屏幕。', '显示 API Key');
    if (!ok) return;
    apiKeyVisible.value = true;
    window.setTimeout(() => { apiKeyVisible.value = false; }, 15000);
  }

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

  return { config, actualApiKey, apiKeyVisible, loading, loadConfig, saveConfig, revealApiKey, configDescriptions };
}
