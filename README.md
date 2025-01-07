# philips_medical

# start locally
1. Modify the env.sample to reflect your local environment, specifically:

IMAGE_PATH: path to store the processed images of pdf pages
DATA_PATH: path to store the data file (e.g. pdfs)
LOG_PATH: path for saving logs
SERVER_API: IP of the host machine
PORT: exposed port of the host machine

2. Rename env.sample to an .env file for loading in python environment

variables in *.env will be overwritten by the environment section of docker-compose.yml. Smartly design the relation!

3. Modify the host machine volumns in the volumns section of docker-compose.yml to reflect your host machine

4. Make an image by Dockerfile

docker build -t philips_medical:1.0 .

5. Start the service

cd [Project Root Dir]
docker-compose up -d

# product environment
SERVER_API=http://39.99.129.97
PORT=4503

upload pdf file:
```bash
curl -X 'POST' \  'http://39.99.129.97:4503/upload/?ranking=1' \  -H 'accept: application/json' \  -H 'Content-Type: multipart/form-data' \  -F 'file=@459801834582 Reflow Soldering OQ protocol.pdf;type=application/pdf'
```

verify pdf file:
```bash
curl -X 'POST' \  'http://39.99.129.97:4503/verify/' \  -H 'accept: application/json' \  -H 'Content-Type: application/json' \  -d '{  "query": [    {"file_path": "http://39.99.129.97:4503/data/459801834582 OQ report-Reflow soldering.pdf"}  ]}'
```