# Built from the REPO ROOT so the backend modules are included:
#   docker build -t notebot-nc -f nc-talk/Dockerfile .
# Dependencies are installed before the code is copied, so editing the bot only
# rebuilds the final (fast) layer instead of reinstalling torch every time.
FROM python:3.11-slim-bookworm
WORKDIR /app

RUN apt-get update -y && apt-get install -y --no-install-recommends ffmpeg wget curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install torch==2.0.1+cpu torchvision==0.15.2+cpu torchaudio==2.0.2+cpu \
    -f https://download.pytorch.org/whl/torch_stable.html
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m nltk.downloader punkt

COPY . /app/

CMD ["python", "-u", "nc-talk/app.py"]
