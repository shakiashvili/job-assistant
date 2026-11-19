from fastapi import HTTPException, UploadFile

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024


async def read_upload_bounded(
    upload: UploadFile,
    max_bytes: int = MAX_UPLOAD_SIZE_BYTES,
    chunk_size: int = 65536,
) -> bytes:
    """
    Streams an UploadFile in fixed chunks and aborts immediately with HTTP 413
    before buffering oversized payloads into memory.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Uploaded file exceeds 10 MB maximum size limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)
