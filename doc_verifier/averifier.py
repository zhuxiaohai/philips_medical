import os
import json
from urllib.parse import urlparse
import logging
import asyncio
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import AnalysisFeature
from doc_verifier.utils import (
    extract_signature_tables, extract_signature_pairs, extract_styles, 
    get_hands_written_spans, get_color_spans, identify_author_and_philips,
    has_intersection, is_valid_date_format, format_date, extract_page_number,
    get_pdf_page_number, is_url, get_file_name_and_local_path_from_url
)
from doc_verifier.logging_utils import DocumentError
from doc_verifier.plot_utils import draw_bounding_boxes_on_pdf
from doc_verifier import config


logger = logging.getLogger("doc_verifier")


def process_page(
    file_path: str, 
    file_name: str, 
    page_number: int,
    author_date: str = "", 
    author_cell: dict = None, 
    philips_date : str = "",
    philips_cell: dict = None
    ):
    logger.debug(f"begin to process page{page_number} of {file_name}")
    
    image_url = ""
    errors = []
    poller = None
    
    endpoint = os.getenv('AZURE_ENDPOINT', 'default_value')
    key = os.getenv('AZURE_KEY', 'default_value')
    document_analysis_client = DocumentAnalysisClient(
        endpoint=endpoint, credential=AzureKeyCredential(key)
    )
    
    try:
        if is_url(file_path):
            poller = document_analysis_client.begin_analyze_document_from_url(
                "prebuilt-layout",
                document_url=file_path,
                pages=f"{page_number}",
                features=[AnalysisFeature.STYLE_FONT]
            )
        else:
            with open(file_path, "rb") as f:
                poller = document_analysis_client.begin_analyze_document(
                    "prebuilt-layout",
                    document=f,
                    pages=f"{page_number}",
                    features=[AnalysisFeature.STYLE_FONT]
                )
    except Exception as e:
        raise FileNotFoundError(f"Failed to verify document: {e}")
    
    if not poller:
        logger.debug(f"page{page_number} of {file_name} can not be parsed")
        return {
        "file_name": file_name,
        "page_number": page_number, 
        "results": {
            "author_cell": author_cell,
            "author_date": author_date,
            "philips_cell": philips_cell,
            "philips_date": philips_date,
            "page_image": image_url,
            "errors": errors
            }
        }
    
    logger.debug(f"page {page_number} of {file_name} parsed!")

    result = poller.result()
        
    page_numbers = extract_page_number(result)
    signature_tables = extract_signature_tables(result)
    signature_pairs = extract_signature_pairs(result)
    hands_written_styles, color_styles = extract_styles(result)
    hands_written_spans = get_hands_written_spans(hands_written_styles)
    color_spans = get_color_spans(color_styles)
    
    for page_number, ocr_page_number in page_numbers.items():
        
        if page_number != ocr_page_number["printed_number"]:
            error = DocumentError(file_name, ocr_page_number["content"], page_number, ocr_page_number["bounding_regions"], "page number is not valid")
            errors.append(error)
            logger.info(error)
    
    for table_idx, signature_table in enumerate(signature_tables):
        
        person_count = 0
        
        for person in signature_table["persons"]:
            if (not person["signature"]["content"]) and (not person["date"]["content"]):
                continue
            else:
                if person['signature']["spans"] and (not has_intersection(person['signature']["spans"], hands_written_spans)):
                    error = DocumentError(file_name, person['signature']["content"], page_number, person['signature']["bounding_regions"], "signature is not handwritten")
                    errors.append(error)
                    logger.info(error)
                if person['date']["spans"] and (not has_intersection(person['date']["spans"], hands_written_spans)):
                    error = DocumentError(file_name, person['date']["content"], page_number, person['date']["bounding_regions"], "date is not handwritten")
                    errors.append(error)
                    logger.info(error)
                if person['signature']["spans"] and has_intersection(person['signature']["spans"], color_spans):
                    error = DocumentError(file_name, person['signature']["content"], page_number, person['signature']["bounding_regions"], "signature is not black")
                    errors.append(error)
                    logger.info(error)
                if person['date']["spans"] and has_intersection(person['date']["spans"], color_spans):
                    error = DocumentError(file_name, person['date']["content"], page_number, person['date']["bounding_regions"], "date is not black")
                    errors.append(error)
                    logger.info(error)
                if person.get("role") and (person["role"].find("philips") >= 0) and (not is_valid_date_format(person["date"]["content"])) and (page_number > 1):
                    error = DocumentError(file_name, person['date']["content"], page_number, person['date']["bounding_regions"], "philips date format is invalid") 
                    errors.append(error)
                    logger.info(error)
                person_count += 1
        
        if person_count == 0:
            error = DocumentError(file_name, "", page_number, signature_table["bounding_regions"], "signatures and dates are missing")
            errors.append(error)
            logger.info(error)

        if (page_number == 1) and (table_idx == 0) and (person_count > 0):
            author_cell, author_date, philips_cell, philips_date = identify_author_and_philips(signature_table)
            if author_cell and (not author_date):
                error = DocumentError(file_name, author_cell["signature"]["content"], page_number, author_cell["date"]["bounding_regions"], "author date is missing")
                errors.append(error)
                logger.info(error)
            if philips_cell and (not philips_date):
                error = DocumentError(file_name, philips_cell["signature"]["content"], page_number, philips_cell["date"]["bounding_regions"], "philips date is missing")
                errors.append(error)
                logger.info(error)
            if philips_cell and (not is_valid_date_format(philips_cell["date"]["content"])):
                error = DocumentError(file_name, philips_cell["date"]["content"], page_number, philips_cell["date"]["bounding_regions"], "philips date format is invalid")
                errors.append(error)
                logger.info(error)
        
        for person in signature_table["persons"]:
            formatted_date = format_date(person["date"]["content"])
            if formatted_date and author_date and (formatted_date < author_date):
                error = DocumentError(file_name, person["date"]["content"], page_number, person["date"]["bounding_regions"], "date is ahead of author date")
                errors.append(error)
                logger.info(error)
            if formatted_date and philips_date and (formatted_date > philips_date):
                error = DocumentError(file_name, person["date"]["content"], page_number, person["date"]["bounding_regions"], "date is behind philips date")
                errors.append(error)
                logger.info(error)
            if (page_number > 1) or (table_idx > 0):
                if (person.get("role", "").find("philips") >= 0) and (not is_valid_date_format(person["date"]["content"])):
                    error = DocumentError(file_name, person["date"]["content"], page_number, person["date"]["bounding_regions"], "philips date format is invalid")
                    errors.append(error)
                    logger.info(error)

    for pair in signature_pairs:
        if (not pair["signature"]["content"]) and (not pair["date"]["content"]):
            error = DocumentError(file_name, "", page_number, pair["signature"]["bounding_regions"]+pair["date"]["bounding_regions"], "signatures and dates are missing")
            errors.append(error)
            logger.info(error)
        else:
            if pair["signature"]["spans"] and (not has_intersection(pair["signature"]["spans"], hands_written_spans)):
                error = DocumentError(file_name, pair['signature']["content"], page_number, pair['signature']["bounding_regions"], "signature is not handwritten")
                errors.append(error)
                logger.info(error)
            if pair["date"]["spans"] and (not has_intersection(pair["date"]["spans"], hands_written_spans)):
                error = DocumentError(file_name, pair['date']["content"], page_number, pair['date']["bounding_regions"], "date is not handwritten")
                errors.append(error)
                logger.info(error)
            if pair["signature"]["spans"] and has_intersection(pair["signature"]["spans"], color_spans):
                error = DocumentError(file_name, pair['signature']["content"], page_number, pair['signature']["bounding_regions"], "signature is not black")
                errors.append(error)
                logger.info(error)
            if pair["date"]["spans"] and has_intersection(pair["date"]["spans"], color_spans):
                error = DocumentError(file_name, pair['date']["content"], page_number, pair['date']["bounding_regions"], "date is not black")
                errors.append(error)
                logger.info(error)
            formatted_date = format_date(pair["date"]["content"])
            if formatted_date and author_date and (formatted_date < author_date):
                error = DocumentError(file_name, pair["date"]["content"], page_number, pair["date"]["bounding_regions"], "date is ahead of author date")
                errors.append(error)
                logger.info(error)
            if formatted_date and philips_date and (formatted_date > philips_date):
                error = DocumentError(file_name, pair["date"]["content"], page_number, pair["date"]["bounding_regions"], "date is behind philips date")
                errors.append(error)
                logger.info(error)
                
    if errors:
        bounding_regions = [i.bounding_regions for i in errors]
        bounding_regions = [(idx, item) for idx, sublist in enumerate(bounding_regions) for item in sublist]
        try:
            logger.info(f"start ploting on page{page_number} of {file_name}")
            image_path = os.path.join(config.IMAGE_PATH, os.path.splitext(file_name)[0], f"page{page_number}.png")
            local_file_path, _ = get_file_name_and_local_path_from_url(file_path)
            draw_bounding_boxes_on_pdf(
                local_file_path, 
                bounding_regions, 
                image_path, 
                page_number
            )
            image_url = f"{config.SERVER_API}:{config.PORT}/img/{os.path.splitext(file_name)[0]}/page{page_number}.png"
            logger.info(f"image saved for page{page_number} of {file_name}")
        except Exception as e:
            logger.error(f"Error while drawing bounding boxes on page{page_number} of {file_name}: {e}")
    
    response = {
        "file_name": file_name,
        "page_number": page_number, 
        "results": {
            "author_cell": author_cell,
            "author_date": author_date,
            "philips_cell": philips_cell,
            "philips_date": philips_date,
            "page_image": image_url,
            "errors": [error.__dict__ for error in errors] if errors else errors
            }
        }
    return response


