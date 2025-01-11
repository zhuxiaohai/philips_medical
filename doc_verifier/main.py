import os
import logging
import signal
import time
import sys
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from doc_verifier.logging_utils import setup_logging
from doc_verifier.utils import is_url, get_filename_from_url
from doc_verifier import config
from doc_verifier.verifier import process_single_file
from doc_verifier.averifier import aprocess_single_file
from doc_verifier.domain import DocVerifierRequest, DocUploadResponse


min_pages = config.MIN_PAGES
max_pages = 3


def signal_handler(sig, frame):
    logger.info('Interrupt received, shutting down...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


logging_config = setup_logging(os.path.join("logging_config", "logging_config.json"))
logger = logging.getLogger("doc_verifier")


app = FastAPI()


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/img/{subpath:path}")
async def get_image(subpath: str):
    file_path = os.path.join(config.IMAGE_PATH, subpath)
    
    if not os.path.commonpath([config.IMAGE_PATH, os.path.abspath(file_path)]) == os.path.abspath(config.IMAGE_PATH):
        raise HTTPException(status_code=400, detail="Invalid image path")

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(file_path, media_type="image/png")


@app.get("/data/{subpath:path}")
async def get_file(subpath: str):
    file_path = os.path.join(config.DATA_PATH, subpath)

    if not os.path.commonpath([config.DATA_PATH, os.path.abspath(file_path)]) == os.path.abspath(config.DATA_PATH):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path, media_type="application/octet-stream", filename=os.path.basename(file_path))


# @app.post("/upload/")
# async def upload(file: UploadFile = File(...), ranking: int=1):
#     if not file.filename.endswith(".pdf"):
#         logger.error(f"File {file.filename} is not a PDF!")
#         return DocUploadResponse(file_url="", file_ranking=ranking)

#     try: 
#         file_path = os.path.join(config.DATA_PATH, file.filename.replace(" ", ""))
#         with open(file_path, "wb") as f:
#             content = await file.read()
#             f.write(content)
#     except Exception as e:
#         logger.error(f"Error while uploading {file.filename}: {e}")
#         return DocUploadResponse(file_url="", file_ranking=ranking)

#     return DocUploadResponse(url=f"{config.SERVER_API}:{config.PORT}/data/{file.filename.replace(" ", "")}", ranking=ranking)


@app.post("/upload/")
async def upload(file: UploadFile = File(...), ranking: int = 1):
    if not file.filename.endswith(".pdf"):
        logger.error(f"File {file.filename} is not a PDF!")
        return DocUploadResponse(file_url="", file_ranking=ranking)

    timestamp = str(int(time.time()))
    folder_path = os.path.join(config.DATA_PATH, timestamp)
    os.makedirs(folder_path, exist_ok=True)

    try:
        sanitized_filename = file.filename.replace(" ", "_")
        file_path = os.path.join(folder_path, sanitized_filename)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        logger.error(f"Error while uploading {file.filename}: {e}")
        return DocUploadResponse(file_url="", file_ranking=ranking)

    url = f"{config.SERVER_API}:{config.PORT}/data/{timestamp}/{sanitized_filename}"
    logger.info(f"file saved as {sanitized_filename}")
    return DocUploadResponse(url=url, ranking=ranking)


@app.post("/verify/")
async def verify(query: DocVerifierRequest):
    file_path = query.url
    return StreamingResponse(
        process_single_file(file_path, min_pages, max_pages), 
        media_type="event_stream"
        )
    
    
@app.post("/averify/")
async def averify(query: DocVerifierRequest):
    file_path = query.url
    return StreamingResponse(
        aprocess_single_file(file_path, min_pages, max_pages), 
        media_type="event_stream"
        )
    

if __name__ == "__main__":
    import uvicorn
    
    logger.info(f'listening at port {config.PORT}')
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_config=logging_config)