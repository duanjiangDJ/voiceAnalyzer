"""
class_service.py — 班级与单元数据服务
===================================
管理 resource/classes 下的班级（文件夹名即名称）、resource/units 下的共享单元（文件夹名即名称）。
所有班级共享同一套单元（教材）。学生仿读音频和评估结果按班级×单元存放。

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


DEFAULT_CLASS_ID = ""
DEFAULT_UNIT_ID = ""

_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4"}
_STUDENT_RE = re.compile(r"^(.+)-(\d{10})$")


def _safe_name(raw: str) -> str:
    """将用户输入的名称转为安全的文件夹名。"""
    name = raw.strip()
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name or "untitled"


class ClassService:
    """班级与单元数据服务。"""

    def __init__(self) -> None:
        self.context = get_app_context()
        self.log_service = get_log_service()

    # ---------- 班级 ----------

    def list_classes(self) -> dict:
        """列出所有班级（文件夹名即班级名称）。"""
        items = []
        first_class = ""
        for class_dir in sorted(self.context.classes_dir.iterdir()):
            if not class_dir.is_dir() or class_dir.name.startswith(".") or class_dir.name.startswith("__"):
                continue
            if not first_class:
                first_class = class_dir.name
            units = self.list_units()["items"]
            items.append({
                "class_id": class_dir.name,
                "name": class_dir.name,
                "description": "",
                "unit_count": len(units),
                "student_count": len(self.list_students(class_dir.name)["items"]),
            })
        current_class = first_class
        unit_items = self.list_units()["items"]
        current_unit = unit_items[0]["unit_id"] if unit_items else ""
        return {"items": items, "current": {"class_id": current_class, "unit_id": current_unit}}

    def create_class(self, name: str, description: str = "") -> dict:
        """创建班级（以名称作为文件夹名）。"""
        folder = _safe_name(name)
        class_dir = self.get_class_dir(folder)
        if class_dir.exists():
            return {"class_id": folder, "name": folder, "description": "", "duplicate": True}
        class_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_students_csv(class_dir / "students.csv", class_dir / "__empty__")
        self.log_service.append("api", "INFO", f"创建班级: {name} -> {folder}", {"class_id": folder})
        return {"class_id": folder, "name": name, "description": description}

    def update_class(self, class_id: str, name: str, description: str = "") -> dict:
        """重命名班级（重命名文件夹）。"""
        safe_id = self._safe_id(class_id)
        class_dir = self.get_class_dir(safe_id)
        if not class_dir.exists():
            return {"updated": False, "reason": "班级不存在"}
        new_folder = _safe_name(name)
        if new_folder == safe_id:
            return {"updated": True, "class_id": safe_id, "name": safe_id, "description": description}
        new_dir = self.get_class_dir(new_folder)
        if new_dir.exists():
            return {"updated": False, "reason": "目标班级名已存在"}
        shutil.move(str(class_dir), str(new_dir))
        self._rename_archive_class_refs(safe_id, new_folder)
        self.log_service.append("api", "INFO", f"重命名班级: {safe_id} -> {new_folder}")
        return {"updated": True, "class_id": new_folder, "name": name, "description": description}

    def archive_class(self, class_id: str) -> dict:
        """归档班级目录。"""
        safe_id = self._safe_id(class_id)
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

    # ---------- 单元（共享教材，所有班级可见）----------

    def list_units(self, class_id: str = "") -> dict:
        """列出所有共享单元（resource/units/ 下所有子目录）。"""
        items = []
        units_dir = self.context.units_dir
        if not units_dir.exists():
            return {"items": items}
        for unit_dir in sorted(units_dir.iterdir()):
            if not unit_dir.is_dir() or unit_dir.name.startswith(".") or unit_dir.name.startswith("__"):
                continue
            status = self.get_unit_status(class_id, unit_dir.name) if class_id else {}
            items.append({
                "unit_id": unit_dir.name,
                "name": unit_dir.name,
                "description": "",
                "status": status,
            })
        return {"items": items}

    def create_unit(self, class_id: str, name: str, description: str = "") -> dict:
        """创建共享单元（在 resource/units/ 下）。class_id 参数保留兼容性但不影响位置。"""
        folder = _safe_name(name)
        unit_dir = self.context.units_dir / folder
        if unit_dir.exists():
            return {"class_id": class_id, "unit_id": folder, "name": name, "description": description, "duplicate": True}
        for child in ("standard_audio", "standard_text"):
            (unit_dir / child).mkdir(parents=True, exist_ok=True)
        self.log_service.append("api", "INFO", f"创建单元: {name} -> {folder}", {"unit_id": folder})
        return {"class_id": class_id, "unit_id": folder, "name": name, "description": description}

    def update_unit(self, class_id: str, unit_id: str, name: str, description: str = "") -> dict:
        """重命名共享单元（重命名 resource/units/ 下的文件夹）。"""
        safe_unit = self._safe_id(unit_id)
        unit_dir = self.context.units_dir / safe_unit
        if not unit_dir.exists():
            return {"updated": False, "reason": "单元不存在"}
        new_folder = _safe_name(name)
        if new_folder == safe_unit:
            return {"updated": True, "class_id": class_id, "unit_id": safe_unit, "name": safe_unit, "description": description}
        new_dir = self.context.units_dir / new_folder
        if new_dir.exists():
            return {"updated": False, "reason": "目标单元名已存在"}
        shutil.move(str(unit_dir), str(new_dir))
        for class_dir in self.context.classes_dir.iterdir():
            if not class_dir.is_dir() or class_dir.name.startswith(".") or class_dir.name.startswith("__"):
                continue
            old_class_unit = class_dir / safe_unit
            if old_class_unit.exists():
                new_class_unit = class_dir / new_folder
                shutil.move(str(old_class_unit), str(new_class_unit))
        self._rename_archive_unit_refs(safe_unit, new_folder)
        self.log_service.append("api", "INFO", f"重命名单元: {safe_unit} -> {new_folder}")
        return {"updated": True, "class_id": class_id, "unit_id": new_folder, "name": name, "description": description}

    def archive_unit(self, class_id: str, unit_id: str) -> dict:
        """归档共享单元（移动 resource/units/ 下目录到 __archived__）。"""
        safe_unit = self._safe_id(unit_id)
        unit_dir = self.context.units_dir / safe_unit
        if not unit_dir.exists():
            return {"archived": False, "reason": "单元不存在"}
        trash_dir = self.context.units_dir / "__archived__"
        trash_dir.mkdir(parents=True, exist_ok=True)
        target = trash_dir / f"{safe_unit}_{self._timestamp()}"
        shutil.move(str(unit_dir), str(target))
        self.log_service.append("api", "WARNING", "归档单元", {"unit_id": safe_unit, "target": str(target)})
        self._add_archive_record("unit", class_name=safe_unit, class_id=class_id, unit_id=safe_unit, original_path=str(unit_dir), archived_path=str(target))
        return {"archived": True, "target": str(target)}

    # ---------- 学生 ----------

    def list_students(self, class_id: str, unit_id: str | None = None) -> dict:
        """列出班级学生，并可叠加指定单元提交状态。"""
        students_path = self.get_class_dir(class_id) / "students.csv"
        students = self._read_students(students_path)
        audio_map = {}
        if unit_id:
            audio_dir = self._class_unit_dir(class_id, unit_id) / "imitation_audio"
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
        class_dir = self.get_class_dir(safe_id)
        if not class_dir.exists():
            return {"deleted": False, "reason": "班级不存在"}
        self._remove_archive_records_by_class(safe_id)
        shutil.rmtree(str(class_dir))
        self.log_service.append("api", "WARNING", "物理删除班级", {"class_id": safe_id, "path": str(class_dir)})
        return {"deleted": True}

    def permanently_delete_unit(self, class_id: str, unit_id: str) -> dict:
        """物理删除共享单元：删除 resource/units/ 下的目录以及所有班级下的该单元数据。"""
        safe_unit = self._safe_id(unit_id)
        unit_dir = self.context.units_dir / safe_unit
        if unit_dir.exists():
            shutil.rmtree(str(unit_dir))
            self.log_service.append("api", "WARNING", "物理删除共享单元", {"unit_id": safe_unit, "path": str(unit_dir)})
        deleted_count = 0
        for class_dir in self.context.classes_dir.iterdir():
            if not class_dir.is_dir() or class_dir.name.startswith(".") or class_dir.name.startswith("__"):
                continue
            class_unit = class_dir / safe_unit
            if class_unit.exists():
                shutil.rmtree(str(class_unit))
                self.log_service.append("api", "WARNING", "物理删除班级单元数据", {"class_id": class_dir.name, "unit_id": safe_unit})
                deleted_count += 1
        self._remove_archive_records_by_unit(safe_unit)
        return {"deleted": bool(unit_dir.exists() or deleted_count > 0), "deleted_count": deleted_count}

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
        for unit_dir in self.context.units_dir.iterdir():
            if not unit_dir.is_dir() or unit_dir.name.startswith(".") or unit_dir.name.startswith("__"):
                continue
            class_unit = self.get_class_dir(safe_class) / unit_dir.name
            audio_dir = class_unit / "imitation_audio"
            if audio_dir.exists():
                for audio_path in audio_dir.iterdir():
                    if audio_path.stem == student_key:
                        audio_path.unlink()
            result_dir = class_unit / "result"
            student_result = result_dir / student_key
            if student_result.exists():
                shutil.rmtree(str(student_result))
        self._remove_archive_records_by_student(safe_class, student_id)
        self.log_service.append("api", "WARNING", "物理删除学生", {"class_id": safe_class, "student_id": student_id})
        return {"deleted": True}

    # ---------- 归档记录管理 ----------

    def _archived_record_path(self) -> Path:
        return self.context.classes_dir.parent / "archived.json"

    def _read_archive_records(self) -> list[dict]:
        path = self._archived_record_path()
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_archive_records(self, records: list[dict]) -> None:
        path = self._archived_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _add_archive_record(self, record_type: str, *, class_name: str = "", class_id: str = "",
                            unit_id: str = "", student_id: str = "",
                            original_path: str = "", archived_path: str = "") -> str:
        records = self._read_archive_records()
        record_id = uuid.uuid4().hex[:12]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "id": record_id, "type": record_type, "name": class_name,
            "class_id": class_id, "unit_id": unit_id, "student_id": student_id,
            "original_path": original_path, "archived_path": archived_path, "archived_at": now,
        }
        records.append(record)
        self._write_archive_records(records)
        self.log_service.append("api", "INFO", "归档记录已添加", record)
        return record_id

    def _remove_archive_records_by_class(self, class_id: str) -> None:
        records = self._read_archive_records()
        kept = [r for r in records if r.get("class_id") != class_id]
        self._write_archive_records(kept)

    def _remove_archive_records_by_unit(self, unit_id: str) -> None:
        records = self._read_archive_records()
        kept = [r for r in records if r.get("unit_id") != unit_id]
        self._write_archive_records(kept)

    def _remove_archive_records_by_student(self, class_id: str, student_id: str) -> None:
        records = self._read_archive_records()
        kept = [r for r in records if not (r.get("class_id") == class_id and r.get("student_id") == student_id)]
        self._write_archive_records(kept)

    def _rename_archive_class_refs(self, old_id: str, new_id: str) -> None:
        records = self._read_archive_records()
        for r in records:
            if r.get("class_id") == old_id:
                r["class_id"] = new_id
        self._write_archive_records(records)

    def _rename_archive_unit_refs(self, old_id: str, new_id: str) -> None:
        records = self._read_archive_records()
        for r in records:
            if r.get("unit_id") == old_id:
                r["unit_id"] = new_id
        self._write_archive_records(records)

    def get_archived_items(self) -> list[dict]:
        return self._read_archive_records()

    def restore_archived_item(self, record_id: str) -> dict:
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
            students_path = self.get_class_dir(class_id) / "students.csv"
            rows = self._read_students(students_path)
            if not any(r.get("student_id") == student_id for r in rows):
                rows.append({"name": student_name, "student_id": student_id, "status": "active", "note": ""})
                self._write_students(students_path, rows)
            records = [r for r in records if r["id"] != record_id]
            self._write_archive_records(records)
            self.log_service.append("api", "INFO", "复原学生", {"record_id": record_id})
            return {"restored": True, "record": target_record}

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
        students_path = self.get_class_dir(class_id) / "students.csv"
        existing = {(row["name"], row["student_id"]): row for row in self._read_students(students_path)}
        audio_dir = self._class_unit_dir(class_id, unit_id) / "imitation_audio"
        for path in audio_dir.glob("*"):
            key = self._student_key_from_audio(path)
            match = _STUDENT_RE.match(key)
            if match:
                existing.setdefault((match.group(1), match.group(2)), {
                    "name": match.group(1), "student_id": match.group(2), "status": "active", "note": "",
                })
        self._write_students(students_path, list(existing.values()))
        return self.list_students(class_id, unit_id)

    def get_unit_status(self, class_id: str, unit_id: str) -> dict:
        shared = self.context.units_dir / unit_id
        class_unit = self._class_unit_dir(class_id, unit_id) if class_id else None
        standard_audio = list((shared / "standard_audio").glob("*")) if shared.exists() else []
        standard_text = list((shared / "standard_text").glob("*.txt")) if shared.exists() else []
        audio_files = list((class_unit / "imitation_audio").glob("*")) if class_unit and (class_unit / "imitation_audio").exists() else []
        result_dir = class_unit / "result" if class_unit else None
        return {
            "standard_audio_ready": bool(standard_audio),
            "standard_text_ready": bool(standard_text),
            "student_audio_count": len([f for f in audio_files if f.suffix.lower() in _AUDIO_EXTENSIONS]),
            "result_ready": result_dir.exists() and (result_dir / "summary.csv").exists() if result_dir else False,
            "progress_ready": result_dir.exists() and (result_dir / "progress.json").exists() if result_dir else False,
        }

    # ---------- 路径工具 ----------

    def get_class_dir(self, class_id: str) -> Path:
        return self.context.classes_dir / self._safe_id(class_id)

    def get_unit_dir(self, class_id: str, unit_id: str) -> Path:
        return self.context.units_dir / self._safe_id(unit_id)

    def _class_unit_dir(self, class_id: str, unit_id: str) -> Path:
        return self.get_class_dir(class_id) / self._safe_id(unit_id)

    def unit_paths(self, class_id: str, unit_id: str) -> dict[str, Path]:
        shared = self.context.units_dir / self._safe_id(unit_id)
        class_unit = self._class_unit_dir(class_id, unit_id)
        return {
            "unit_dir": shared,
            "standard_audio_dir": shared / "standard_audio",
            "standard_text_dir": shared / "standard_text",
            "imitation_audio_dir": class_unit / "imitation_audio",
            "result_dir": class_unit / "result",
        }

    # ---------- 内部辅助 ----------

    def _safe_id(self, raw: str) -> str:
        if not raw:
            return ""
        return raw

    def _ensure_students_csv(self, path: Path, audio_dir: Path) -> None:
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
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            return [dict(row) for row in csv.DictReader(file_obj)]

    def _write_students(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=["name", "student_id", "status", "note"])
            writer.writeheader()
            for row in sorted(rows, key=lambda item: item.get("student_id", "")):
                writer.writerow({key: row.get(key, "") for key in writer.fieldnames})

    def _student_key_from_audio(self, path: Path) -> str:
        return path.stem

    def _normalize_student_row(self, row: dict) -> dict[str, str]:
        return {
            "name": row.get("name") or row.get("姓名") or row.get("学生") or "",
            "student_id": row.get("student_id") or row.get("学号") or row.get("id") or "",
            "status": row.get("status") or row.get("状态") or "active",
            "note": row.get("note") or row.get("备注") or "",
        }

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _read_json(self, path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return default
