# flo2-calc as an image: the shape flo2's helper sandbox (ops/flo2-tool-sandbox)
# runs one container of per person and design, and also a plain way to run it
# anywhere with Docker. Nothing in it needs flo2: it is the same server the
# plugin starts.
#   docker build -t flo2-calc .
#   docker run --rm -i --network none --read-only --user 65534:65534 flo2-calc
#
# PINNED, IN ONE PLACE. The image installs this package and nothing else, so
# the set it runs is exactly pyproject.toml's.
#
# TWO STAGES. The build stage has pip and the build backend; the image gets
# only the finished environment, copied to the same path on the same base.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN python -m venv /opt/flo2-calc \
 && /opt/flo2-calc/bin/pip install --no-cache-dir --disable-pip-version-check . \
 && /opt/flo2-calc/bin/pip freeze --all

# The image does nothing to confine itself. flo2-tool-sandbox runs it with no
# network, a read-only root, an unprivileged user (65534), a memory cap, and
# only the design's folder mounted, read-only, at /design. So nothing here may
# need the network or a writable root at run time: HOME is /tmp (a tmpfs or
# nothing), no bytecode is written, and no --root is given, so flo2-calc
# writes no file: every record comes back inside its reply.
FROM python:3.12-slim
COPY --from=build /opt/flo2-calc /opt/flo2-calc
ENV PATH=/opt/flo2-calc/bin:$PATH HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN flo2-calc --version
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["flo2-calc"]
