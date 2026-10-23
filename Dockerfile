FROM ubuntu:latest
LABEL authors="almas"

ENTRYPOINT ["top", "-b"]