from doc_verifier.plot_utils import extract_specific_message_from_log

def test_valid_log_line():
    log_line = '[INFO] [2023-10-01 12:00:00] [module] : {"file_name": "test.pdf", "error_type": "missing_text", "page_number": 1, "content": "Some content", "bounding_regions": []}'
    expected_output = {
        "file_name": "test.pdf",
        "error_type": "missing_text",
        "page_number": 1,
        "content": "Some content",
        "bounding_regions": []
    }
    assert extract_specific_message_from_log(log_line) == expected_output

def test_invalid_json_log_line():
    log_line = '[INFO] [2023-10-01 12:00:00] [module] : {"file_name": "test.pdf", "error_type": "missing_text", "page_number": 1, "content": "Some content", "bounding_regions": '
    assert extract_specific_message_from_log(log_line) is None

def test_missing_required_fields():
    log_line = '[INFO] [2023-10-01 12:00:00] [module] : {"file_name": "test.pdf", "error_type": "missing_text", "page_number": 1, "content": "Some content"}'
    assert extract_specific_message_from_log(log_line) is None