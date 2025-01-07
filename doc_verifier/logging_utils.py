import json
import logging
import logging.config
import pathlib
from doc_verifier import config


class DocumentError:
    """
    A class to represent an error found in a document.

    Attributes:
    -----------
    file_name : str
        The name of the file where the error was found.
    content : str
        The content of the document where the error was found.
    page_number : int
        The page number where the error was found.
    bounding_regions : list of region objects
        The bounding region contains coordinates of the error in the document.
    error_type : str
        The type of error found in the document.

    Methods:
    --------
    __repr__():
        Returns a string representation of the DocumentError instance.
    """
    def __init__(self, file_name, content, page_number, bounding_regions, error_type):
        self.file_name = file_name
        self.content = content
        self.page_number = page_number
        self.bounding_regions = bounding_regions
        self.error_type = error_type

    def __repr__(self):
        return json.dumps(
            {
                "file_name": self.file_name,
                "error_type": self.error_type, 
                "page_number": self.page_number, 
                "content": self.content, 
                "bounding_regions": [region.to_dict() for region in self.bounding_regions]
            },
            ensure_ascii=False
        )
        

def setup_logging(fpath: str) -> dict:
    config_file = pathlib.Path(fpath)
    logging_config = None
    with open(config_file) as f:
        file_content = f.read()
        logging_config = json.loads(file_content.replace("{LOG_PATH}", config.LOG_PATH))
        logging.config.dictConfig(logging_config)

    logger = logging.getLogger("doc_verifier")
    logger.info('doc_verifier logging configured')
    return logging_config