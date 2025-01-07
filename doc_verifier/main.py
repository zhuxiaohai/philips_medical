import os
from typing import List
from urllib.parse import urlparse
import copy
import logging
import signal
import sys
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import numpy as np
import pandas as pd
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from doc_verifier.logging_utils import setup_logging
from doc_verifier import config
from doc_verifier.verifier import verify_multiple_files
from doc_verifier.plot_utils import extract_specific_messages_from_log_file, draw_bounding_boxes_on_pdf, clear_path
from doc_verifier.domain import DocVerifierRequest, DocVerifierResponse, DocUploadResponse


def signal_handler(sig, frame):
    logger.info('Interrupt received, shutting down...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

endpoint = os.getenv('AZURE_ENDPOINT', 'default_value')
key = os.getenv('AZURE_KEY', 'default_value')
min_pages = config.MIN_PAGES
max_pages = config.MAX_PAGES
document_analysis_client = DocumentAnalysisClient(
    endpoint=endpoint, credential=AzureKeyCredential(key)
)

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


@app.get("/img/{file_name}")
async def get_image(file_name: str):
    if os.path.exists(os.path.join(config.IMAGE_PATH, file_name)):
        return FileResponse(os.path.join(config.IMAGE_PATH, file_name), media_type="image/png")
    else:
        raise HTTPException(status_code=404, detail="Image not found")


@app.get("/data/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(config.DATA_PATH, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type="application/octet-stream", filename=filename)


@app.post("/upload/")
async def upload(file: UploadFile = File(...), ranking: int=1):
    if not file.filename.endswith(".pdf"):
        logger.error(f"File {file.filename} is not a PDF!")
        return DocUploadResponse(file_url="", file_ranking=ranking)

    try: 
        file_path = os.path.join(config.DATA_PATH, file.filename)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        logger.error(f"Error while uploading {file.filename}: {e}")
        return DocUploadResponse(file_url="", file_ranking=ranking)

    return DocUploadResponse(url=f"{config.SERVER_API}:{config.PORT}/data/{file.filename}", ranking=ranking)


@app.post("/verify/")
async def verify(query: DocVerifierRequest):
    # transform to dict input 
    all_files = copy.deepcopy(query.query)
    files_dict = {}
    for file in all_files:
        file_name = urlparse(file["file_path"]).path.split("/")[-1]
        if "ranking" not in file:
            file["ranking"] = 1
        files_dict[file_name] = {key: file[key] for key in file if key != "file_name"}
    input_dict = {key: files_dict[key] for key in files_dict if files_dict[key]}
    
    # feed input to verifier and log
    _ = await asyncio.to_thread(lambda: verify_multiple_files(input_dict, min_pages, max_pages, document_analysis_client))
    # results = await asyncio.to_thread(lambda: verify_multiple_files(input_dict, min_pages, max_pages, document_analysis_client))
    # valid_to_verify = False
    # for file_name, file_info in results.items():
    #     if file_info["file_result"]["author_cell"] \
    #     or file_info["file_result"]["author_date"] \
    #     or file_info["file_result"]["philips_cell"] \
    #     or file_info["file_result"]["philips_date"] \
    #     or file_info["file_result"]["errors"]:
    #         valid_to_verify = True
    #         break
    # if not valid_to_verify:
    #     logger.info("no errors are found")
    #     return DocVerifierResponse(response=[])

    # extract errors from log
    try:
        errors = extract_specific_messages_from_log_file(
            logging_config["handlers"]["fileHandler"]["filename"], 
            )
    except Exception as e:
        logger.error(f"Error while extracting messages from log file: {e}")
        return DocVerifierResponse(**all_result)
    if not errors:
        logger.info("no errors are extracted")
        return DocVerifierResponse(response=[])
    else:
        logger.info("errors are extracted from log file")
        
    df = pd.DataFrame(errors)
    df = df.set_index("file_name").merge(
        pd.DataFrame(input_dict).T.reset_index(drop=False).rename(columns={"index": "file_name"}).set_index("file_name"), 
        how="right", left_index=True, right_index=True
        ).reset_index(drop=False)
    
    # process errors of log, output all_result
    all_result = []
    df = df.sort_values(["ranking", "file_name", "page_number"])
    files = df["file_name"].unique()
    clear_path(config.IMAGE_PATH)
    for file in files:
        file_df = df[df["file_name"] == file]
        if file_df["page_number"].isnull().values[0]:
            logger.info(f"no errors are extracted from {file}")
            continue
        else:
            logger.info(f"Start ploting on {file}")
        file_result = []
        pages = np.sort(file_df["page_number"].unique())
        for page in pages:
            page = int(page)
            page_df = file_df[file_df["page_number"] == page]
            bounding_regions = page_df["bounding_regions"].tolist()
            bounding_regions = [(idx, item) for idx, sublist in enumerate(bounding_regions) for item in sublist]
            image_path = os.path.join(config.IMAGE_PATH, f"{file}_page{page}.png")
            image_url = f"{config.SERVER_API}:{config.PORT}/img/{file}_page{page}.png"
            try:
                phisical_path = os.path.join(config.DATA_PATH, urlparse(page_df["file_path"].values[0]).path.split("/")[-1])
                draw_bounding_boxes_on_pdf(
                    phisical_path, 
                    bounding_regions, 
                    image_path, 
                    page
                )
            except Exception as e:
                logger.error(f"Error while drawing bounding boxes on pdf: {e}")
                continue
            file_result.append(
                {
                    "page_number": page, 
                    "page_image": image_url, 
                    "errors": page_df[["content", "error_type"]].to_dict(orient="records")
                }
            )
        all_result.append({"file_name": file, "pages": file_result})
        logger.info(f"Completed ploting on {file}")
    
    if all_result:
        logger.info("Ploting completed")
    return DocVerifierResponse(response=all_result)


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f'listening at port {config.PORT}')
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_config=logging_config)