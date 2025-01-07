import os
import re
import json
import logging
import fitz
from PIL import Image, ImageDraw
from collections import deque

logger = logging.getLogger("doc_verifier")


def draw_bounding_boxes_on_pdf(pdf_path: str, bounding_regions: list, output_image_path: str, page_number: int):
    """
    Draw bounding boxes on the PDF page and save the result as an image.

    Args:
        pdf_path (str): The path to the PDF file.
        bounding_regions (list): A list of bounding boxes.
        output_image_path (str): The path to save the output image.
        page_number (int): The page number to draw bounding boxes on.
    """
    # Open the PDF file
    document = fitz.open(pdf_path)
    
    # Select the page
    page = document.load_page(page_number - 1)  # page_number is 1-based
    
    # Render the page to an image
    pix = page.get_pixmap()
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    # Draw the bounding boxes
    draw = ImageDraw.Draw(img)
    for idx, bbox in bounding_regions:
        x0 = bbox["polygon"][0]["x"]*72
        y0 = bbox["polygon"][0]["y"]*72
        x1 = bbox["polygon"][2]["x"]*72
        y1 = bbox["polygon"][2]["y"]*72
        draw.rectangle([x0, y0, x1, y1], outline="red", width=2)
        draw.text((x1 + 5, y0), str(idx), fill="red")
        
    # Save the image
    img.save(output_image_path)
    

def extract_specific_messages_from_log_file(log_file_path: str,
                                            start_marker: str = "Begin to analyze all files.",
                                            end_marker: str = "Complete analyzing all files."):
    """
    Extract the latest specific messages from a log file between start and end markers and store them in a list.

    Args:
        log_file_path (str): The path to the log file.
        start_marker (str): The marker indicating the start of the relevant log section.
        end_marker (str): The marker indicating the end of the relevant log section.

    Returns:
        list: A list of specific messages converted to Python objects.
    """

    buffer = deque()
    found_end_marker = False
    start_position = None
    end_position = None
    partial_line = b''

    with open(log_file_path, 'rb') as log_file:
        log_file.seek(0, 2)  # Move the cursor to the end of the file
        file_size = log_file.tell()
        block_size = 1024
        blocks = -1

        while file_size > 0:
            if file_size - block_size > 0:
                log_file.seek(blocks * block_size, 2)
                data = log_file.read(block_size)
            else:
                log_file.seek(0, 0)
                data = log_file.read(file_size)

            lines = data.split(b'\n')
            if partial_line:
                lines[-1] = lines[-1] + partial_line
                partial_line = b''

            if data and data[-1] != b'\n':
                partial_line = lines.pop()

            file_size -= block_size
            blocks -= 1

            for line in reversed(lines):
                if line.strip():
                    decoded_line = line.decode('utf-8')
                    if end_marker in decoded_line:
                        found_end_marker = True
                        end_position = log_file.tell() - len(data) + data.rfind(line) + len(line)
                    elif start_marker in decoded_line and found_end_marker:
                        start_position = log_file.tell() - len(data) + data.rfind(line)
                        break

            if start_position is not None and end_position is not None:
                break

    if start_position is not None and end_position is not None:
        with open(log_file_path, 'rb') as log_file:
            log_file.seek(start_position)
            data = log_file.read(end_position - start_position)
            lines = data.split(b'\n')

            for line in lines:
                if line.strip():
                    decoded_line = line.decode('utf-8')
                    if 'INFO' in decoded_line:
                        buffer.append(decoded_line)

    # Process the specific messages
    result_messages = []
    for line in buffer:
        message = extract_specific_message_from_log(line)
        if message:
            result_messages.append(message)

    return result_messages

def extract_specific_message_from_log(log_line: str):
    """
    Extract the specific message part from a log line and convert it to a Python object.

    Args:
        log_line (str): A single line from the log file.

    Returns:
        dict: The specific message part converted to a Python object, or None if it doesn't match the criteria.
    """
    # Define the regex pattern to extract the message part
    pattern = r'\[.*?\] \[INFO\] \[.*?\] : (.*)'
    match = re.search(pattern, log_line)
    if match:
        message_str = match.group(1)
        try:
            message_dict = json.loads(message_str)
            # Check if the message contains the specific fields
            required_fields = {"file_name", "error_type", "page_number", "content", "bounding_regions"}
            if required_fields.issubset(message_dict.keys()):
                return message_dict
            else:
                logger.error(f"Message does not contain all required fields: {message_dict}")
                return None
        except json.JSONDecodeError:
            # Skip messages that are not valid JSON
            return None
    else:
        return None
    
    
def clear_path(image_path: str):  
    """
    Clears the specified directory by deleting all files and subdirectories within it.
    If the directory does not exist, it creates the directory.
    Args:
        image_path (str): The path to the directory to be cleared.
    Raises:
        Exception: If an error occurs while deleting a file or directory, it logs the error with the reason.
    """
     
    if os.path.exists(image_path):
        for filename in os.listdir(image_path):
            file_path = os.path.join(image_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    for root, dirs, files in os.walk(file_path, topdown=False):
                        for name in files:
                            os.remove(os.path.join(root, name))
                        for name in dirs:
                            os.rmdir(os.path.join(root, name))
                    os.rmdir(file_path)
            except Exception as e:
                logger.error(f'Failed to delete {file_path}. Reason: {e}')
    else:
        os.makedirs(image_path)
