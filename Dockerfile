FROM python:3.11-slim-bookworm

# set a directory for the app
WORKDIR /app

# copy all the files to the container
COPY . /app/

# install dependencies
RUN apt-get update -y
RUN apt-get install -y ffmpeg wget curl

# RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
# RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
# RUN pip install torch torchvision torchaudio
RUN pip install torch==2.0.1+cpu torchvision==0.15.2+cpu torchaudio==2.0.2+cpu -f https://download.pytorch.org/whl/torch_stable.html
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m nltk.downloader punkt

CMD ["python", "-u", "./bot.py"]