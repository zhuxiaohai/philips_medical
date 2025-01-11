from collections import deque, defaultdict
from datetime import datetime
import re
import os
import logging
import fitz
import requests
from urllib.parse import urlparse
from typing import List, Dict, Any

from azure.ai.formrecognizer import BoundingRegion

from doc_verifier import config


logger = logging.getLogger("doc_verifier")


def is_url(address):
    regex = re.compile(
        r'^(?:http|https)://'  # URL 必须以 http:// 或 https:// 开头
        r'(?:\S+(?::\S*)?@)?'  # 可选的用户认证信息
        r'(?:[A-Za-z0-9.-]+|\[[A-Fa-f0-9:]+\])'  # 域名或 IP 地址
        r'(?::\d+)?'  # 可选的端口
        r'(?:/\S*)?$'  # 可选的路径
    )
    return re.match(regex, address) is not None


def get_filename_from_url(url):
    parsed_url = urlparse(url)
    url_parts = parsed_url.path.split("/")
    if (parsed_url.scheme.find("http") >= 0) and (len(url_parts) > 2) and (url_parts[-2] != "data"):
        return "/".join(url_parts[-2:])
    else:
        return os.path.basename(parsed_url.path)


def download_file(url, save_path):
    response = requests.get(url, stream=True)
    response.raise_for_status()  
    with open(save_path, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
            
            
def get_file_name_and_local_path_from_url(address):
    if is_url(address):
        filename = get_filename_from_url(address)
        local_file_path = os.path.join(config.DATA_PATH, filename)
    else:
        filename = os.path.basename(address)
        local_file_path = address
    return local_file_path, filename
            

def get_pdf_page_number(address):
    if is_url(address):
        filename = get_filename_from_url(address)
        local_file_path = os.path.join(config.DATA_PATH, filename)
    else:
        filename = os.path.basename(address)
        local_file_path = address

    if not os.path.exists(local_file_path):
        if is_url(address): 
            logger.info(f"downloading from: {address}")
            os.makedirs(config.DATA_PATH, exist_ok=True) 
            download_file(address, local_file_path)
            logger.info(f"saved to: {local_file_path}")
        else:
            raise FileNotFoundError(f"local file not available: {local_file_path}")
        
    try:
        with fitz.open(local_file_path) as pdf_document:
            total_pages = pdf_document.page_count
        logger.info(f"read {total_pages} pages from {local_file_path}")
    except Exception as e:
        raise FileNotFoundError(f"Failed to read from {local_file_path}: {e}")

    return local_file_path, filename, total_pages


def is_valid_date_format(date_str):
    # Define the regex pattern for the date formats
    pattern = r'^\d{1,2}[-.\s]*[A-Za-z]{3}[-.\s]*\d{4}$'
    
    # Check if the date string matches the pattern
    if re.match(pattern, date_str):
        return True
    return False

def format_date(date_str):
    if not date_str:
        return ""
    
    # Remove any extra spaces
    date_str = re.sub(r'\s+', '', date_str)
    
    # Define possible date formats
    date_formats = [
        "%Y-%m-%d",
        "%Y-%m.%d",
        "%Y.%m-%d",
        "%Y.%m.%d",
        "%Y/%m/%d",
        "%d.%b-%Y",
        "%d.%b.%Y",
        "%d.%b%Y",
        "%d-%b-%Y",
        "%d-%b.%Y",
        "%d-%b%Y",
        "%d%b-%Y",
        "%d%b.%Y",
        "%d%b%Y",
    ]
    
    for date_format in date_formats:
        try:
            # Try to parse the date string
            date_obj = datetime.strptime(date_str, date_format)
            # Return the formatted date string
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    # If no format matches, raise an error
    # raise ValueError(f"Date format for '{date_str}' is not recognized")
    return ""

def extract_signature_tables(result: Any) -> List[Dict[str, Dict[str, Any]]]:
    """
    Extracts signature tables from the result object.
    
    Args:
        result: Object containing tables with cells having content, row_index, 
                column_index, spans, and bounding_regions attributes.
    
    Returns:
        List of dictionaries, each representing a table with extracted signature 
        information. Each dictionary contains keys:
            - "row_count": int, the number of rows in the table
            - "column_count": int, the number of columns in the table
            - "bounding_regions": List[Dict[str, Any]], the bounding regions of the table
            - "persons": List[Dict[str, Any]], a list of dictionaries, each representing a person with keys:
                - "name": str, the name of the person
                - "role": str, the role or title of the person
                - "signature": Dict[str, Any], a dictionary with keys:
                    "content": str, the content of the signature
                    "spans": List[Dict[str, Any]], the spans of the signature
                    "bounding_regions": List[Dict[str, Any]], the bounding regions of the signature
                - "date": Dict[str, Any], a dictionary with keys:
                    "content": str, the content of the date
                    "spans": List[Dict[str, Any]], the spans of the date
                    "bounding_regions": List[Dict[str, Any]], the bounding regions of the date
    """
    signature_tables = []
    for table in result.tables:
        headers = [cell.content.lower() for cell in table.cells if cell.row_index == 0]
        if set(headers) >= {"signature", "date"}:
            table_dict = {
                "row_count": table.row_count, 
                "column_count": table.column_count, 
                "bounding_regions": [region.to_dict() for region in table.bounding_regions], 
                "persons": []
            }
            for row_index in range(1, table.row_count):
                person = {}
                for cell in table.cells:
                    if cell.row_index == row_index:
                        header = headers[cell.column_index]
                        if (header.find("name") >= 0) or (header.find("print") >= 0):
                            person["name"] = cell.content.strip().lower()
                        elif (header.find("role") >= 0) or (header.find("title") >= 0):
                            person["role"] = cell.content.strip().lower()
                        elif header.find("signature") >= 0:
                            person["signature"] = {
                                "content": cell.content.strip().lower(),
                                "spans": [span.to_dict() for span in cell.spans],
                                "bounding_regions": [region.to_dict() for region in cell.bounding_regions]
                                }
                        elif header.find("date") >= 0:
                            person["date"] = {
                                "content": cell.content.strip().lower(),
                                "spans": [span.to_dict() for span in cell.spans],
                                "bounding_regions": [region.to_dict() for region in cell.bounding_regions]
                                }
                table_dict[f"persons"].append(person)
            signature_tables.append(table_dict)
    
    return signature_tables

def extract_signature_pairs(result) -> List[Dict[str, Dict[str, Any]]]:
    """
    Extracts signature and date pairs from the result object.
    
    Args:
        result (object): Contains pages and lines to be processed.
    
    Returns:
        List[Dict[str, Dict[str, Any]]]: Each dictionary contains:
            - "signature": {
                "content": str,
                "spans": List,
                "bounding_regions": List[Dict[str, Any]]
            }
            - "date": {
                "content": str,
                "spans": List,
                "bounding_regions": List[Dict[str, Any]]
            }
    """
    # Extract signatures and dates
    signatures = deque()
    dates = deque()

    page_index = 0
    while page_index < len(result.pages):
        page = result.pages[page_index]
        line_index = 0
        while line_index < len(page.lines):
            line = page.lines[line_index]
            text = line.content.lower()
            if "completed by" in text:
                signature_context = text.split("completed by")[-1].strip().lower()
                signature = signature_context[signature_context.find(":")+1:]
                if (not signature) and (line_index + 1 < len(page.lines)) and (
                    "completion date" not in page.lines[line_index + 1].content.lower()):
                    line_index += 1
                    line = page.lines[line_index]
                    signature = line.content.strip().lower()
                signatures.append((signature, page.page_number, line.polygon, line.spans))
            elif "completion date" in text:
                date_context = text.split("completion date")[-1].strip().lower()
                date = date_context[date_context.find(":")+1:]
                if (not date) and (line_index + 1 < len(page.lines)):
                    line_index += 1
                    line = page.lines[line_index]
                    date = line.content.strip().lower()
                dates.append((date, page.page_number, line.polygon, line.spans))
            line_index += 1
        page_index += 1

    # Pair signatures with dates
    pairs = []
    while signatures and dates:
        signature, sig_page, sig_polygon, sig_spans = signatures.popleft()
        date, date_page, date_polygon, date_spans = dates.popleft()
        pairs.append(
            {"signature": {
                "content": signature, 
                "spans": [span.to_dict() for span in sig_spans],
                "bounding_regions": [BoundingRegion(polygon=sig_polygon, page_number=sig_page).to_dict()]
                },    
             "date": {
                 "content": date, 
                 "spans": [span.to_dict() for span in date_spans],
                 "bounding_regions": [BoundingRegion(polygon=date_polygon, page_number=date_page).to_dict()]
                 }
             }
            )
        
    return pairs

def hex_to_rgb(hex_color):
    # Convert hex color string to RGB tuple.
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def is_blue(rgb_color):
    # Determine if the given RGB color is in the blue range.
    r, g, b = rgb_color
    # Define a threshold to determine if a color is blue
    # Here we assume a color is blue if the blue component 
    # is significantly higher than red and green
    return b > r and b > g

def filter_blue_colors(hex_color):
    # decide if a hex color string represents blue color.
    rgb_color = hex_to_rgb(hex_color)
    return is_blue(rgb_color)

def get_styled_text(styles):
    # Iterate over the styles and merge the spans from each style.
    spans = [span for style in styles for span in style["spans"]]
    spans.sort(key=lambda span: span["offset"])
    return spans

def extract_styles(result):
    # Group styles by their font attributes
    hands_written = defaultdict(list)  
    colors = defaultdict(list)  
    # Iterate over the styles and group them by their font attributes.
    for style in result.styles:
        style = style.to_dict()
        if style["is_handwritten"]:
            hands_written[style["is_handwritten"]].append(style)
        if style["color"]:
            colors[style["color"]].append(style)
    return hands_written, colors


def extract_page_number(result):
    """
    Extract page numbers from the OCR recognized text in the result of the azure_document_intelligence prebuilt_layout model.

    Args:
        result: The result object from the azure_document_intelligence prebuilt_layout model.

    Returns:
        dict: A dictionary where keys are page indices and values are the extracted page numbers.
    """
    page_numbers = {}
    page_number_patterns = [
        re.compile(r'page\s*[^0-9]*\s*(\d+)', re.IGNORECASE),
        re.compile(r'page\s*[^0-9]*\s*(\d+)\s*[^0-9]*\s*\d+', re.IGNORECASE),
        re.compile(r'page\s*[^0-9]*\s*(\d+)\s*[^0-9]*\s*\d+', re.IGNORECASE),
        re.compile(r'page\s*[^0-9]*\s*(\d+)\s*[^0-9]*\s*\d+', re.IGNORECASE),
        re.compile(r'page\s*[^0-9]*\s*(\d+)\s*[^0-9]*\s*\d+', re.IGNORECASE)
    ]

    for page in result.pages:
        for line in page.lines:
            text = line.content.strip()
            for pattern in page_number_patterns:
                match = pattern.search(text)
                if match:
                    page_numbers[page.page_number] = {
                        "printed_number": int(match.group(1)),
                        "content": line.content,
                        "spans": [span.to_dict() for span in line.spans],
                        "bounding_regions": [BoundingRegion(polygon=line.polygon, page_number=page.page_number).to_dict()]
                        }
                    break  # Assuming the page number is unique per page and stopping after finding it
            if page.page_number in page_numbers:
                break

    return page_numbers
    

def get_color_spans(color_styles):
    # Extract the spans of text for each color
    color_spans = {}
    for font_color, styles in color_styles.items():
        if filter_blue_colors(font_color):
            color_spans[font_color] = get_styled_text(styles)
    return color_spans

def get_hands_written_spans(hands_written_styles):
    # Extract the spans of text for each handwriting style
    hands_written_spans = {}
    for is_hands_written, styles in hands_written_styles.items():
        if is_hands_written:
            hands_written_spans[is_hands_written] = get_styled_text(styles)
    return hands_written_spans   

def has_intersection(
    cells: List[Dict[str, int]], 
    spans_dict: Dict[str, List[Dict[str, int]]]
    ) -> bool:
    """
    Checks if there is any intersection between a list of cells and a dictionary of spans.
    Args:
        cells: 
        A list of dictionaries where each dictionary represents a cell with the following keys:
        - 'offset' (int): The starting position of the cell.
        - 'length' (int): The length of the cell.
        spans_dict: 
        A dictionary where keys are span types and values are lists of dictionaries. 
        Each dictionary in the list represents a span.
    Returns:
        bool: True if there is any intersection between any cell and any span, False otherwise.
    """
    if not cells:
        return False
    for cell in cells:
        cell_offset = cell["offset"]
        cell_length = cell["length"]
        cell_end = cell_offset + cell_length
        for _, spans in spans_dict.items():
            for span in spans:
                span_offset = span["offset"]
                span_length = span["length"]
                span_end = span_offset + span_length
                
                # Check if there is an intersection
                if not (cell_end <= span_offset or cell_offset >= span_end):
                    return True
    return False

def identify_author_and_philips(signature_table: dict) -> tuple:
    """
    Identifies the earliest date for an author and the latest date for a Philips representative from a signature table.

    Args:
        signature_table (dict): A dictionary where keys are person IDs and values 
        are dictionaries containing person details, including their role and date information.

    Returns:
        tuple: A tuple containing four elements:
            - author_cell (dict or None): The dictionary containing details of the author with the earliest date.
            - author_date (str): The earliest date associated with an author, formatted as a string. 
                                    Returns an empty string if no author is found.
            - philips_cell (dict or None): The dictionary containing details of the Philips representative with the latest date.
                                            Returns None if no Philips representative is found.
            - philips_date (str): The latest date associated with a Philips representative, formatted as a string. 
                                    Returns an empty string if no Philips representative is found.
    """
    author_cell, author_date = None, ""
    philips_cell, philips_date = None, ""
    for person in signature_table["persons"]:
        if person.get("role", "").find("author") >= 0:
            if not author_cell:
                author_cell = person
            formatted_date = format_date(person["date"]["content"])
            if formatted_date and ((not author_date) or (author_date > formatted_date)):
                author_cell = person
                author_date = formatted_date
        if person.get("role", "").find("philips") >= 0:
            if not philips_cell:
                philips_cell = person
            formatted_date = format_date(person["date"]["content"])
            if formatted_date and ((not philips_date) or (philips_date < formatted_date)):
                philips_cell= person
                philips_date = formatted_date
    return author_cell, author_date, philips_cell, philips_date