"""Gunicorn configuration for production (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 8
item 1). Not used in local development — `manage.py runserver` remains the dev workflow
(see docs/DEPLOY.md "本機常用指令").

Everything is read from the environment so this file doesn't need editing per
environment; deploy/systemd/mpts-gunicorn.service supplies the values via an
EnvironmentFile pointing at the real .env. Binding to a Unix socket rather than a TCP
port is deliberate: Gunicorn must never be reachable directly, only through Nginx, since
the reverse proxy is what turns a real client IP into a trustworthy X-Forwarded-For
header (see deploy/nginx/mpts.conf.example) and terminates TLS.
"""

import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "unix:/run/mpts/gunicorn.sock")
workers = int(os.environ.get("GUNICORN_WORKERS", str(multiprocessing.cpu_count() * 2 + 1)))
worker_class = "sync"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

# Restart each worker after a while to bound the effect of any slow memory leak (ReportLab/
# openpyxl/pypdf all build sizeable in-memory structures for large exports). Jitter avoids
# every worker recycling at the same moment.
max_requests = 1000
max_requests_jitter = 100

accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "-")
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