async def averify_single_file(
    queue: asyncio.Queue,
    semaphore_number: int,
    file_path: str, 
    min_pages: int, 
    max_pages: int, 
    start_page: int = 1,
    ):
    """
    The function performs the following checks:
        - Verifies if the document contains handwritten signatures and dates.
        - Checks if the signatures and dates are present and correctly formatted.
        - Logs errors if signatures or dates are missing, not handwritten, or incorrectly formatted.
        - Ensures that dates are within valid ranges relative to author and Philips dates.
    The verification process continues until the specified page range is exhausted or an invalid argument error is encountered.
    Args:
        file_path (str): The path to the document file to be verified.
        min_pages (int): The minimum page number to start verification.
        max_pages (int): The maximum page number to end verification.
    Returns:
        dict: A dictionary containing the errors, author and Philips dates and cells.
    """
    local_file_path, file_name, num_pages = get_pdf_page_number(file_path)
    processed_image_folder = os.path.join(config.IMAGE_PATH, os.path.splitext(file_name)[0])
    os.makedirs(processed_image_folder, exist_ok=True)
    logger.debug(f"procssed image will be saved in {processed_image_folder}")
    
    logger.info(f"Begin to analyze {file_name}...")
    
    start_page = max(min_pages, start_page)
    if start_page == 1:
        try:
            result = process_page(local_file_path, file_name, start_page)
            author_date = result["results"]["author_date"]
            author_cell = result["results"]["author_cell"]
            philips_date = result["results"]["philips_date"]
            philips_cell = result["results"]["philips_cell"]
            
            logger.debug(f"page {start_page} of {file_name} results in queue")
            
            await queue.put(result)
            start_page += 1
        except Exception as e:
            logger.error(f"Error processing page {start_page}: {e}")
            await queue.put({"error": str(e)})
            return
    else:
        author_date = ""
        author_cell = None
        philips_date = ""
        philips_cell = None
    
    semaphore = asyncio.Semaphore(semaphore_number)

    async def aprocess_with_semaphore(page_number):
        async with semaphore:
            try:
                result = await asyncio.to_thread(
                    process_page,
                    local_file_path, 
                    file_name, 
                    page_number, 
                    author_date,
                    author_cell,
                    philips_date,
                    philips_cell,
                    )
                
                logger.debug(f"page {page_number} of {file_name} results in queue")
                
                await queue.put(result)
            except Exception as e:
                logger.error(f"Error processing page {page_number}: {e}")
                await queue.put({"error": str(e)})

    tasks = [
        aprocess_with_semaphore(page_number)
        for page_number in range(start_page, min(max_pages, num_pages) + 1)
    ]
    
    await asyncio.gather(*tasks)

    await queue.put(None)
    
    logger.info(f"Complete analyzing {file_name}.")
    
    
