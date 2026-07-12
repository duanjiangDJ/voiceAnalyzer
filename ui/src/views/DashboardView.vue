<script setup lang="ts">
import * as echarts from 'echarts';
import { nextTick, onMounted, onUnmounted, watch } from 'vue';
import type { FileStatus, StandardText, Statistics, SummaryData } from '../types';

const props = defineProps<{
  fileStatus: FileStatus;
  standardText: StandardText;
  stats: Statistics;
  summary: SummaryData;
  loadingResults: boolean;
}>();

let chartInstance: echarts.ECharts | null = null;

function drawScoreChart() {
  nextTick(() => {
    const el = document.getElementById('scoreChart');
    if (!el || !props.summary.rows?.length) return;
    const existing = echarts.getInstanceByDom(el);
    const chart = existing || echarts.init(el);
    if (!existing) chartInstance = chart;
    chart.setOption({
      tooltip: {},
      grid: { left: 36, right: 18, top: 24, bottom: 58 },
      xAxis: { type: 'category', data: props.summary.rows.map((row: any) => row['学生']), axisLabel: { rotate: 28 } },
      yAxis: { type: 'value', min: 0, max: 100 },
      series: [{ type: 'bar', data: props.summary.rows.map((row: any) => Number(row['总成绩'] || 0)), itemStyle: { color: '#2563eb', borderRadius: [4, 4, 0, 0] } }],
    });
  });
}

watch(() => props.summary.rows?.length, drawScoreChart);
onMounted(drawScoreChart);
onUnmounted(() => chartInstance?.dispose());
</script>

<template>
  <div class="view stack fade-in">
    <div class="dash-row">
      <div class="dash-cards">
        <div class="dash-card"><div class="dash-card-icon" :class="fileStatus.standard_audio_ready?'okay':'warn'">{{ fileStatus.standard_audio_ready ? '✓' : '!' }}</div><div class="dash-card-body"><span>标准音频</span><strong>{{ fileStatus.standard_audio_ready ? '已就绪' : '缺失' }}</strong></div></div>
        <div class="dash-card"><div class="dash-card-icon okay">{{ standardText.word_count > 0 ? '✓' : '!' }}</div><div class="dash-card-body"><span>标准文本</span><strong>{{ standardText.word_count || 0 }} 词</strong><small>{{ standardText.sentence_count || 0 }} 句</small></div></div>
        <div class="dash-card"><div class="dash-card-icon accent">{{ fileStatus.student_audio_count || 0 }}</div><div class="dash-card-body"><span>已提交录音</span><strong>{{ fileStatus.student_audio_count || 0 }} 人</strong></div></div>
        <div class="dash-card"><div class="dash-card-icon score">{{ stats.average_score ? (stats.average_score>=70?'↑':'↓') : '—' }}</div><div class="dash-card-body"><span>班级均分</span><strong>{{ stats.average_score ?? '—' }}</strong><small>共 {{ stats.student_count || 0 }} 人</small></div></div>
      </div>
      <div class="panel dash-chart"><h2>成绩分布</h2>
        <div v-if="loadingResults" class="loading-overlay"><span class="spinner large"></span></div>
        <div v-else-if="!summary.rows?.length" class="empty-state"><p>暂无成绩数据</p><small>启动评估任务后此处将显示成绩分布图。</small></div>
        <div v-else id="scoreChart" class="chart"></div>
      </div>
    </div>
  </div>
</template>
