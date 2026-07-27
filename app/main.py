"""HTTP layer.

Two endpoints do the work: one label, or many. Batch is not a loop over the
single endpoint; it fans out concurrently, because the whole point of Sarah
Chen's 300 label import is that agents should not wait 300 times in series.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.comparison.engine import compare, overall_verdict
from app.config import (
    ALLOWED_MEDIA_TYPES,
    MAX_BATCH_SIZE,
    MAX_CONCURRENCY,
    MAX_UPLOAD_BYTES,
    get_extractor,
    using_live_model,
)
from app.extraction.base import ExtractionError
from app.extraction.mock_extractor import MockExtractor
from app.schemas import (
    ApplicationData,
    BatchResult,
    ExtractedLabel,
    VerificationResult,
    Verdict,
)

STATIC_DIR = Path(__file__).parent / "static"
SAMPLES_DIR = Path(__file__).parent.parent / "samples"

app = FastAPI(
    title="TTB Label Verification",
    description="Prototype: compares alcohol beverage label artwork against COLA application data.",
    version="1.0.0",
)


def _parse_application(raw: str) -> ApplicationData:
    try:
        return ApplicationData(**json.loads(raw))
    except json.JSONDecodeError:
        raise HTTPException(400, "The application data was not valid JSON.")
    except ValidationError as exc:
        missing = ", ".join(str(e["loc"][0]) for e in exc.errors())
        raise HTTPException(400, f"The application data is missing or malformed: {missing}.")


def _validate_upload(file: UploadFile, contents: bytes) -> None:
    if not contents:
        raise HTTPException(400, f"{file.filename} is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{file.filename} exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    if file.content_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(415, f"{file.filename} is a {file.content_type} file. Upload a JPEG, PNG or WebP image.")


async def _verify_one(
    filename: str, contents: bytes, media_type: str, application: ApplicationData
) -> VerificationResult:
    """Extract, compare, and time both stages separately.

    The two timings are reported to the interface because they fail for different
    reasons: extraction is network-bound and variable, comparison is local and
    should stay in single-digit milliseconds.
    """
    extractor = get_extractor()
    started = time.perf_counter()

    try:
        if isinstance(extractor, MockExtractor):
            extracted = await extractor.extract_named(filename)
        else:
            extracted = await extractor.extract(contents, media_type)
    except ExtractionError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return VerificationResult(
            filename=filename, overall=Verdict.REVIEW, checks=[],
            extraction_ms=elapsed, comparison_ms=0, total_ms=elapsed,
            model=extractor.name, error=str(exc),
        )
    except Exception:
        elapsed = int((time.perf_counter() - started) * 1000)
        return VerificationResult(
            filename=filename, overall=Verdict.REVIEW, checks=[],
            extraction_ms=elapsed, comparison_ms=0, total_ms=elapsed,
            model=extractor.name,
            error="This label could not be read. Try a clearer image, or review it manually.",
        )

    extraction_ms = int((time.perf_counter() - started) * 1000)

    compare_started = time.perf_counter()
    checks = compare(application, extracted)
    comparison_ms = int((time.perf_counter() - compare_started) * 1000)

    return VerificationResult(
        filename=filename,
        overall=overall_verdict(checks),
        checks=checks,
        extraction_ms=extraction_ms,
        comparison_ms=comparison_ms,
        total_ms=int((time.perf_counter() - started) * 1000),
        model=extractor.name,
        legibility_notes=extracted.legibility_notes,
    )


@app.post("/api/verify", response_model=VerificationResult)
async def verify(file: UploadFile = File(...), application: str = Form(...)):
    """Verify a single label against one application record."""
    contents = await file.read()
    _validate_upload(file, contents)
    return await _verify_one(
        file.filename or "label", contents, file.content_type or "image/jpeg",
        _parse_application(application),
    )


@app.post("/api/verify-batch", response_model=BatchResult)
async def verify_batch(
    files: list[UploadFile] = File(...), applications: str = Form(...)
):
    """Verify many labels at once.

    `applications` is a JSON array; each entry carries a `filename` key that ties
    it to one of the uploaded images. Files without a matching record are
    reported rather than silently skipped, because a silently dropped label in a
    300 item import is exactly the failure an agent would never catch.
    """
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(413, f"Batches are limited to {MAX_BATCH_SIZE} labels. You uploaded {len(files)}.")

    try:
        records = json.loads(applications)
    except json.JSONDecodeError:
        raise HTTPException(400, "The application data was not valid JSON.")
    if not isinstance(records, list):
        raise HTTPException(400, "Batch application data must be a JSON array.")

    by_filename = {r.get("filename"): r for r in records if isinstance(r, dict)}

    started = time.perf_counter()
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def run(file: UploadFile) -> VerificationResult:
        contents = await file.read()
        name = file.filename or "label"
        record = by_filename.get(name)
        if record is None:
            return VerificationResult(
                filename=name, overall=Verdict.REVIEW, checks=[],
                extraction_ms=0, comparison_ms=0, total_ms=0,
                model=get_extractor().name,
                error="No application record was provided for this file.",
            )
        try:
            _validate_upload(file, contents)
        except HTTPException as exc:
            return VerificationResult(
                filename=name, overall=Verdict.REVIEW, checks=[],
                extraction_ms=0, comparison_ms=0, total_ms=0,
                model=get_extractor().name, error=exc.detail,
            )
        async with semaphore:
            return await _verify_one(
                name, contents, file.content_type or "image/jpeg",
                ApplicationData(**{k: v for k, v in record.items() if k != "filename"}),
            )

    results = await asyncio.gather(*(run(f) for f in files))

    counts = {v.value: 0 for v in Verdict}
    for result in results:
        counts[result.overall.value] += 1

    return BatchResult(
        results=list(results),
        total_ms=int((time.perf_counter() - started) * 1000),
        counts=counts,
    )


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "extractor": get_extractor().name,
        "live_model": using_live_model(),
    }


@app.get("/api/sample-applications")
async def sample_applications():
    """Sample COLA records so the interface can be exercised without typing."""
    path = SAMPLES_DIR / "applications.json"
    if not path.exists():
        return JSONResponse([], status_code=200)
    return JSONResponse(json.loads(path.read_text()))


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
