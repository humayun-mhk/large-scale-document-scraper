import re
from pathlib import Path
from urllib.parse import urlparse

CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def choose_extension(content_type: str | None, url: str) -> str:
    if content_type:
        clean_type = content_type.split(";")[0].strip().lower()
        if clean_type in CONTENT_TYPE_EXTENSIONS:
            return CONTENT_TYPE_EXTENSIONS[clean_type]

    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}:
        return suffix

    return ".bin"


def build_final_path(base_dir: str, organization: str, doc_type: str, document_id: int, extension: str) -> Path:
    folder = Path(base_dir) / slugify(organization) / slugify(doc_type)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{document_id}{extension}"
