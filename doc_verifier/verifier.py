import logging
from azure.ai.formrecognizer import DocumentAnalysisClient, AnalysisFeature
from doc_verifier.utils import (
    extract_signature_tables, extract_signature_pairs, extract_styles, 
    get_hands_written_spans, get_color_spans, identify_author_and_philips,
    has_intersection, is_valid_date_format, format_date, extract_page_number
)
from doc_verifier.logging_utils import DocumentError

logger = logging.getLogger("doc_verifier")


def verify_single_file(file_path: str, file_name: str, min_pages: int, max_pages: int, document_analysis_client: DocumentAnalysisClient,
                       start_page=1) -> dict:
    """
    The function performs the following checks:
        - Verifies if the document contains handwritten signatures and dates.
        - Checks if the signatures and dates are present and correctly formatted.
        - Logs errors if signatures or dates are missing, not handwritten, or incorrectly formatted.
        - Ensures that dates are within valid ranges relative to author and Philips dates.
    The verification process continues until the specified page range is exhausted or an invalid argument error is encountered.
    Args:
        file_path (str): The path to the document file to be verified.
        file_name (str): The name of the document file to be verified.
        min_pages (int): The minimum page number to start verification.
        max_pages (int): The maximum page number to end verification.
        document_analysis_client (DocumentAnalysisClient): The client used to analyze the document.
    Returns:
        dict: A dictionary containing the errors, author and Philips dates and cells.
    """
    logger.info(f"Begin to analyze {file_name}...")
    
    author_date, philips_date = "", ""
    author_cell, philips_cell = None, None
    errors = []
    page_number = start_page
    
    while True and (page_number >= min_pages) and (page_number <= max_pages):
        
        poller = None
        
        try:
            # Code that may raise an exception
            poller = document_analysis_client.begin_analyze_document_from_url(
                "prebuilt-layout",
                document_url=file_path,
                pages=f"{page_number}",
                features=[AnalysisFeature.STYLE_FONT]
            )
        except Exception as e:
            # Check if the exception message contains "Invalid argument"
            if "Invalid argument" in str(e):
                break
            else:
                # Re-raise the exception if it's not the specific error you're looking for
                raise
        
        if not poller:
            break
        
        logger.debug(f"page {page_number} parsed!")
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
                    if person.get("role") and person["role"].find("philips") >= 0 and (not is_valid_date_format(person["date"]["content"])):
                        error = DocumentError(file_name, person['date']["content"], page_number, person['date']["bounding_regions"], "date format is invalid") 
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
                    error = DocumentError(file_name, person["signature"]["content"], page_number, person["date"]["bounding_regions"], "date is ahead of author date")
                    errors.append(error)
                    logger.info(error)
                if formatted_date and philips_date and (formatted_date > philips_date):
                    error = DocumentError(file_name, person["signature"]["content"], page_number, person["date"]["bounding_regions"], "date is behind philips date")
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
                    error = DocumentError(file_name, pair["signature"]["content"], page_number, pair["date"]["bounding_regions"], "date is ahead of author date")
                    errors.append(error)
                    logger.info(error)
                if formatted_date and philips_date and (formatted_date > philips_date):
                    error = DocumentError(file_name, pair["signature"]["content"], page_number, pair["date"]["bounding_regions"], "date is behind philips date")
                    errors.append(error)
                    logger.info(error)

        page_number += 1
        
    logger.info(f"Complete analyzing {file_name}.")
    
    return {
        "author_cell": author_cell,
        "author_date": author_date,
        "philips_cell": philips_cell,
        "philips_date": philips_date,
        "errors": errors
    }


def verify_multiple_files(files_dict: dict, min_pages: int, max_pages: int, document_analysis_client: DocumentAnalysisClient) -> dict:
    """
    The function checks all the files for signatures and dates, and verifies that the 
    chronological order of the 'philips_date' in the documents matches the ranking order. For example, 
    if file1 has a ranking of 1 and file2 has a ranking of 2, then file1's 'philips_date' should be 
    earlier than file2's 'philips_date'.
    Args:
        files_dict (dict): A dictionary containing the file names and their corresponding file paths 
                           and rankings.
        min_pages (int): The minimum page number to start verification.
        max_pages (int): The maximum page number to end verification.
        document_analysis_client (DocumentAnalysisClient): The client used for document analysis.
    Returns:
        files_dict (dict): A dictionary containing the file names and their corresponding errors
    """
    logger.info("Begin to analyze all files.")
    
    files_dict = files_dict.copy()
    
    for file_name, file_info in files_dict.items():
        if not file_info["file_path"]:
            continue
        try:
            file_result = verify_single_file(file_info["file_path"], file_name, min_pages, max_pages, document_analysis_client)
            file_info["file_result"] = file_result
        except Exception as e:
            file_info["file_result"] = {
                "author_cell": None,
                "author_date": "",
                "philips_cell": None,
                "philips_date": "",
                "errors": [DocumentError(file_name, str(e), 0, [], "execution error")]
            }    

    # make a list and sort it by ranking
    philips_dates = []
    
    for file_name, file_info in files_dict.items():
        if file_info["file_result"]["philips_date"]:
            philips_dates.append(
                {
                    "file_name": file_name, 
                    "file_ranking": file_info["ranking"], 
                    "file_date": file_info["file_result"]["philips_date"]
                }
            )
        
    if philips_dates:
        philips_dates.sort(key=lambda x: x["file_ranking"])
        for i in range(1, len(philips_dates)):
            if philips_dates[i]["file_date"] < philips_dates[i-1]["file_date"]:
                file_name = philips_dates[i]["file_name"]
                error = DocumentError(
                    file_name,
                    files_dict[file_name]["file_result"]["philips_cell"]["date"]["content"],
                    files_dict[file_name]["file_result"]["philips_cell"]["date"]["bounding_regions"]["page_number"], 
                    files_dict[file_name]["file_result"]["philips_cell"]["date"]["bounding_regions"],
                    f"{file_name} is signed earlier than {philips_dates[i-1]["file_name"]}"
                    )
                files_dict[file_name]["file_result"]["errors"].append(error)
                logger.info(error)
    
    logger.info("Complete analyzing all files.")
              
    return files_dict