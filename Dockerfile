FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS sources
COPY tools/build_source.py /build_source.py
RUN python -I /build_source.py --pinned /source.zip
COPY tools/build_import_archive.py /build_import_archive.py
RUN python -I /build_import_archive.py /source.zip /import-313.zip

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
WORKDIR /app
COPY --chmod=0444 selector.py scope.py import_guard.py class_changes.py shadowed.json.gz types.json.gz initialization.json.gz namespaces.json.gz edits.py dependencies.py cold_lines.json.gz class_usage.json.gz expressions.py equivalence.py operands.json.gz shared.json.gz dependencies.json.gz file_reads.json.gz import_lines.json.gz item_profiles.json.gz observers.txt ./
COPY --from=sources --chmod=0444 /source.zip /import-313.zip ./
ENTRYPOINT ["python", "-B", "/app/selector.py"]
