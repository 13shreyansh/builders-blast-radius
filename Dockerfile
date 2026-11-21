FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS sources
COPY tools/build_source.py /build_source.py
RUN python -I /build_source.py --pinned /source.zip

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
WORKDIR /app
COPY --chmod=0444 selector.py scope.py dependencies.json.gz file_reads.json.gz import_lines.json.gz ./
COPY --from=sources --chmod=0444 /source.zip ./
ENTRYPOINT ["python", "-B", "/app/selector.py"]
