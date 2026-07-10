"""
file_service.py — 素材文件服务
=============================
封装按班级/单元管理的标准音频、标准文本、学生音频、压缩包上传与知识库读取。

依赖:
    - csv, re, shutil, zipfile, pathlib（标准库）
    - fastapi.UploadFile（第三方）
    - services.app_context（项目内部模块）
"""

import csv
import re
import shutil
import zipfile
from pathlib import Path

from fastapi import UploadFile

from services.app_context import get_app_context
from services.class_service import ClassService, DEFAULT_CLASS_ID, DEFAULT_UNIT_ID
from services.log_service import get_log_service


_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}
_STUDENT_FILE_RE = re.compile(r"^(.+)-(\d{10})\.(wav|mp3|m4a)$", re.IGNORECASE)


class FileService:
    """素材文件服务。"""

    def __init__(self) -> None:
        self.context = get_app_context()
        self.class_service = ClassService()
        self.log_service = get_log_service()

    def get_status(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """获取素材准备状态。"""
        self.class_service.ensure_default_workspace()
        paths = self.class_service.unit_paths(class_id, unit_id)
        standard_audios = self._audio_files(paths["standard_audio_dir"])
        standard_text = paths["standard_text_dir"] / "standard.txt"
        student_audios = self.list_student_audios(class_id, unit_id)
        knowledge_files = list(self.context.knowledge_dir.glob("*.csv")) if self.context.knowledge_dir.exists() else []
        return {
            "class_id": class_id,
            "unit_id": unit_id,
            "standard_audio_ready": bool(standard_audios),
            "standard_audio_count": len(standard_audios),
            "standard_text_ready": standard_text.exists(),
            "student_audio_count": len(student_audios["items"]),
            "invalid_student_audio_count": len([item for item in student_audios["items"] if not item["valid"]]),
            "knowledge_ready": bool(knowledge_files),
            "standard_audios": standard_audios,
        }

    def read_standard_text(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """读取标准文本内容和统计信息。"""
        paths = self.class_service.unit_paths(class_id, unit_id)
        path = paths["standard_text_dir"] / "standard.txt"
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        words = [word for word in re.split(r"\s+", content.strip()) if word]
        sentences = [item for item in re.split(r"[.!?。！？]+", content) if item.strip()]
        return {"content": content, "word_count": len(words), "sentence_count": len(sentences)}

    def save_standard_text(self, content: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """保存标准文本。"""
        paths = self.class_service.unit_paths(class_id, unit_id)
        paths["standard_text_dir"].mkdir(parents=True, exist_ok=True)
        path = paths["standard_text_dir"] / "standard.txt"
        tmp_path = path.with_suffix(".txt.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
        self.log_service.append("api", "INFO", "保存标准文本", {"class_id": class_id, "unit_id": unit_id})
        return self.read_standard_text(class_id, unit_id)

    def list_student_audios(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """获取学生音频列表。"""
        items = []
        paths = self.class_service.unit_paths(class_id, unit_id)
        audio_dir = paths["imitation_audio_dir"]
        if not audio_dir.exists():
            return {"items": items}
        for path in sorted(audio_dir.iterdir()):
            if path.suffix.lower() not in _AUDIO_EXTENSIONS:
                continue
            match = _STUDENT_FILE_RE.match(path.name)
            items.append({
                "filename": path.name,
                "student_name": match.group(1) if match else "",
                "student_id": match.group(2) if match else "",
                "size": path.stat().st_size,
                "modified_at": path.stat().st_mtime,
                "valid": bool(match),
            })
        return {"items": items}

    async def save_student_audios(self, files: list[UploadFile], class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """批量保存学生音频。"""
        paths = self.class_service.unit_paths(class_id, unit_id)
        paths["imitation_audio_dir"].mkdir(parents=True, exist_ok=True)
        saved = []
        rejected = []
        for upload in files:
            filename = Path(upload.filename or "").name
            if not _STUDENT_FILE_RE.match(filename):
                rejected.append({"filename": filename, "reason": "命名不符合 {姓名}-{10位学号}.{ext}"})
                continue
            target = paths["imitation_audio_dir"] / filename
            with target.open("wb") as file_obj:
                shutil.copyfileobj(upload.file, file_obj)
            saved.append(filename)
        self.class_service.upsert_students_from_audio(class_id, unit_id)
        self.log_service.append("api", "INFO", "上传学生音频", {"class_id": class_id, "unit_id": unit_id, "saved": len(saved), "rejected": len(rejected)})
        return {"saved": saved, "rejected": rejected, "students": self.list_student_audios(class_id, unit_id)["items"]}

    async def save_student_uploads(self, files: list[UploadFile], class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """统一保存学生音频或 zip 压缩包。"""
        saved = []
        rejected = []
        for upload in files:
            filename = Path(upload.filename or "").name
            if Path(filename).suffix.lower() == ".zip":
                result = await self.save_student_audio_zip(upload, class_id, unit_id)
            else:
                result = await self.save_student_audios([upload], class_id, unit_id)
            saved.extend(result.get("saved", []))
            rejected.extend(result.get("rejected", []))
        self.log_service.append("api", "INFO", "统一上传学生录音", {"class_id": class_id, "unit_id": unit_id, "saved": len(saved), "rejected": len(rejected)})
        return {"saved": saved, "rejected": rejected, "students": self.list_student_audios(class_id, unit_id)["items"]}

    async def save_student_audio_zip(self, upload: UploadFile, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """上传并解压包含学生音频的 zip 文件。"""
        filename = Path(upload.filename or "").name
        if Path(filename).suffix.lower() != ".zip":
            return {"saved": [], "rejected": [{"filename": filename, "reason": "仅支持 zip 压缩包"}]}
        tmp_path = self.context.uploads_dir / "tmp" / filename
        with tmp_path.open("wb") as file_obj:
            shutil.copyfileobj(upload.file, file_obj)
        paths = self.class_service.unit_paths(class_id, unit_id)
        paths["imitation_audio_dir"].mkdir(parents=True, exist_ok=True)
        saved = []
        rejected = []
        try:
            with zipfile.ZipFile(tmp_path) as zip_obj:
                for info in zip_obj.infolist():
                    source_name = Path(info.filename).name
                    if not source_name or info.is_dir():
                        continue
                    if not _STUDENT_FILE_RE.match(source_name):
                        rejected.append({"filename": info.filename, "reason": "命名不符合 {姓名}-{10位学号}.{ext}"})
                        continue
                    target = paths["imitation_audio_dir"] / source_name
                    with zip_obj.open(info) as source, target.open("wb") as target_obj:
                        shutil.copyfileobj(source, target_obj)
                    saved.append(source_name)
        finally:
            tmp_path.unlink(missing_ok=True)
        self.class_service.upsert_students_from_audio(class_id, unit_id)
        self.log_service.append("api", "INFO", "上传学生音频压缩包", {"class_id": class_id, "unit_id": unit_id, "saved": len(saved), "rejected": len(rejected)})
        return {"saved": saved, "rejected": rejected, "students": self.list_student_audios(class_id, unit_id)["items"]}

    async def save_standard_audio(self, upload: UploadFile, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """保存标准音频。"""
        filename = Path(upload.filename or "").name
        if Path(filename).suffix.lower() not in _AUDIO_EXTENSIONS:
            return {"saved": False, "reason": "不支持的音频格式"}
        paths = self.class_service.unit_paths(class_id, unit_id)
        paths["standard_audio_dir"].mkdir(parents=True, exist_ok=True)
        target = paths["standard_audio_dir"] / filename
        with target.open("wb") as file_obj:
            shutil.copyfileobj(upload.file, file_obj)
        self.log_service.append("api", "INFO", "上传标准音频", {"class_id": class_id, "unit_id": unit_id, "filename": filename})
        return {"saved": True, "filename": filename, "standard_audios": self._audio_files(paths["standard_audio_dir"])}

    def read_knowledge_preview(self) -> dict:
        """读取知识库 CSV 的前 50 行。"""
        files = sorted(self.context.knowledge_dir.glob("*.csv")) if self.context.knowledge_dir.exists() else []
        if not files:
            return {"columns": [], "rows": []}
        with files[0].open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            rows = [row for _, row in zip(range(50), reader)]
            return {"filename": files[0].name, "columns": reader.fieldnames or [], "rows": rows}

    def _audio_files(self, directory: Path) -> list[dict]:
        """列出目录下的音频文件。"""
        if not directory.exists():
            return []
        return [
            {"filename": path.name, "size": path.stat().st_size, "modified_at": path.stat().st_mtime}
            for path in sorted(directory.iterdir())
            if path.suffix.lower() in _AUDIO_EXTENSIONS
        ]