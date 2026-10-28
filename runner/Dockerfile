# Optional container runner. Build once BEFORE the demo:
#   docker build -t snipforge-runner:1 -f runner/Dockerfile .
# SnipForge auto-detects the image; runner.py adds --network none, --read-only, --cap-drop ALL,
# no-new-privileges, an unprivileged user, memory/CPU/PID limits and a small tmpfs at run time.
FROM python:3.12-slim
COPY snipforge/harness.py /harness/harness.py
USER 65534:65534
WORKDIR /tmp
