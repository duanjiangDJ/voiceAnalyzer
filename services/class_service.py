"""
class_service.py — 班级与单元数据服务
===================================
管理 resource/classes 下的班级、单元、学生名单，并提供旧扁平数据的默认迁移映射。

依赖:
    - csv, json, re, shutil, pathlib（标准库）
    - services.app_context, services.log_service（项目内部模块）
"""

import csv
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from services.app_context import get_app_context
from services.log_service import get_log_service


DEFAULT_CLASS_ID = "default-class"
DEFAULT_UNIT_ID = "default-unit"
DEFAULT_CLASS_NAME = "默认班级"
DEFAULT_UNIT_NAME = "默认单元"

_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4"}
_STUDENT_RE = re.compile(r"^(.+)-(\d{10})$")


class ClassService:
    """班级与单元数据服务。"""

    def __init__(self) -> None:
        self.context = get_app_context()
        self.log_service = get_log_service()

    def ensure_default_workspace(self) -> dict:
        """
        确保默认班级和默认单元存在，并非破坏性复制旧数据。

        返回:
            当前默认班级和单元信息。
        """
        class_dir = self.get_class_dir(DEFAULT_CLASS_ID)
        unit_dir = self.get_unit_dir(DEFAULT_CLASS_ID, DEFAULT_UNIT_ID)
        class_dir.mkdir(parents=True, exist_ok=True)
        unit_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_if_missing(class_dir / "class.json", {
            "class_id": DEFAULT_CLASS_ID,
            "name": DEFAULT_CLASS_NAME,
            "description": "由旧 resource 扁平数据自动建立的默认班级",
        })
        self._write_json_if_missing(unit_dir / "unit.json", {
            "unit_id": DEFAULT_UNIT_ID,
            "name": DEFAULT_UNIT_NAME,
            "description": "由旧 resource 扁平数据自动建立的默认单元",
        })
        for child in ("standard_audio", "standard_text", "imitation_audio", "result"):
            (unit_dir / child).mkdir(parents=True, exist_ok=True)

        self._copy_legacy_files(self.context.standard_audio_dir, unit_dir / "standard_audio")
        self._copy_legacy_files(self.context.standard_text_dir, unit_dir / "standard_text")
        self._copy_legacy_files(self.context.imitation_audio_dir, unit_dir / "imitation_audio")
        self._copy_legacy_result_files(self.context.result_dir, unit_dir / "result")
        self._ensure_students_csv(class_dir / "students.csv", unit_dir / "imitation_audio")
        return {"class_id": DEFAULT_CLASS_ID, "unit_id": DEFAULT_UNIT_ID}

    def list_classes(self) -> dict:
        """列出所有班级。"""
        self.ensure_default_workspace()
        items = []
        for class_dir in sorted(self.context.classes_dir.iterdir()):
            if not class_dir.is_dir() or class_dir.name.startswith(".") or class_dir.name.startswith("__"):
                continue
            meta = self._read_json(class_dir / "class.json", {})
            units = self.list_units(class_dir.name)["items"]
            items.append({
                "class_id": class_dir.name,
                "name": meta.get("name", class_dir.name),
                "description": meta.get("description", ""),
                "unit_count": len(units),
                "student_count": len(self.list_students(class_dir.name)["items"]),
            })
        return {"items": items, "current": {"class_id": DEFAULT_CLASS_ID, "unit_id": DEFAULT_UNIT_ID}}

    def create_class(self, name: str, description: str = "") -> dict:
        """创建班级。"""
        class_id = self._slugify(name)
        class_dir = self.get_class_dir(class_id)
        class_dir.mkdir(parents=True, exist_ok=True)
        (class_dir / "units").mkdir(parents=True, exist_ok=True)
        self._write_json(class_dir / "class.json", {"class_id": class_id, "name": name, "description": description})
        self._ensure_students_csv(class_dir / "students.csv", class_dir / "__empty__")
        self.log_service.append("api", "INFO", f"创建班级: {name}", {"class_id": class_id})
        return {"class_id": class_id, "name": name, "description": description}

    def update_class(self, class_id: str, name: str, description: str = "") -> dict:
        """更新班级显示信息。"""
        class_dir = self.get_class_dir(class_id)
        if not class_dir.exists():
            return {"updated": False, "reason": "班级不存在"}
        data = {"class_id": self._safe_id(class_id), "name": name, "description": description}
        self._write_json(class_dir / "class.json", data)
        self.log_service.append("api", "INFO", f"更新班级: {name}", {"class_id": class_id})
        return {"updated": True, **data}

    def archive_class(self, class_id: str) -> dict:
        """归档班级目录，默认班级不允许归档。"""
        safe_id = self._safe_id(class_id)
        if safe_id == DEFAULT_CLASS_ID:
            return {"archived": False, "reason": "默认班级不能归档"}
        class_dir = self.get_class_dir(safe_id)
        if not class_dir.exists():
            return {"archived": False, "reason": "班级不存在"}
        trash_dir = self.context.classes_dir / "__archived__"
        trash_dir.mkdir(parents=True, exist_ok=True)
        target = trash_dir / f"{safe_id}_{self._timestamp()}"
        shutil.move(str(class_dir), str(target))
        self.log_service.append("api", "WARNING", "归档班级", {"class_id": safe_id, "target": str(target)})
        self._add_archive_record("class", class_name=safe_id, class_id=safe_id, original_path=str(class_dir), archived_path=str(target))
        return {"archived": True, "target": str(target)}

    def list_units(self, class_id: str) -> dict:
        """列出班级下所有单元。"""
        units_dir = self.get_class_dir(class_id) / "units"
        if not units_dir.exists():
            return {"items": []}
        items = []
        for unit_dir in sorted(units_dir.iterdir()):
            if not unit_dir.is_dir() or unit_dir.name.startswith(".") or unit_dir.name.startswith("__"):
                continue
            meta = self._read_json(unit_dir / "unit.json", {})
            status = self.get_unit_status(class_id, unit_dir.name)
            items.append({
                "unit_id": unit_dir.name,
                "name": meta.get("name", unit_dir.name),
                "description": meta.get("description", ""),
                "status": status,
            })
        return {"items": items}

    def create_unit(self, class_id: str, name: str, description: str = "") -> dict:
        """创建单元。"""
        unit_id = self._slugify(name)
        unit_dir = self.get_unit_dir(class_id, unit_id)
        for child in ("standard_audio", "standard_text", "imitation_audio", "result"):
            (unit_dir / child).mkdir(parents=True, exist_ok=True)
        self._write_json(unit_dir / "unit.json", {"unit_id": unit_id, "name": name, "description": description})
        self.log_service.append("api", "INFO", f"创建单元: {name}", {"class_id": class_id, "unit_id": unit_id})
        return {"class_id": class_id, "unit_id": unit_id, "name": name, "description": description}

    def update_unit(self, class_id: str, unit_id: str, name: str, description: str = "") -> dict:
        """更新单元显示信息。"""
        unit_dir = self.get_unit_dir(class_id, unit_id)
        if not unit_dir.exists():
            return {"updated": False, "reason": "单元不存在"}
        data = {"unit_id": self._safe_id(unit_id), "name": name, "description": description}
        self._write_json(unit_dir / "unit.json", data)
        self.log_service.append("api", "INFO", f"更新单元: {name}", {"class_id": class_id, "unit_id": unit_id})
        return {"updated": True, "class_id": class_id, **data}

    def archive_unit(self, class_id: str, unit_id: str) -> dict:
        """归档单元目录，默认单元不允许归档。"""
        safe_class = self._safe_id(class_id)
        safe_unit = self._safe_id(unit_id)
        if safe_class == DEFAULT_CLASS_ID and safe_unit == DEFAULT_UNIT_ID:
            return {"archived": False, "reason": "默认单元不能归档"}
        unit_dir = self.get_unit_dir(class_id, safe_unit)
        if not unit_dir.exists():
            return {"archived": False, "reason": "单元不存在"}
        trash_dir = self.get_class_dir(class_id) / "units" / "__archived__"
        trash_dir.mkdir(parents=True, exist_ok=True)
        target = trash_dir / f"{safe_unit}_{self._timestamp()}"
        shutil.move(str(unit_dir), str(target))
        self.log_service.append("api", "WARNING", "归档单元", {"class_id": class_id, "unit_id": safe_unit, "target": str(target)})
        self._add_archive_record("unit", class_name=safe_unit, class_id=safe_class, unit_id=safe_unit, original_path=str(unit_dir), archived_path=str(target))
        return {"archived": True, "target": str(target)}

    def list_students(self, class_id: str, unit_id: str | None = None) -> dict:
        """列出班级学生，并可叠加指定单元提交状态。"""
        students_path = self.get_class_dir(class_id) / "students.csv"
        students = self._read_students(students_path)
        audio_map = {}
        if unit_id:
            audio_dir = self.get_unit_dir(class_id, unit_id) / "imitation_audio"
            audio_map = {self._student_key_from_audio(path): path for path in audio_dir.glob("*") if path.suffix.lower() in _AUDIO_EXTENSIONS}
        items = []
        for student in students:
            key = f"{student['name']}-{student['student_id']}"
            audio_path = audio_map.get(key)
            item = dict(student)
            item["student_key"] = key
            item["submit_status"] = "submitted" if audio_path else "missing"
            item["audio_file"] = audio_path.name if audio_path else ""
            items.append(item)
        return {"items": items}

    def upsert_student(self, class_id: str, student: dict[str, str]) -> dict:
        """新增或更新学生名单记录。"""
        name = str(student.get("name", "")).strip()
        student_id = str(student.get("student_id", "")).strip()
        if not name or not re.fullmatch(r"\d{10}", student_id):
            return {"saved": False, "reason": "姓名不能为空且学号必须为 10 位数字"}
        students_path = self.get_class_dir(class_id) / "students.csv"
        rows = self._read_students(students_path)
        updated = False
        clean_row = {
            "name": name,
            "student_id": student_id,
            "status": str(student.get("status", "active") or "active"),
            "note": str(student.get("note", "") or ""),
        }
        for index, row in enumerate(rows):
            if row.get("student_id") == student_id:
                rows[index] = clean_row
                updated = True
                break
        if not updated:
            rows.append(clean_row)
        self._write_students(students_path, rows)
        self.log_service.append("api", "INFO", "保存学生", {"class_id": class_id, "student_id": student_id})
        return {"saved": True, "updated": updated, "student": clean_row}

    def delete_student(self, class_id: str, student_id: str) -> dict:
        """从班级名单中移除学生（归档），不删除已上传音频和历史结果。"""
        students_path = self.get_class_dir(class_id) / "students.csv"
        rows = self._read_students(students_path)
        kept = [row for row in rows if row.get("student_id") != student_id]
        if len(kept) == len(rows):
            return {"deleted": False, "reason": "学生不存在"}
        removed = [row for row in rows if row.get("student_id") == student_id]
        self._write_students(students_path, kept)
        student_name = removed[0].get("name", student_id) if removed else student_id
        self.log_service.append("api", "WARNING", "归档学生名单记录", {"class_id": class_id, "student_id": student_id})
        self._add_archive_record("student", class_name=student_name, class_id=class_id, student_id=student_id)
        return {"deleted": True}

    # ---------- 物理删除 ----------

    def permanently_delete_class(self, class_id: str) -> dict:
        """物理删除班级目录及所有单元的所有数据。"""
        safe_id = self._safe_id(class_id)
        if safe_id == DEFAULT_CLASS_ID:
            return {"deleted": False, "reason": "默认班级不能删除"}
        class_dir = self.get_class_dir(safe_id)
        if not class_dir.exists():
            return {"deleted": False, "reason": "班级不存在"}
        # 先清理可能存在于归档记录中的条目
        self._remove_archive_records_by_class(safe_id)
        shutil.rmtree(str(class_dir))
        self.log_service.append("api", "WARNING", "物理删除班级", {"class_id": safe_id, "path": str(class_dir)})
        return {"deleted": True}

    def permanently_delete_unit(self, class_id: str, unit_id: str) -> dict:
        """物理删除单元目录，删除所有班级中含该单元的所有数据。"""
        safe_unit = self._safe_id(unit_id)
        safe_class = self._safe_id(class_id)
        if safe_class == DEFAULT_CLASS_ID and safe_unit == DEFAULT_UNIT_ID:
            return {"deleted": False, "reason": "默认单元不能删除"}
        # 遍历所有班级，删除同名单元
        deleted_count = 0
        for class_dir in sorted(self.context.classes_dir.iterdir()):
            if not class_dir.is_dir() or class_dir.name.startswith(".") or class_dir.name.startswith("__"):
                continue
            unit_dir = class_dir / "units" / safe_unit
            if unit_dir.exists():
                shutil.rmtree(str(unit_dir))
                self.log_service.append("api", "WARNING", "物理删除单元", {"class_id": class_dir.name, "unit_id": safe_unit, "path": str(unit_dir)})
                deleted_count += 1
        # 清理归档记录
        self._remove_archive_records_by_unit(safe_unit)
        return {"deleted": bool(deleted_count), "deleted_count": deleted_count}

    def permanently_delete_student(self, class_id: str, student_id: str) -> dict:
        """物理删除学生：从 CSV 移除并删除所有单元的音频和结果。"""
        safe_class = self._safe_id(class_id)
        students_path = self.get_class_dir(safe_class) / "students.csv"
        rows = self._read_students(students_path)
        removed = [row for row in rows if row.get("student_id") == student_id]
        kept = [row for row in rows if row.get("student_id") != student_id]
        if len(kept) == len(rows):
            return {"deleted": False, "reason": "学生不存在"}
        self._write_students(students_path, kept)
        student_name = removed[0].get("name", student_id) if removed else student_id
        student_key = f"{student_name}-{student_id}"
        # 删除所有单元的音频和结果
        units_dir = self.get_class_dir(safe_class) / "units"
        if units_dir.exists():
            for unit_dir in units_dir.iterdir():
                if not unit_dir.is_dir() or unit_dir.name.startswith(".") or unit_dir.name.startswith("__"):
                    continue
                # 删除音频
                audio_dir = unit_dir / "imitation_audio"
                if audio_dir.exists():
                    for audio_path in audio_dir.iterdir():
                        if audio_path.stem == student_key:
                            audio_path.unlink()
                # 删除结果
                result_dir = unit_dir / "result"
                student_result = result_dir / student_key
                if student_result.exists():
                    shutil.rmtree(str(student_result))
        self._remove_archive_records_by_student(safe_class, student_id)
        self.log_service.append("api", "WARNING", "物理删除学生", {"class_id": safe_class, "student_id": student_id})
        return {"deleted": True}

    # ---------- 归档记录管理 ----------

    def _archived_record_path(self) -> Path:
        """归档记录文件路径。"""
        return self.context.classes_dir.parent / "archived.json"

    def _read_archive_records(self) -> list[dict]:
        """读取所有归档记录。"""
        path = self._archived_record_path()
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_archive_records(self, records: list[dict]) -> None:
        """写入归档记录。"""
        path = self._archived_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _add_archive_record(self, record_type: str, *, class_name: str = "", class_id: str = "",
                            unit_id: str = "", student_id: str = "",
                            original_path: str = "", archived_path: str = "") -> str:
        """添加一条归档记录并返回记录 ID。"""
        records = self._read_archive_records()
        record_id = uuid.uuid4().hex[:12]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "id": record_id,
            "type": record_type,
            "name": class_name,
            "class_id": class_id,
            "unit_id": unit_id,
            "student_id": student_id,
            "original_path": original_path,
            "archived_path": archived_path,
            "archived_at": now,
        }
        records.append(record)
        self._write_archive_records(records)
        self.log_service.append("api", "INFO", "归档记录已添加", record)
        return record_id

    def _remove_archive_records_by_class(self, class_id: str) -> None:
        """删除指定班级的所有归档记录。"""
        records = self._read_archive_records()
        kept = [r for r in records if r.get("class_id") != class_id]
        self._write_archive_records(kept)

    def _remove_archive_records_by_unit(self, unit_id: str) -> None:
        """删除指定单元的所有归档记录。"""
        records = self._read_archive_records()
        kept = [r for r in records if r.get("unit_id") != unit_id]
        self._write_archive_records(kept)

    def _remove_archive_records_by_student(self, class_id: str, student_id: str) -> None:
        """删除指定学生的归档记录。"""
        records = self._read_archive_records()
        kept = [r for r in records if not (r.get("class_id") == class_id and r.get("student_id") == student_id)]
        self._write_archive_records(kept)

    def get_archived_items(self) -> list[dict]:
        """获取所有归档项目列表。"""
        return self._read_archive_records()

    def restore_archived_item(self, record_id: str) -> dict:
        """复原归档项目。班级/单元从 __archived__ 移回；学生重新加入 CSV。"""
        records = self._read_archive_records()
        target_record = None
        for r in records:
            if r["id"] == record_id:
                target_record = r
                break
        if not target_record:
            return {"restored": False, "reason": "归档记录不存在"}

        rtype = target_record.get("type", "")
        class_id = target_record.get("class_id", "")
        unit_id = target_record.get("unit_id", "")
        student_id = target_record.get("student_id", "")
        student_name = target_record.get("name", "")

        if rtype == "student":
            # 学生归档仅从 CSV 移除，复原即重新加入 CSV
            students_path = self.get_class_dir(class_id) / "students.csv"
            rows = self._read_students(students_path)
            if not any(r.get("student_id") == student_id for r in rows):
                rows.append({"name": student_name, "student_id": student_id, "status": "active", "note": ""})
                self._write_students(students_path, rows)
            records = [r for r in records if r["id"] != record_id]
            self._write_archive_records(records)
            self.log_service.append("api", "INFO", "复原学生", {"record_id": record_id})
            return {"restored": True, "record": target_record}

        # 班级或单元：从 __archived__ 移回原位置
        archived_path = Path(target_record.get("archived_path", ""))
        original_path = Path(target_record.get("original_path", ""))
        if not archived_path.is_absolute() or str(archived_path) in (".", ""):
            records = [r for r in records if r["id"] != record_id]
            self._write_archive_records(records)
            return {"restored": False, "reason": "归档路径无效，记录已清理"}

        if not archived_path.exists():
            records = [r for r in records if r["id"] != record_id]
            self._write_archive_records(records)
            return {"restored": False, "reason": "归档文件已不存在，记录已清理"}

        original_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(archived_path), str(original_path))
        except PermissionError:
            return {"restored": False, "reason": "文件被占用，请关闭相关程序后重试"}
        records = [r for r in records if r["id"] != record_id]
        self._write_archive_records(records)
        self.log_service.append("api", "INFO", "复原归档项目", {"record_id": record_id, "original": str(original_path)})
        return {"restored": True, "record": target_record}

    def permanently_delete_archived_item(self, record_id: str) -> dict:
        """物理删除归档项目。班级/单元删除文件；学生仅移除记录。"""
        records = self._read_archive_records()
        target_record = None
        for r in records:
            if r["id"] == record_id:
                target_record = r
                break
        if not target_record:
            return {"deleted": False, "reason": "归档记录不存在"}

        archived_path = Path(target_record.get("archived_path", ""))
        if archived_path.is_absolute() and str(archived_path) not in (".", "") and archived_path.exists():
            try:
                if archived_path.is_dir():
                    shutil.rmtree(str(archived_path))
                else:
                    archived_path.unlink()
            except PermissionError:
                return {"deleted": False, "reason": "文件被占用，请关闭相关程序后重试"}

        records = [r for r in records if r["id"] != record_id]
        self._write_archive_records(records)
        self.log_service.append("api", "WARNING", "物理删除归档项目", {"record_id": record_id, "path": str(archived_path)})
        return {"deleted": True}

    def import_students_csv(self, class_id: str, csv_text: str) -> dict:
        """从 CSV 文本导入学生名单。"""
        reader = csv.DictReader(csv_text.splitlines())
        saved = []
        rejected = []
        for row in reader:
            normalized = self._normalize_student_row(row)
            result = self.upsert_student(class_id, normalized)
            if result.get("saved"):
                saved.append(result["student"])
            else:
                rejected.append({"row": row, "reason": result.get("reason", "格式错误")})
        self.log_service.append("api", "INFO", "导入学生 CSV", {"class_id": class_id, "saved": len(saved), "rejected": len(rejected)})
        return {"saved": saved, "rejected": rejected, "students": self.list_students(class_id)["items"]}

    def upsert_students_from_audio(self, class_id: str, unit_id: str) -> dict:
        """从单元音频文件补齐班级学生名单。"""
        students_path = self.get_class_dir(class_id) / "students.csv"
        existing = {(row["name"], row["student_id"]): row for row in self._read_students(students_path)}
        audio_dir = self.get_unit_dir(class_id, unit_id) / "imitation_audio"
        for path in audio_dir.glob("*"):
            key = self._student_key_from_audio(path)
            match = _STUDENT_RE.match(key)
            if match:
                existing.setdefault((match.group(1), match.group(2)), {
                    "name": match.group(1),
                    "student_id": match.group(2),
                    "status": "active",
                    "note": "",
                })
        self._write_students(students_path, list(existing.values()))
        return self.list_students(class_id, unit_id)

    def get_unit_status(self, class_id: str, unit_id: str) -> dict:
        """获取单元素材、提交和结果状态。"""
        unit_dir = self.get_unit_dir(class_id, unit_id)
        standard_audio = list((unit_dir / "standard_audio").glob("*")) if (unit_dir / "standard_audio").exists() else []
        standard_text = list((unit_dir / "standard_text").glob("*.txt")) if (unit_dir / "standard_text").exists() else []
        audio_files = [path for path in (unit_dir / "imitation_audio").glob("*") if path.suffix.lower() in _AUDIO_EXTENSIONS]
        result_dir = unit_dir / "result"
        return {
            "standard_audio_ready": bool(standard_audio),
            "standard_text_ready": bool(standard_text),
            "student_audio_count": len(audio_files),
            "result_ready": (result_dir / "summary.csv").exists(),
            "progress_ready": (result_dir / "progress.json").exists(),
        }

    def get_class_dir(self, class_id: str) -> Path:
        """获取班级目录。"""
        return self.context.classes_dir / self._safe_id(class_id)

    def get_unit_dir(self, class_id: str, unit_id: str) -> Path:
        """获取单元目录。"""
        return self.get_class_dir(class_id) / "units" / self._safe_id(unit_id)

    def unit_paths(self, class_id: str, unit_id: str) -> dict[str, Path]:
        """获取单元关键路径。"""
        unit_dir = self.get_unit_dir(class_id, unit_id)
        return {
            "unit_dir": unit_dir,
            "standard_audio_dir": unit_dir / "standard_audio",
            "standard_text_dir": unit_dir / "standard_text",
            "imitation_audio_dir": unit_dir / "imitation_audio",
            "result_dir": unit_dir / "result",
        }

    def _copy_legacy_files(self, source: Path, target: Path) -> None:
        """非破坏性复制旧文件到默认单元。"""
        if not source.exists():
            return
        target.mkdir(parents=True, exist_ok=True)
        for path in source.iterdir():
            if path.is_file() and not (target / path.name).exists():
                shutil.copy2(path, target / path.name)

    def _copy_legacy_result_files(self, source: Path, target: Path) -> None:
        """非破坏性复制旧结果到默认单元。"""
        if not source.exists():
            return
        target.mkdir(parents=True, exist_ok=True)
        for path in source.iterdir():
            destination = target / path.name
            if destination.exists():
                continue
            if path.is_dir():
                shutil.copytree(path, destination)
            elif path.is_file():
                shutil.copy2(path, destination)

    def _ensure_students_csv(self, path: Path, audio_dir: Path) -> None:
        """确保学生名单存在。"""
        if path.exists():
            return
        rows = []
        if audio_dir.exists():
            for audio_path in audio_dir.iterdir():
                match = _STUDENT_RE.match(audio_path.stem)
                if match:
                    rows.append({"name": match.group(1), "student_id": match.group(2), "status": "active", "note": ""})
        self._write_students(path, rows)

    def _read_students(self, path: Path) -> list[dict]:
        """读取学生名单。"""
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            return [dict(row) for row in csv.DictReader(file_obj)]

    def _write_students(self, path: Path, rows: list[dict]) -> None:
        """写入学生名单。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=["name", "student_id", "status", "note"])
            writer.writeheader()
            for row in sorted(rows, key=lambda item: item.get("student_id", "")):
                writer.writerow({key: row.get(key, "") for key in writer.fieldnames})

    def _student_key_from_audio(self, path: Path) -> str:
        """从音频路径获取学生键。"""
        return path.stem

    def _normalize_student_row(self, row: dict) -> dict[str, str]:
        """兼容中英文字段名，归一化学生 CSV 行。"""
        return {
            "name": row.get("name") or row.get("姓名") or row.get("学生") or "",
            "student_id": row.get("student_id") or row.get("学号") or row.get("id") or "",
            "status": row.get("status") or row.get("状态") or "active",
            "note": row.get("note") or row.get("备注") or "",
        }

    def _timestamp(self) -> str:
        """返回用于归档目录名的时间戳。"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _write_json_if_missing(self, path: Path, data: dict[str, Any]) -> None:
        """文件不存在时写入 JSON。"""
        if not path.exists():
            self._write_json(path, data)

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        """写入 JSON 文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        """读取 JSON 文件。"""
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _slugify(self, value: str) -> str:
        """将显示名转为安全 ID。"""
        value = value.strip() or "untitled"
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value).strip("-")
        return slug or "untitled"

    def _safe_id(self, value: str) -> str:
        """限制 ID 不能逃逸 classes 目录。"""
        safe = self._slugify(value)
        if safe in {".", ".."}:
            raise ValueError("非法 ID")
        return safe