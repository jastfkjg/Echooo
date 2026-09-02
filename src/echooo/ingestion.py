from __future__ import annotations
import io
import zipfile
from pathlib import Path
from echooo.service import Problem

MAX_UPLOAD = 5 * 1024 * 1024


def extract_file(filename: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD:
        raise Problem("文件不得超过 5 MB。")
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".txt", ".md", ".csv", ".json"}:
            content = data.decode("utf-8-sig")
        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted or len(reader.pages) > 100:
                raise Problem("请上传未加密且不超过 100 页的 PDF。")
            content = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        elif suffix == ".docx":
            from docx import Document
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 20 * 1024 * 1024:
                    raise Problem("解压后文件过大。")
            doc = Document(io.BytesIO(data))
            content = "\n".join([p.text for p in doc.paragraphs] +
                [" | ".join(cell.text for cell in row.cells) for t in doc.tables for row in t.rows])
        else:
            raise Problem("支持 TXT、Markdown、CSV、JSON、PDF 和 DOCX。")
    except Problem:
        raise
    except Exception as exc:
        raise Problem("无法读取文件，请检查格式或改为粘贴文字。") from exc
    if not content.strip():
        raise Problem("未提取到文字；扫描 PDF 请先进行 OCR。")
    if len(content) > 100000:
        raise Problem("提取内容超过 100,000 字符，请拆分文件。")
    return content.strip()
