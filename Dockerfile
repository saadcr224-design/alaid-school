FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY public ./public
RUN useradd --create-home school && mkdir /data && chown school:school /data
USER school
ENV PORT=8000 DATABASE_PATH=/data/school.db COOKIE_SECURE=1
EXPOSE 8000
CMD ["python", "server.py"]
