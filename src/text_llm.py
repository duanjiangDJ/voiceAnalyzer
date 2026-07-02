"""
text_llm.py — 基于 LLM 的语音转写文本比对模块
================================================
功能：
  1. 使用 Whisper 将音频转写为文本
  2. 调用 LLM API 对比标准文本与转写文本，找出差异
  3. 从学习资料库中查询差异单词的关联知识点
  4. 生成 Markdown 格式的结构化比对报告，并计算单词准确率

架构：
  ┌─ get_whisper_model() ──→ 全局单例 Whisper 模型（双重检查锁定）
  ├─ transcribe_only()    ──→ 音频 → 文本（Whisper）
  ├─ call_llm()          ──→ HTTP 调用 OpenAI 兼容 API
  ├─ llm_compare_texts() ──→ LLM 比对 + 本地统计 + 报告生成
  └─ _query_knowledge()  ──→ 查询关联知识点

依赖：
  - whisper (openai-whisper): 语音转写
  - src.config: AppConfig 统一配置
  - src.constants: 共享常量（音频扩展名、错误类型标记）
  - src.utils: 通用工具函数（ensure_dir, write_md_report）
  - 标准库: csv, json, os, re, threading, urllib
"""

import csv
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict

import whisper

from src.config import AppConfig
from src.constants import (
    AUDIO_EXTENSIONS_DOT,
    ERROR_TYPE_REPLACE,
    ERROR_TYPE_INSERT,
    ERROR_TYPE_DELETE,
)
from src.utils import ensure_dir, write_md_report

_config = AppConfig.load()
"""应用全局配置（统一配置入口，模块内全局只读访问）"""


# ==============================================================================
# 知识点加载 — 从 CSV 构建单词→知识点映射表，供比对报告引用
# ==============================================================================
def load_learning_source(csv_path: str | None = None) -> dict:
    """
    加载学习资料 CSV，构建知识点字典。

    CSV 格式（6 列，无标题行）：
      单词/短语, 发音, 释义, 例句, 翻译, 视频链接

    参数:
        csv_path: CSV 文件路径，为 None 时使用配置中的默认路径

    返回:
        dict: {单词(小写): [{"pronounce":..., "meaning":..., ...}, ...]}
              若文件不存在则返回空字典
    """
    if csv_path is None:
        csv_path = os.path.join(
            _config.paths.abs_path(_config.paths.knowledge_dir),
            "learning_source.csv",
        )

    if not os.path.exists(csv_path):
        print(f"[文本比对] 警告: 知识点文件 {csv_path} 不存在，将跳过关联知识点匹配。")
        return {}

    knowledge = defaultdict(list)
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            # 跳过空行和无关键词的行
            if not row or not row[0].strip():
                continue
            phrase = row[0].strip().lower()
            # 补全不足 6 列的旧格式行
            while len(row) < 6:
                row.append("")
            entry = {
                "pronounce": row[1].strip(),
                "meaning": row[2].strip(),
                "sentence": row[3].strip(),
                "translation": row[4].strip(),
                "link": row[5].strip(),
            }
            knowledge[phrase].append(entry)
    return knowledge


# 模块加载时一次性读取，全局共享（只读访问无需加锁）
LEARNING_SOURCE: dict = load_learning_source()


