from fastapi import APIRouter, UploadFile, File, HTTPException, status
from core.status_code import StatusCode
from fastapi.responses import JSONResponse
import shutil
import os
import uuid
import time
from typing import List
from config import settings

router = APIRouter()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


# Magic numbers for common file types
# Format: extension -> list of valid signatures (hex bytes)
MAGIC_NUMBERS = {
    'jpg':  [b'\xFF\xD8\xFF'],
    'jpeg': [b'\xFF\xD8\xFF'],
    'png':  [b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'],
    'gif':  [b'\x47\x49\x46\x38'],
    'pdf':  [b'\x25\x50\x44\x46'],
    'doc':  [b'\xD0\xCF\x11\xE0'], # Old Office format
    'docx': [b'\x50\x4B\x03\x04'], # Zip format (Office 2007+)
}

async def validate_and_save_file(file: UploadFile, save_path: str, max_size: int) -> int:
    """
    Validate file content (magic number) and save securely with size limit.
    Returns: File size in bytes.
    Raises: HTTPException on validation failure or size limit exceeded.
    """
    # 1. Check Extension (First line of defense)
    ext = file.filename.split('.')[-1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=StatusCode.BAD_REQUEST,
            detail=f"不支持的文件类型. 允许的类型: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    # 2. Magic Number Validation (Read first 2KB)
    header = await file.read(2048)
    if not header:
        raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="空文件")
    
    # Check signature if we have a definition for this extension
    if ext in MAGIC_NUMBERS:
        valid_signatures = MAGIC_NUMBERS[ext]
        is_valid = False
        for signature in valid_signatures:
            if header.startswith(signature):
                is_valid = True
                break
        
        if not is_valid:
            # Check for docx/zip conflict (docx is technically a zip)
            if ext == 'docx' and header.startswith(b'\x50\x4B\x03\x04'):
                 pass
            else:
                 raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="文件内容与扩展名不符")

    # Reset cursor for writing
    await file.seek(0)
    
    # 3. Streaming Write with Size Limit
    file_size = 0
    chunk_size = 1024 * 64 # 64KB chunks
    
    try:
        with open(save_path, "wb") as buffer:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                
                file_size += len(chunk)
                if file_size > max_size:
                    buffer.close()
                    os.remove(save_path) # Cleanup partial file
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件大小超过限制 ({max_size / 1024 / 1024}MB)"
                    )
                
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
         if os.path.exists(save_path):
             os.remove(save_path)
         raise HTTPException(status_code=StatusCode.INTERNAL_SERVER_ERROR, detail=f"文件保存失败: {str(e)}")

    return file_size

@router.post("")
async def upload_file(file: UploadFile = File(...)):
    """
    通用文件上传接口 (Secure)
    - 验证文件头 (Magic Number)
    - 限制文件大小
    - 防止内存溢出 (Streaming)
    """
    ext = file.filename.split('.')[-1].lower()
    filename = f"{uuid.uuid4().hex}_{int(time.time())}.{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, filename)
    
    # Validate and Save
    file_size = await validate_and_save_file(file, file_path, settings.MAX_UPLOAD_SIZE)
    
    file_url = f"{settings.STATIC_URL_PREFIX}/uploads/{filename}"
    
    return {
        "filename": filename,
        "url": file_url,
        "content_type": file.content_type,
        "size": file_size
    }
