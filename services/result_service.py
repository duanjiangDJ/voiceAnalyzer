"""
result_service.py — 结果查询服务
===============================
按班级/单元读取 summary.csv、progress.json、学生 Markdown 报告、错误 JSON 和导出文件。

依赖:
    - csv, json, statistics, pathlib（标准库）
    - services.app_context（项目内部模块）
"""

import csv
import json
import statistics
from pathlib import Path

from services.app_context import get_app_context
from services.class_service import ClassService, DEFAULT_CLASS_ID, DEFAULT_UNIT_ID


class ResultService:
    """结果查询服务。"""

    def __init__(self) -> None:
        self.context = get_app_context()
        self.class_service = ClassService()

    def get_summary(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """读取成绩总表。"""
        path = self._result_dir(class_id, unit_id) / "summary.csv"
        if not path.exists():
            return {"columns": [], "rows": []}
        with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            rows = [dict(row) for row in reader]
            return {"columns": reader.fieldnames or [], "rows": rows}

    def get_statistics(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """计算班级统计。"""
        rows = self.get_summary(class_id, unit_id)["rows"]
        scores = [self._to_float(row.get("总成绩")) for row in rows]
        scores = [score for score in scores if score is not None]
        return {
            "student_count": len(rows),
            "average_score": round(statistics.mean(scores), 2) if scores else None,
            "max_score": max(scores) if scores else None,
            "min_score": min(scores) if scores else None,
            "pass_rate": round(len([score for score in scores if score >= 60]) / len(scores) * 100, 2) if scores else None,
        }

    def get_student_detail(self, student_id: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """获取学生详情、报告和错误。"""
        student_dir = self._find_student_dir(student_id, class_id, unit_id)
        if not student_dir:
            return {"found": False}
        report_path = next(student_dir.glob("*.md"), None)
        errors_path = next(student_dir.glob("*_errors.json"), None)
        result_dir = self._result_dir(class_id, unit_id)
        summary_rows = self.get_summary(class_id, unit_id)["rows"]
        student_keys = [row.get("学生", "") for row in summary_rows]
        current_key = next((key for key in student_keys if student_id in key), student_dir.name)
        current_index = student_keys.index(current_key) if current_key in student_keys else -1
        return {
            "found": True,
            "student_id": student_id,
            "name": student_dir.name,
            "summary": next((row for row in summary_rows if row.get("学生") == current_key), {}),
            "previous_student": student_keys[current_index - 1] if current_index > 0 else None,
            "next_student": student_keys[current_index + 1] if 0 <= current_index < len(student_keys) - 1 else None,
            "report": report_path.read_text(encoding="utf-8") if report_path else "",
            "report_relative_path": str(report_path.relative_to(result_dir)) if report_path else "",
            "errors": self._read_json(errors_path) if errors_path else {},
            "images": [
                {"filename": path.name, "relative_path": str(path.relative_to(result_dir))}
                for path in student_dir.glob("*.png")
            ],
        }

    def get_error_aggregate(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """聚合所有学生错误 JSON。"""
        aggregate: dict[str, dict[str, int]] = {"replace": {}, "insert": {}, "delete": {}}
        for path in self._result_dir(class_id, unit_id).glob("*/*_errors.json"):
            data = self._read_json(path)
            for error_type in aggregate:
                items = data.get(error_type, []) if isinstance(data, dict) else []
                for item in items:
                    word = str(item.get("expected") or item.get("actual") or item.get("word") or "").strip().lower()
                    if word:
                        aggregate[error_type][word] = aggregate[error_type].get(word, 0) + 1
        return aggregate

    def get_available_exports(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """获取当前可用导出文件。"""
        files = []
        result_dir = self._result_dir(class_id, unit_id)
        for pattern in ("*.xlsx", "*.csv", "*.png"):
            files.extend(result_dir.glob(pattern))
        error_summary = result_dir / "error_analysis" / "error_summary.csv"
        if error_summary.exists():
            files.append(error_summary)
        for path in (result_dir / "error_analysis").glob("wordcloud_*.png") if (result_dir / "error_analysis").exists() else []:
            files.append(path)
        return {
            "class_id": class_id,
            "unit_id": unit_id,
            "files": [
                {"filename": path.name, "relative_path": str(path.relative_to(result_dir)), "size": path.stat().st_size}
                for path in sorted(set(files))
            ],
        }

    def get_progress(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """读取 progress.json 并返回各阶段进度计数。"""
        result_dir = self._result_dir(class_id, unit_id)
        progress_path = result_dir / "progress.json"
        if not progress_path.exists():
            return {"total": 0, "voice_done": 0, "text_done": 0, "students": {}}
        data = self._read_json(progress_path)
        students = data.get("students", {})
        total = len(students)
        voice_done = sum(1 for s in students.values() if isinstance(s, dict) and s.get("voice") == "done")
        text_done = sum(1 for s in students.values() if isinstance(s, dict) and s.get("text") == "done")
        return {"total": total, "voice_done": voice_done, "text_done": text_done, "students": students}

    def resolve_export_path(self, relative_path: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> Path | None:
        """解析导出文件路径，确保不越过单元结果目录。"""
        result_dir = self._result_dir(class_id, unit_id).resolve()
        target = (result_dir / relative_path).resolve()
        if not str(target).startswith(str(result_dir)) or not target.exists() or not target.is_file():
            return None
        return target

    def _result_dir(self, class_id: str, unit_id: str) -> Path:
        """获取班级/单元结果目录。"""
        return self.class_service.unit_paths(class_id, unit_id)["result_dir"]

    def _find_student_dir(self, student_id: str, class_id: str, unit_id: str) -> Path | None:
        """按学号或目录名查找学生结果目录。"""
        result_dir = self._result_dir(class_id, unit_id)
        if not result_dir.exists():
            return None
        for path in result_dir.iterdir():
            if path.is_dir() and student_id in path.name:
                return path
        return None

    def _read_json(self, path: Path | None) -> dict:
        """安全读取 JSON 文件。"""
        if not path or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _to_float(self, value: str | None) -> float | None:
        """将百分比或数字字符串转为 float。"""
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace("%", ""))
        except ValueError:
            return None