async def asend_single_file_result(queue: asyncio.Queue, next_page = 1):
    results_buffer = {}  
    while True:
        result = await queue.get()
        if not result:
            break
        if "error" in result:
            yield f"data: {{\"task cancelled\": \"{result['error']}\"}}\n\n"
            break
        page_number = result["page_number"]
        results_buffer[page_number] = result

        while next_page in results_buffer:
            
            logger.debug(f"page {next_page} of {results_buffer[next_page]["file_name"]} sent!")
            
            yield f"data: {json.dumps(results_buffer.pop(next_page), ensure_ascii=False)}\n\n"
            next_page += 1
            
            
async def aprocess_single_file(
    file_path: str, 
    min_pages: int, 
    max_pages: int, 
    start_page: int = 1,
    semaphore_number: int = 4
    ):
    queue = asyncio.Queue()
    producer_task = asyncio.create_task(
        averify_single_file(
            queue, 
            semaphore_number, 
            file_path, 
            min_pages, 
            max_pages, 
            start_page
            )
        )
    
    try:
        async for result in asend_single_file_result(queue, start_page):
            yield result
            if "task cancelled" in result:
                producer_task.cancel() 
                break
    finally:
        await producer_task
            

# def verify_multiple_files(files_dict: dict, min_pages: int, max_pages: int, document_analysis_client: DocumentAnalysisClient) -> dict:
#     """
#     The function checks all the files for signatures and dates, and verifies that the 
#     chronological order of the 'philips_date' in the documents matches the ranking order. For example, 
#     if file1 has a ranking of 1 and file2 has a ranking of 2, then file1's 'philips_date' should be 
#     earlier than file2's 'philips_date'.
#     Args:
#         files_dict (dict): A dictionary containing the file names and their corresponding file paths 
#                            and rankings.
#         min_pages (int): The minimum page number to start verification.
#         max_pages (int): The maximum page number to end verification.
#         document_analysis_client (DocumentAnalysisClient): The client used for document analysis.
#     Returns:
#         files_dict (dict): A dictionary containing the file names and their corresponding errors
#     """
#     logger.info("Begin to analyze all files.")
    