# ==============================================================================
# LLM API 调用层 — 与具体比对逻辑解耦，可替换为任意 OpenAI 兼容后端
# ==============================================================================
def call_llm(system_prompt: str, user_prompt: str, use_json: bool = False) -> str:
    """
    调用 OpenAI 兼容的 /chat/completions 端点。

    参数:
        system_prompt: 系统角色提示词（定义任务规则）
        user_prompt:   用户角色提示词（携带待处理数据）
        use_json:      是否启用 response_format={"type":"json_object"}

    返回:
        API 返回的 message.content 文本

    异常:
        RuntimeError: HTTP 错误、API 返回错误、或空响应内容
    """
    # ---- 构造请求 ----
    url = f"{_config.llm.api_base.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_config.llm.api_key}",
    }
    body = {
        "model": _config.llm.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 131072,
    }
    if use_json:
        body["response_format"] = {"type": "json_object"}
    if _config.llm.thinking:
        body["thinking"] = {"type": "enabled"}

    # ---- 发送请求 ----
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=_config.llm.timeout) as resp:
            raw_body = resp.read().decode("utf-8")
            result = json.loads(raw_body)
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(f"[LLM] API 返回 HTTP {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"[LLM] 无法连接 API ({url}): {e.reason}")

    # ---- 验证响应 ----
    if "error" in result:
        raise RuntimeError(f"[LLM] API 错误: {result['error']}")

    choices = result.get("choices", [])
    if not choices:
        raise RuntimeError(
            f"[LLM] API 返回空 choices，完整响应: "
            f"{json.dumps(result, ensure_ascii=False)[:500]}"
        )

    content = choices[0].get("message", {}).get("content", "")
    finish_reason = choices[0].get("finish_reason", "unknown")

    if not content:
        # 思考模式下 token 可能全被 reasoning_content 消耗 → 自动回退重试
        reasoning = choices[0].get("message", {}).get("reasoning_content", "")
        if reasoning and finish_reason == "length" and _config.llm.thinking and use_json:
            print("  [LLM] 思考模式 token 耗尽，回退到非思考模式重试 ...")
            # 移除 thinking，所有 token 用于 content
            body.pop("thinking", None)
            body["max_tokens"] = max(body.get("max_tokens", 4096), 131072)
            retry_req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"), headers=headers
            )
            with urllib.request.urlopen(retry_req, timeout=_config.llm.timeout) as resp2:
                retry_result = json.loads(resp2.read().decode("utf-8"))
            retry_content = (
                retry_result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if not retry_content:
                raise RuntimeError(
                    "[LLM] 非思考模式回退后仍为空 (finish_reason=length)，"
                    "文本过长，请缩短音频或拆分处理。"
                )
            return retry_content

        raise RuntimeError(
            f"[LLM] API 返回空内容 (finish_reason={finish_reason})，"
            f"完整响应: {json.dumps(result, ensure_ascii=False)[:500]}"
        )

    # 打印 token 消耗（每次 API 调用都记录）
    usage = result.get("usage", {})
    print(
        f"  [LLM Token] prompt={usage.get('prompt_tokens','?')} "
        f"completion={usage.get('completion_tokens','?')} "
        f"total={usage.get('total_tokens','?')}"
    )

    return content


# ==============================================================================
# JSON 提取工具 — 兼容 LLM 可能的多余输出（Markdown 包裹、控制字符等）
# ==============================================================================
def _extract_json(text: str) -> dict | None:
    """
    从 LLM 返回文本中提取 JSON 对象，按优先级尝试四种策略：
      1. 直接解析全文为 JSON
      2. 提取 ```json ... ``` 代码块
      3. 提取最外层 { ... } （贪婪匹配）
      4. 移除控制字符后重试策略 3

    参数:
        text: LLM 原始返回文本

    返回:
        解析后的 dict；若所有策略失败则返回 None
    """
    # 预处理：移除 JSON 中不允许的注释和尾部逗号
    def _sanitize_json(s: str) -> str:
        """移除 // 单行注释 和 尾部逗号（LLM 常见错误）"""
        # 移除 // 注释（仅在行级，不处理字符串内的 //）
        s = re.sub(r"//[^\n]*", "", s)
        # 移除尾部逗号（, 后紧跟 ] 或 }）
        s = re.sub(r",\s*(\]|\})", r"\1", s)
        return s

    text = _sanitize_json(text)

    # 策略 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略 2: 提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(_sanitize_json(m.group(1).strip()))
        except json.JSONDecodeError:
            pass

    # 策略 3: 贪婪提取最外层花括号
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(_sanitize_json(m.group(0)))
        except json.JSONDecodeError:
            pass

    # 策略 4: 清理控制字符后重试
    try:
        cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
        cleaned = _sanitize_json(cleaned)
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            return json.loads(m.group(0))
    except json.JSONDecodeError:
        pass

    return None


# ==============================================================================
# 关联知识点查询 — 根据单句差异匹配学习资料库
# ==============================================================================
def _query_knowledge(
    sent_standard: str, sent_transcribed: str, sent_errors: list
) -> list:
    """
    根据单句的差异词，在 LEARNING_SOURCE 中查询关联知识点。

    算法：
      1. 从 errors 中收集差异词（替换词、多读词、漏读词）
      2. 在标准句和转写句的小写词序列中检索多词短语匹配
      3. 合并单词 + 短语作为查询键，查 LEARNING_SOURCE
      4. 按单词/短语分组，格式化为 Markdown 列表

    参数:
        sent_standard:    该句标准文本（含 LLM 标注的 **粗体** 差异标记）
        sent_transcribed: 该句转写文本（同上）
        sent_errors:      该句的 errors 数组

    返回:
        Markdown 行字符串列表（空列表表示该句无匹配知识点）
    """
    if not LEARNING_SOURCE:
        return []

    # ---- 1. 收集差异词（小写去重） ----
    error_words: set[str] = set()
    for e in sent_errors:
        t = e.get("type", "")
        if t in ("replace", "delete"):
            for w in e.get("standard", "").lower().split():
                error_words.add(w)
        if t in ("replace", "insert"):
            for w in e.get("transcribed", "").lower().split():
                error_words.add(w)

    # ---- 2. 文本 → 小写单词序列（去除 ** 粗体标记） ----
    def _to_word_seq(text: str) -> list:
        """去除 Markdown 粗体标记后提取英文单词序列（小写）"""
        clean = re.sub(r"\*\*", "", text)
        return [w.lower() for w in re.findall(r"[a-zA-Z]+", clean)]

    std_seq = _to_word_seq(sent_standard)
    hyp_seq = _to_word_seq(sent_transcribed)

    # ---- 3. 在词序列中滑动匹配多词短语 ----
    phrases_to_match = [p for p in LEARNING_SOURCE if " " in p]
    matched_phrases: set[str] = set()
    for seq in (std_seq, hyp_seq):
        n = len(seq)
        for phrase in phrases_to_match:
            tokens = phrase.split()
            m = len(tokens)
            if m > n:
                continue
            for i in range(n - m + 1):
                if seq[i : i + m] == tokens:
                    matched_phrases.add(phrase)

    # ---- 4. 合并单词语短语，批量查询 ----
    all_queries = error_words | matched_phrases
    found: list[tuple[str, dict]] = []
    for query in all_queries:
        if query in LEARNING_SOURCE:
            for entry in LEARNING_SOURCE[query]:
                found.append((query, entry))

    if not found:
        return []

    # ---- 5. 格式化为 Markdown（按单词/短语分组） ----
    lines = ["- **关联知识点**："]
    phrase_groups: dict[str, list] = defaultdict(list)
    for phrase, e in found:
        phrase_groups[phrase].append(e)

    for phrase, entries in phrase_groups.items():
        for e in entries:
            parts = [f"**{phrase}**"]
            if e["pronounce"]:
                parts.append(f"发音: {e['pronounce']}")
            if e["meaning"]:
                parts.append(f"释义: {e['meaning']}")
            if e["sentence"]:
                parts.append(f"例句: {e['sentence']}")
            if e["translation"]:
                parts.append(f"翻译: {e['translation']}")
            if e["link"]:
                parts.append(f"[视频]({e['link']})")
            lines.append("  - " + "；".join(parts))
    return lines


# ==============================================================================
# LLM 文本比对 — 核心业务逻辑
# ==============================================================================
# ---- LLM 系统提示词（定义比对规则、等价规则、输出 Schema） ----
_SYSTEM_PROMPT = (
    "你是英语语音识别质量评估助手。对比标准文本和转写文本找差异。\n"
    "工作流程: 1.将转写文本与标准文本对齐，按标准文本句号分句 2.将转写文本对应切分(以标准分句为准) 3.逐句比对,不跳句 4.完成所有句子后自查\n\n"
    "【等价规则-不算差异】\n"
    "0.转写句点分句可能有误,参考标准文本正确分句\n"
    "1.缩写/口语化: gonna=going to, can't=cannot, I'm=I am等\n"
    "2.英美拼写: colour=color, theatre=theater等\n"
    "3.尊称/缩略: mr=mister, dr=doctor等\n"
    "4.同音词: their/there/they're, to/too/two等(ASR常见)\n"
    "5.数字等价: twenty five=25, first=1st等\n"
    "6.短语合并: every day=everyday, in to=into等\n"
    "7.标点/连字符: re-tile与retile等\n"
    "8.人名/地名：所有人名地名（有些文本会缩写）不算差异\n"
    "9.其他读出来等价的\n"
    "【需要报告的差异】\n"
    "1.实质替换:含义明显不同(cat→hat)\n"
    "2.多读:转写多出标准没有的词\n"
    "3.漏读:标准词在转写中缺失\n"
    "4.等价规则未定义的其他差异\n"
    "【输出格式-严格JSON,禁止注释】\n"
    '{"h":true,"T":"sentence0|||sentence1|||...","d":[{"i":0,"e":[{"r":["breeze","breath"]},{"i":["extra words"]}]}]}\n'
    "字段: h=has_diff, T=所有转写句子按顺序用|||拼接(不要加粗体**标记!)\n"
    "d=差异数组, i=标准句序号(0-based), e=该句错误数组\n"
    "e: {\"r\":[标准词,识别词]}=替换, {\"i\":[多读词]}=多读, {\"d\":[漏读词]}=漏读\n"
    "无差异则h:false,d:[]. 不要输出标准句(已省略). 不要用**粗体**. 紧凑JSON(无换行无缩进). 逐句不漏."
)


def _split_standard_sentences(text: str) -> list[str]:
    """按句号分割标准文本为句子列表。"""
    # 匹配句尾: .!? 后跟空格+大写字母或数字
    pattern = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
    sentences = []
    last = 0
    for m in pattern.finditer(text):
        sentences.append(text[last : m.start()].strip())
        last = m.end()
    if last < len(text):
        sentences.append(text[last:].strip())
    return sentences


def _bold_in_text(text: str, word: str) -> str:
    """在文本中查找 word 并用 **word** 替换（单词边界、大小写不敏感）。"""
    if not word or not text:
        return text
    pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    if pattern.search(text):
        return pattern.sub(f"**{word}**", text)
    # 回退: 不使用单词边界（短语可能有标点相邻）
    return text.replace(word, f"**{word}**")


def llm_compare_texts(
    standard_text: str, transcribed_text: str
) -> tuple[str, float, dict]:
    """
    使用 LLM 比对标准文本与转写文本，返回 Markdown 报告、准确率和按类型分类的错误列表。

    流程：
      1. 构造提示词 → 调用 LLM → 解析 JSON
      2. 本地统计：从 errors 数组按词计数，计算准确率
      3. 按错误类型分类：替换、多读、漏读
      4. 生成报告：逐句 Markdown → 关联知识点 → 统计脚注

    参数:
        standard_text:   标准文本（完整原文）
        transcribed_text: Whisper 转写文本

    返回:
        (markdown_report: str, accuracy: float, errors_by_category: dict)
        - markdown_report: 格式化的差异报告（含统计脚注）
        - accuracy: 单词准确率 [0.0, 1.0]
        - errors_by_category: {ERROR_TYPE_REPLACE: [...], ERROR_TYPE_INSERT: [...], ERROR_TYPE_DELETE: [...]}
    """
    # ---- 1. 调用 LLM 获取结构化差异 ----
    user_prompt = (
        f"标准:\n{standard_text}\n\n"
        f"转写:\n{transcribed_text}\n\n"
        "对比后返回JSON。"
    )
    time_start = time.time()
    raw_response = call_llm(_SYSTEM_PROMPT, user_prompt, use_json=True)
    time_elapsed = time.time() - time_start

    data = _extract_json(raw_response)
    if data is None:
        raise RuntimeError(
            f"无法解析 LLM 返回的 JSON。\n"
            f"--- 原始返回前 800 字符 ---\n{raw_response[:800]}\n"
            f"--- 原始返回末 200 字符 ---\n{raw_response[-200:]}\n"
            f"------------------------"
        )

    # ---- 2. 本地统计 + 标准文本分句 ----
    standard_words = re.findall(r"[a-zA-Z]+", standard_text)
    standard_word_count = len(standard_words)

    # 解析紧凑格式: {"h":bool,"d":[{...}]} 回退旧格式: {"has_diff":...,"sentences":[...]}
    has_diff = data.get("h", data.get("has_diff", True))
    diffs = data.get("d", data.get("sentences", []))
    if not isinstance(diffs, list):
        diffs = []

    # 标准文本分句（用于本地重建标准句）
    std_sentences = _split_standard_sentences(standard_text)

    all_errors: list = []
    replace_count = 0
    insert_count = 0
    delete_count = 0
    error_word_count = 0

    errors_by_category: dict[str, list[dict]] = {
        ERROR_TYPE_REPLACE: [],
        ERROR_TYPE_INSERT: [],
        ERROR_TYPE_DELETE: [],
    }

    # 安全取字符串值（LLM 可能返回 str / [str] / [[str]] 等嵌套形式）
    def _s(v):
        """递归解包直到得到字符串。"""
        if isinstance(v, str):
            return v
        if isinstance(v, list) and len(v) > 0:
            return _s(v[0])
        return str(v)

    for entry in diffs:
        sent_errors = entry.get("e", entry.get("errors", []))
        for e in sent_errors:
            all_errors.append(e)
            if "r" in e:
                n = len(_s(e["r"]).split())
                replace_count += 1
                error_word_count += n
                std_word = _s(e["r"])
                trans_word = (
                    _s(e["r"][1:])
                    if isinstance(e["r"], list) and len(e["r"]) > 1
                    else _s(e["r"])
                )
                errors_by_category[ERROR_TYPE_REPLACE].append({
                    "standard": std_word,
                    "transcribed": trans_word,
                })
            elif "i" in e:
                n = len(_s(e["i"]).split())
                insert_count += 1
                error_word_count += n
                errors_by_category[ERROR_TYPE_INSERT].append({
                    "word": _s(e["i"]),
                })
            elif "d" in e:
                n = len(_s(e["d"]).split())
                delete_count += 1
                error_word_count += n
                errors_by_category[ERROR_TYPE_DELETE].append({
                    "word": _s(e["d"]),
                })
            elif e.get("type") == "replace":
                n = len(e.get("standard", "").split())
                replace_count += 1
                error_word_count += n
                errors_by_category[ERROR_TYPE_REPLACE].append({
                    "standard": e.get("standard", ""),
                    "transcribed": e.get("transcribed", ""),
                })
            elif e.get("type") == "insert":
                n = len(e.get("transcribed", "").split())
                insert_count += 1
                error_word_count += n
                errors_by_category[ERROR_TYPE_INSERT].append({
                    "word": e.get("transcribed", ""),
                })
            elif e.get("type") == "delete":
                n = len(e.get("standard", "").split())
                delete_count += 1
                error_word_count += n
                errors_by_category[ERROR_TYPE_DELETE].append({
                    "word": e.get("standard", ""),
                })

    accuracy = (
        (standard_word_count - error_word_count) / standard_word_count
        if standard_word_count > 0
        else 1.0
    )
    accuracy = max(0.0, min(1.0, accuracy))

    # ---- 3. 本地生成 Markdown 报告 ----
    # 解析 T 块（所有转写句用 ||| 拼接）或回退旧格式 per-sentence t 字段
    T_block = data.get("T", "")
    T_parts = T_block.split("|||") if T_block else []

    if not has_diff or not diffs:
        report = "（无内容差异）"
    else:
        lines: list[str] = []
        for idx, entry in enumerate(diffs, 1):
            sent_errors = entry.get("e", entry.get("errors", []))
            sent_idx = entry.get("i", idx - 1)

            # 取转写句: T 块按索引取 / 旧格式 t 字段
            if T_parts and sent_idx < len(T_parts):
                hyp_sent = T_parts[sent_idx]
            else:
                hyp_sent = entry.get("t", entry.get("transcribed", ""))

            # 对转写句本地加粗: 按 error 中的 t_word 加粗
            for e in sent_errors:
                if "r" in e:
                    hyp_sent = _bold_in_text(hyp_sent, _s(e["r"][1:]) or _s(e["r"]))
                elif "i" in e:
                    hyp_sent = _bold_in_text(hyp_sent, _s(e["i"]))
                elif e.get("type") == "replace":
                    hyp_sent = _bold_in_text(hyp_sent, e.get("transcribed", ""))
                elif e.get("type") == "insert":
                    hyp_sent = _bold_in_text(hyp_sent, e.get("transcribed", ""))

            # 本地重建标准句: 按索引取标准句 → 加粗错误词
            if sent_idx < len(std_sentences):
                std_sent = std_sentences[sent_idx]
            else:
                std_sent = entry.get("standard", "")

            for e in sent_errors:
                if "r" in e:
                    std_sent = _bold_in_text(std_sent, _s(e["r"]))
                elif "d" in e:
                    std_sent = _bold_in_text(std_sent, _s(e["d"]))
                elif e.get("type") == "replace":
                    std_sent = _bold_in_text(std_sent, e.get("standard", ""))
                elif e.get("type") == "delete":
                    std_sent = _bold_in_text(std_sent, e.get("standard", ""))

            # 条目 Markdown
            lines.append(f"### 条目 {idx}")
            lines.append(f"- **标准原句**：{std_sent}")
            lines.append(f"- **识别结果**：{hyp_sent}")
            lines.append("- **差异详情**：")

            for e in sent_errors:
                if "r" in e:
                    r_std = _s(e["r"])
                    r_hyp = (
                        _s(e["r"][1:])
                        if isinstance(e["r"], list) and len(e["r"]) > 1
                        else _s(e["r"])
                    )
                    lines.append(f'  - 错误之处："**{r_hyp}**" 应为 "**{r_std}**"')
                elif "i" in e:
                    lines.append(f'  - 多读部分："**{_s(e["i"])}**"')
                elif "d" in e:
                    lines.append(f'  - 漏读部分："**{_s(e["d"])}**"')
                elif e.get("type") == "replace":
                    lines.append(
                        f'  - 错误之处："**{e.get("transcribed","?")}**" 应为 "**{e.get("standard","?")}**"'
                    )
                elif e.get("type") == "insert":
                    lines.append(f'  - 多读部分："**{e.get("transcribed","?")}**"')
                elif e.get("type") == "delete":
                    lines.append(f'  - 漏读部分："**{e.get("standard","?")}**"')

            knowledge_lines = _query_knowledge(std_sent, hyp_sent, sent_errors)
            if knowledge_lines:
                lines.extend(knowledge_lines)
            lines.append("")

        report = "\n".join(lines)

    # ---- 4. 追加统计脚注 ----
    stats = (
        f"\n---\n"
        f"**统计信息**：标准文本 {standard_word_count} 词 | "
        f"替换 {replace_count} | 多读 {insert_count} | 漏读 {delete_count} | "
        f"错误共 {error_word_count} 词 | 准确率 {accuracy * 100:.2f}%"
    )
    report = report.rstrip() + stats

    print(
        f"  [LLM] 返回 {len(all_errors)} 个差异条目 / "
        f"{error_word_count} 个错误单词"
        f"（替换:{replace_count} 多读:{insert_count} 漏读:{delete_count}，"
        f"API 耗时 {time_elapsed:.1f}s）"
    )

    return report, accuracy, errors_by_category


# ==============================================================================
# Whisper 语音转写层 — 全局单例模型，双重检查锁定，仅加载一次
# ==============================================================================
_whisper_model = None
"""全局唯一的 Whisper 模型实例"""

_whisper_model_lock = threading.Lock()
"""Whisper 模型初始化的互斥锁（双重检查锁定）"""


def get_whisper_model(model_name: str = "medium.en"):
    """
    获取全局单例 Whisper 模型。

    实现方式：双重检查锁定（Double-Checked Locking）
    - 第一次检查（无锁）：快速路径，已加载则直接返回
    - 加锁 + 第二次检查：防止多线程同时初始化

    参数:
        model_name: Whisper 模型名称（tiny/small/medium/large）

    返回:
        whisper.Model 实例
    """
    global _whisper_model
    if _whisper_model is None:
        with _whisper_model_lock:
            if _whisper_model is None:
                print(f"[Whisper] 正在加载模型: {model_name} ...")
                _whisper_model = whisper.load_model(model_name)
                print("[Whisper] 模型加载完成（全局单例）。")
    return _whisper_model


def transcribe_only(audio_path: str, model_name: str = "small.en") -> str:
    """
    仅转写音频（不比对），返回纯文本。

    与 llm_compare_texts 解耦，供调度器在 whisper_executor 中独立调用。

    参数:
        audio_path: 音频文件路径
        model_name: Whisper 模型名称

    返回:
        转写后的文本字符串
    """
    model = get_whisper_model(model_name)
    return model.transcribe(audio_path)["text"].strip()


# ==============================================================================
# 文件 I/O — 与比对逻辑解耦的读写操作
# ==============================================================================
def read_standard_text(txt_path: str) -> str:
    """
    读取标准文本文件（UTF-8 编码）。

    参数:
        txt_path: 文本文件路径

    返回:
        去除首尾空白的文本内容
    """
    with open(txt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


# ==============================================================================
# 直接运行入口 — 批量处理 source_audio/ 目录下的所有音频
# ==============================================================================
def main():
    """独立批量处理接口（resource/source_audio/ → resource/result/）"""
    audio_folder = "resource/source_audio"
    text_folder = "resource/source_text"
    result_folder = "resource/result"
    ensure_dir(result_folder)

    if not _config.llm.api_key or _config.llm.api_key == "sk-your-api-key-here":
        print("WARNING: 请在 .env 文件中设置有效的 LLM_API_KEY")
        return

    model = get_whisper_model("medium.en")

    for audio_file in os.listdir(audio_folder):
        if not audio_file.lower().endswith(AUDIO_EXTENSIONS_DOT):
            continue

        base_name = os.path.splitext(audio_file)[0]
        audio_path = os.path.join(audio_folder, audio_file)
        text_path = os.path.join(text_folder, base_name + ".txt")
        res_path = os.path.join(result_folder, base_name + ".md")

        if not os.path.exists(text_path):
            print(f"跳过（无对应文本）: {audio_file}")
            continue

        print(f"处理中: {audio_file}")
        try:
            transcribed_text = model.transcribe(audio_path)["text"].strip()
            standard_text_val = read_standard_text(text_path)
            print(f"  正在调用 LLM ({_config.llm.model}) 进行文本比对 ...")
            report, accuracy, _ = llm_compare_texts(standard_text_val, transcribed_text)
            write_md_report(
                res_path, transcribed_text, standard_text_val,
                report, _config.llm.model,
            )
            print(f"  成功保存: {res_path}（准确率: {accuracy * 100:.2f}%）")
        except Exception as e:
            print(f"  处理失败 {audio_file}: {e}")


if __name__ == "__main__":
    main()
