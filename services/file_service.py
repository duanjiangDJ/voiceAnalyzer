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


_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4"}
_STUDENT_FILE_RE = re.compile(r"^(.+)-(\d{10})\.(wav|mp3|m4a|flac|ogg|mp4)$", re.IGNORECASE)


class FileService:
    """素材文件服务。"""

    def __init__(self) -> None:
        self.context = get_app_context()
        self.class_service = ClassService()
        self.log_service = get_log_service()

    def get_status(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """获取素材准备状态。"""
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

    # ---------- 音频管理 ----------

    def list_student_audio_status(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """获取班级学生的音频提交状态（含提交时间与评分进度）。"""
        items = []
        students = self.class_service.list_students(class_id, unit_id)["items"]
        paths = self.class_service.unit_paths(class_id, unit_id)
        audio_dir = paths["imitation_audio_dir"]
        result_dir = paths["result_dir"]
        # 构建已有音频映射：student_key -> (filename, mtime)
        audio_map: dict[str, tuple[str, float]] = {}
        if audio_dir.exists():
            for path in audio_dir.iterdir():
                if path.suffix.lower() not in _AUDIO_EXTENSIONS:
                    continue
                key = path.stem
                audio_map[key] = (path.name, path.stat().st_mtime)
        # 读取 progress.json 获取评分状态（voice+text 均 done 才算已评分）
        scored_set: set[str] = set()
        progress_path = result_dir / "progress.json"
        if progress_path.exists():
            import json as _json
            try:
                with progress_path.open("r", encoding="utf-8") as f:
                    pdata = _json.load(f)
                for student_key, state in pdata.get("students", {}).items():
                    if isinstance(state, dict) and state.get("voice") == "done" and state.get("text") == "done":
                        scored_set.add(student_key)
            except Exception:
                pass
        for idx, student in enumerate(students):
            key = student.get("student_key", "")
            audio_info = audio_map.get(key)
            has_audio = audio_info is not None
            has_score = key in scored_set
            score_status = "已评分" if has_score else "未评分"
            items.append({
                "index": idx + 1,
                "name": student.get("name", ""),
                "student_id": student.get("student_id", ""),
                "student_key": key,
                "submit_status": "submitted" if has_audio else "missing",
                "submit_time": self._format_mtime(audio_info[1]) if has_audio else "-",
                "filename": audio_info[0] if has_audio else "-",
                "score_status": score_status,
            })
        return {"items": items}

    async def save_single_student_audio(self, upload: UploadFile, student_name: str = "", student_id: str = "",
                                        class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """上传单个学生音频（指定姓名学号或从文件名解析）。"""
        original = Path(upload.filename or "").name
        ext = Path(original).suffix.lower()
        if ext not in _AUDIO_EXTENSIONS:
            return {"saved": False, "reason": f"不支持的音频格式: {ext}"}

        # 尝试从文件名解析
        match = _STUDENT_FILE_RE.match(original)
        parsed_name = match.group(1) if match else ""
        parsed_id = match.group(2) if match else ""
        # 优先使用手动指定的姓名学号
        final_name = student_name.strip() or parsed_name
        final_id = student_id.strip() or parsed_id

        if not final_name or not final_id:
            return {"saved": False, "reason": "无法识别姓名学号，请手动选择学生"}

        # 校验学生是否在班级中
        students = self.class_service.list_students(class_id)["items"]
        student_ids = {s["student_id"] for s in students}
        if final_id not in student_ids:
            return {"saved": False, "reason": f"学号 {final_id} 不在当前班级名单中"}

        # 生成规范文件名
        target_name = f"{final_name}-{final_id}{ext}"
        paths = self.class_service.unit_paths(class_id, unit_id)
        paths["imitation_audio_dir"].mkdir(parents=True, exist_ok=True)
        target = paths["imitation_audio_dir"] / target_name
        with target.open("wb") as file_obj:
            shutil.copyfileobj(upload.file, file_obj)
        self.log_service.append("api", "INFO", "上传学生音频", {"class_id": class_id, "unit_id": unit_id, "filename": target_name})
        return {"saved": True, "filename": target_name, "student_name": final_name, "student_id": final_id}

    async def parse_batch_audio_files(self, files: list[UploadFile], class_id: str = DEFAULT_CLASS_ID,
                                      unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """解析批量上传的音频文件（含 zip），返回解析结果但不保存。"""
        students = self.class_service.list_students(class_id)["items"]
        student_ids = {s["student_id"] for s in students}
        # 构建姓名↔学号映射
        name_to_id: dict[str, str] = {}
        id_to_name: dict[str, str] = {}
        for s in students:
            n, sid = s.get("name", ""), s.get("student_id", "")
            if n and sid:
                name_to_id[n] = sid
                id_to_name[sid] = n

        items: list[dict] = []
        valid_count = 0
        extensions = _AUDIO_EXTENSIONS

        for upload in files:
            filename = Path(upload.filename or "").name
            if not filename:
                continue
            ext = Path(filename).suffix.lower()

            # 处理 zip
            if ext == ".zip":
                zip_items = await self._parse_zip_files(upload, extensions, student_ids, name_to_id, id_to_name)
                items.extend(zip_items)
                valid_count += sum(1 for i in zip_items if i.get("status") == "ok")
                continue

            # 单文件解析
            item = self._parse_single_audio(filename, ext, extensions, student_ids, name_to_id, id_to_name)
            items.append(item)
            if item.get("status") == "ok":
                valid_count += 1

        return {"items": items, "valid_count": valid_count, "total": len(items)}

    def _parse_single_audio(self, filename: str, ext: str, extensions: set, student_ids: set,
                             name_to_id: dict, id_to_name: dict) -> dict:
        """解析单个音频文件。"""
        if ext not in extensions:
            return {"filename": filename, "student_name": "-", "student_id": "-",
                    "status": "invalid_format", "status_text": "格式不支持", "valid": False}

        match = _STUDENT_FILE_RE.match(filename)
        parsed_name = match.group(1) if match else ""
        parsed_id = match.group(2) if match else ""

        if parsed_name and parsed_id:
            if parsed_id in student_ids:
                return {"filename": filename, "student_name": parsed_name, "student_id": parsed_id,
                        "status": "ok", "status_text": "已识别", "valid": True}
            else:
                return {"filename": filename, "student_name": parsed_name, "student_id": parsed_id,
                        "status": "not_in_class", "status_text": "不在班级中", "valid": False}

        # 无法解析
        return {"filename": filename, "student_name": "-", "student_id": "-",
                "status": "unrecognized", "status_text": "无法识别", "valid": False}

    async def _parse_zip_files(self, upload: UploadFile, extensions: set, student_ids: set,
                                name_to_id: dict, id_to_name: dict) -> list[dict]:
        """解析 zip 中的音频文件。"""
        filename = Path(upload.filename or "").name
        items: list[dict] = []
        tmp_path = self.context.uploads_dir / "tmp" / filename
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                for info in zf.infolist():
                    source_name = Path(info.filename).name
                    if not source_name or info.is_dir():
                        continue
                    ext = Path(source_name).suffix.lower()
                    item = self._parse_single_audio(source_name, ext, extensions, student_ids, name_to_id, id_to_name)
                    item["_zip_entry"] = info.filename
                    items.append(item)
        finally:
            tmp_path.unlink(missing_ok=True)
        return items

    async def commit_batch_audios(self, items: list[dict], files: list[UploadFile],
                                  class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """确认并保存批量音频（含从 zip 提取的文件）。"""
        paths = self.class_service.unit_paths(class_id, unit_id)
        paths["imitation_audio_dir"].mkdir(parents=True, exist_ok=True)
        saved = []
        failed = []

        # 建立 zip 文件缓存：zip_filename -> (tmp_path, zipfile)
        zip_cache: dict[str, tuple[Path, zipfile.ZipFile]] = {}

        try:
            for item in items:
                if not item.get("valid") or item.get("status") != "ok":
                    failed.append({"filename": item.get("filename", ""), "reason": item.get("status_text", "")})
                    continue

                fname = item.get("filename", "")
                student_name = item.get("student_name", "")
                student_id = item.get("student_id", "")
                ext = Path(fname).suffix.lower()
                target_name = f"{student_name}-{student_id}{ext}"
                target = paths["imitation_audio_dir"] / target_name

                zip_entry = item.get("_zip_entry")
                if zip_entry:
                    # 来自 zip —— 需要从原始 zip 中提取
                    target.write_bytes(b"")  # placeholder, will be overwritten
                    # 找到对应的 zip upload 并提取
                    for u in files:
                        ufname = Path(u.filename or "").name
                        if Path(ufname).suffix.lower() == ".zip":
                            if ufname not in zip_cache:
                                tmp = self.context.uploads_dir / "tmp" / ufname
                                tmp.parent.mkdir(parents=True, exist_ok=True)
                                with tmp.open("wb") as f:
                                    await u.seek(0)
                                    shutil.copyfileobj(u.file, f)
                                zip_cache[ufname] = (tmp, zipfile.ZipFile(tmp))
                            _, zf = zip_cache[ufname]
                            try:
                                with zf.open(zip_entry) as src, target.open("wb") as dst:
                                    shutil.copyfileobj(src, dst)
                                saved.append(target_name)
                            except KeyError:
                                failed.append({"filename": fname, "reason": "zip 中找不到该条目"})
                else:
                    # 直接上传的文件
                    for u in files:
                        if Path(u.filename or "").name == fname:
                            await u.seek(0)
                            with target.open("wb") as dst:
                                shutil.copyfileobj(u.file, dst)
                            saved.append(target_name)
                            break
        finally:
            for tmp_path, zf in zip_cache.values():
                zf.close()
                tmp_path.unlink(missing_ok=True)

        self.class_service.upsert_students_from_audio(class_id, unit_id)
        self.log_service.append("api", "INFO", "批量提交学生音频", {"class_id": class_id, "unit_id": unit_id, "saved": len(saved), "failed": len(failed)})
        return {"saved": saved, "failed": failed}

    def delete_student_audio(self, filename: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """删除指定学生音频文件。"""
        paths = self.class_service.unit_paths(class_id, unit_id)
        target = paths["imitation_audio_dir"] / filename
        if not target.exists():
            return {"deleted": False, "reason": "文件不存在"}
        target.unlink()
        self.log_service.append("api", "WARNING", "删除学生音频", {"class_id": class_id, "unit_id": unit_id, "filename": filename})
        return {"deleted": True}

    def delete_student_result(self, student_key: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """删除指定学生在当前单元的所有评分结果（含 summary.csv 行与 progress.json 进度）。"""
        paths = self.class_service.unit_paths(class_id, unit_id)
        result_dir = paths["result_dir"]
        student_result = result_dir / student_key
        deleted = False
        if student_result.exists():
            shutil.rmtree(str(student_result))
            deleted = True
        # 同时从 summary.csv 中移除该学生的行
        summary_path = result_dir / "summary.csv"
        if summary_path.exists():
            import csv as _csv
            rows = []
            with summary_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = _csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                rows = [row for row in reader if row.get("学生", "") != student_key]
            if fieldnames:
                tmp = summary_path.with_suffix(".csv.tmp")
                with tmp.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = _csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                tmp.replace(summary_path)
                deleted = True
        # 同时从 progress.json 中移除该学生的进度
        import json as _json
        progress_path = result_dir / "progress.json"
        if progress_path.exists():
            try:
                progress_data = _json.loads(progress_path.read_text(encoding="utf-8"))
                students_dict = progress_data.get("students", {})
                if student_key in students_dict:
                    del students_dict[student_key]
                    progress_data["students"] = students_dict
                    tmp = progress_path.with_suffix(".json.tmp")
                    tmp.write_text(_json.dumps(progress_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp.replace(progress_path)
            except (_json.JSONDecodeError, OSError):
                pass
        self.log_service.append("api", "WARNING", "删除学生评分结果", {"class_id": class_id, "unit_id": unit_id, "student_key": student_key})
        return {"deleted": deleted}

    def _format_mtime(self, timestamp: float) -> str:
        """格式化修改时间为可读字符串。"""
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

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