#     files_dict = files_dict.copy()
    
#     for file_name, file_info in files_dict.items():
#         if not file_info["file_path"]:
#             continue
#         try:
#             file_result = verify_single_file(file_info["file_path"], file_name, min_pages, max_pages, document_analysis_client)
#             file_info["file_result"] = file_result
#         except Exception as e:
#             file_info["file_result"] = {
#                 "author_cell": None,
#                 "author_date": "",
#                 "philips_cell": None,
#                 "philips_date": "",
#                 "errors": [DocumentError(file_name, str(e), 0, [], "execution error")]
#             }    

#     # make a list and sort it by ranking
#     philips_dates = []
    
#     for file_name, file_info in files_dict.items():
#         if file_info["file_result"]["philips_date"]:
#             philips_dates.append(
#                 {
#                     "file_name": file_name, 
#                     "file_ranking": file_info["ranking"], 
#                     "file_date": file_info["file_result"]["philips_date"]
#                 }
#             )
        
#     if philips_dates:
#         philips_dates.sort(key=lambda x: x["file_ranking"])
#         for i in range(1, len(philips_dates)):
#             if philips_dates[i]["file_date"] < philips_dates[i-1]["file_date"]:
#                 file_name = philips_dates[i]["file_name"]
#                 error = DocumentError(
#                     file_name,
#                     files_dict[file_name]["file_result"]["philips_cell"]["date"]["content"],
#                     files_dict[file_name]["file_result"]["philips_cell"]["date"]["bounding_regions"]["page_number"], 
#                     files_dict[file_name]["file_result"]["philips_cell"]["date"]["bounding_regions"],
#                     f"{file_name} is signed earlier than {philips_dates[i-1]["file_name"]}"
#                     )
#                 files_dict[file_name]["file_result"]["errors"].append(error)
#                 logger.info(error)
    
#     logger.info("Complete analyzing all files.")
              
#     return files_dict