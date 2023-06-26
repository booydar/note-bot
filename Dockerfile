FROM python:3.9.7

# set a directory for the app
WORKDIR /app

# copy all the files to the container
COPY . /app/

# install dependencies
RUN apt-get update -y
RUN apt-get install -y ffmpeg

RUN pip install --no-cache-dir -r requirements.txt
RUN python -m nltk.downloader punkt

CMD ["python", "./bot.py"]