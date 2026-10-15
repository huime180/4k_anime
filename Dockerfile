FROM python:3.11-slim
WORKDIR /app
COPY . /app
ENV PORT=8787 HOST=0.0.0.0
EXPOSE 8787
# 首次启动先同步一次表格，再拉起服务
CMD ["sh", "-c", "python3 src/sync_table.py || true; python3 src/build_config.py --base ${PUBLIC_BASE:-http://127.0.0.1:8787} || true; python3 src/server.py --host 0.0.0.0 --port ${PORT:-8787}"]
