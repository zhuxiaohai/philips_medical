import os
from urllib.parse import urlparse
import asyncio
from azure.ai.formrecognizer.aio import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from doc_verifier.logging_utils import setup_logging
from doc_verifier.utils import is_url, get_filename_from_url
from doc_verifier import config
from doc_verifier.verifier import process_single_file



endpoint = os.getenv('AZURE_ENDPOINT', 'default_value')
key = os.getenv('AZURE_KEY', 'default_value')
min_pages = config.MIN_PAGES
max_pages = 3
document_analysis_client = DocumentAnalysisClient(
    endpoint=endpoint, credential=AzureKeyCredential(key)
)



async def verify(file_path):
    async for i in process_single_file(file_path, min_pages, max_pages):
        print(i)
file_path = "/home/ubuntu/data/CWE-PQ-023AWeldingPQReport_test2.pdf"  
asyncio.run(verify(file_path))