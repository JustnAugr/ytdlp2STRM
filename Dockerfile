FROM python:3.12.5
WORKDIR /opt/ytdlp2STRM
COPY . /opt/ytdlp2STRM

ENV AM_I_IN_A_DOCKER_CONTAINER Yes
ENV DOCKER_PORT 5005
ENV TZ="America/New_York"

# Actualizar el sistema e instalar ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean
RUN pip install --no-cache-dir --upgrade -r /opt/ytdlp2STRM/requierments.txt
# RUN pip install deno
# RUN pip install yt-dlp-ejs
CMD ["python", "main.py"]
EXPOSE 5000
