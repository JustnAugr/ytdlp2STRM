#build application in the /app directory
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# Omit development dependencies
ENV UV_NO_DEV=1 
# Disable Python downloads
ENV UV_PYTHON_DOWNLOADS=0

#needed for our python code
ENV AM_I_IN_A_DOCKER_CONTAINER=Yes
ENV UI_PORT=5000
ENV TZ="America/New_York"

WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project -vv

COPY . /app
RUN chmod +x ./entrypoint.sh
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

#Then, use a final image without uv
FROM python:3.13-slim-trixie

#install ffmpeg and gosu
RUN set -eux; \
    apt-get install --update -y ffmpeg gosu; \
    apt-get dist-clean; \
		gosu nobody true

# Copy the application from the builder
COPY --from=builder --chown=nonroot:nonroot /app /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

# Use `/app` as the working directory
WORKDIR /app

#call into our entrypoint
ENTRYPOINT ["./entrypoint.sh"]
