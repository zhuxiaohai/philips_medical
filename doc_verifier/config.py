import os

MIN_PAGES = 1

MAX_PAGES = 3

if "LOG_PATH" in os.environ:
    LOG_PATH = os.environ["LOG_PATH"]
else:
    LOG_PATH = "logs"
    
if "IMAGE_PATH" in os.environ:
    IMAGE_PATH = os.environ["IMAGE_PATH"]
else:
    IMAGE_PATH = "images"
    
if "DATA_PATH" in os.environ:
    DATA_PATH = os.environ["DATA_PATH"]
else:
    DATA_PATH = "data"
    
if "SERVER_API" in os.environ:
    SERVER_API = os.environ["SERVER_API"]
else:
    SERVER_API = "http://43.133.190.145"
    
if "PORT" in os.environ:
    PORT = os.environ["PORT"]
else:
    PORT = 4501