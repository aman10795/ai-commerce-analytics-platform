import os
import json
import glob
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import fitz
from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

INPUT_PATTERN = "data/invoices/*.pdf"
PROMPT_PATH = "prompts/invoice_schema_discovery_2.txt"

RAW_JSON_FOLDER = Path("data/raw_json/ai_extractions")

AI_ARTIFACTS_FOLDER = Path("artifacts/ai_extraction")
FAILED_FOLDER = AI_ARTIFACTS_FOLDER / "failed"
DEBUG_FOLDER = AI_ARTIFACTS_FOLDER / "debug"
LOG_FOLDER = AI_ARTIFACTS_FOLDER / "logs"

MODEL_NAME = "gpt-4.1-mini"
MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 5


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def file_hash(file_path):
    with open(file_path, "rb") as file:
        return hashlib.sha256(file.read()).hexdigest()


def extract_transaction_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    transaction_text = ""

    stop_markers = [
        "I. General Terms",
        "II. Terms of Wolt Services",
        "III. Terms of Purchase",
        "General Terms",
        "Terms of Service",
        "Right of revocation",
    ]

    for page in doc:
        page_text = page.get_text()

        for marker in stop_markers:
            if marker in page_text:
                page_text = page_text.split(marker)[0]
                transaction_text += page_text
                return transaction_text.strip()

        transaction_text += page_text + "\n"

    return transaction_text.strip()


def load_prompt_template(prompt_path):
    with open(prompt_path, "r", encoding="utf-8") as file:
        return file.read()


def call_openai_with_retry(prompt):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"OpenAI request attempt {attempt}/{MAX_RETRIES}", flush=True)

            response = client.responses.create(
                model=MODEL_NAME,
                input=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                temperature=0,
            )

            return response.output_text

        except (APIConnectionError, RateLimitError, APIStatusError) as error:
            print(f"OpenAI request failed: {type(error).__name__}", flush=True)

            if attempt == MAX_RETRIES:
                raise

            time.sleep(RETRY_SLEEP_SECONDS * attempt)

    raise RuntimeError("OpenAI request failed after retries.")


def clean_openai_json_response(extracted_data):
    cleaned_data = extracted_data.strip()

    if cleaned_data.startswith("```json"):
        cleaned_data = cleaned_data.removeprefix("```json").strip()

    if cleaned_data.startswith("```"):
        cleaned_data = cleaned_data.removeprefix("```").strip()

    if cleaned_data.endswith("```"):
        cleaned_data = cleaned_data.removesuffix("```").strip()

    return cleaned_data


def save_json(data, output_path):
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def find_existing_extraction_by_hash(current_pdf_hash):
    for extraction_file in RAW_JSON_FOLDER.glob("*.json"):
        try:
            with open(extraction_file, "r", encoding="utf-8") as file:
                existing_data = json.load(file)

            existing_hash = (
                existing_data
                .get("_pipeline_metadata", {})
                .get("pdf_hash")
            )

            if existing_hash == current_pdf_hash:
                return extraction_file

        except Exception:
            continue

    return None


def main():
    print("Starting batch invoice extraction pipeline...", flush=True)

    RAW_JSON_FOLDER.mkdir(parents=True, exist_ok=True)
    FAILED_FOLDER.mkdir(parents=True, exist_ok=True)
    DEBUG_FOLDER.mkdir(parents=True, exist_ok=True)
    LOG_FOLDER.mkdir(parents=True, exist_ok=True)

    prompt_template = load_prompt_template(PROMPT_PATH)

    pdf_files = sorted(glob.glob(INPUT_PATTERN))

    if not pdf_files:
        print("No PDF files found in data/invoices/", flush=True)
        return

    print(f"Found {len(pdf_files)} PDF file(s).", flush=True)

    run_log = []

    for pdf_path in pdf_files:
        pdf_path = Path(pdf_path)
        pdf_filename = pdf_path.name
        pdf_stem = pdf_path.stem

        output_path = RAW_JSON_FOLDER / f"{pdf_stem}_extraction.json"
        failed_path = FAILED_FOLDER / f"{pdf_stem}_failed.json"

        started_at = now_utc()
        current_pdf_hash = file_hash(pdf_path)

        print("-" * 60, flush=True)
        print(f"Processing PDF: {pdf_filename}", flush=True)

        existing_extraction = find_existing_extraction_by_hash(current_pdf_hash)

        if existing_extraction:
            print(
                f"Skipping {pdf_filename}: identical document already processed.",
                flush=True,
            )

            skip_metadata = {
                "pdf_file_name": pdf_filename,
                "pdf_path": str(pdf_path),
                "pdf_hash": current_pdf_hash,
                "status": "skipped_duplicate_hash",
                "matched_output_file": str(existing_extraction),
                "skipped_at": now_utc(),
            }

            run_log.append(skip_metadata)
            continue

        metadata = {
            "pdf_file_name": pdf_filename,
            "pdf_stem": pdf_stem,
            "pdf_path": str(pdf_path),
            "pdf_hash": current_pdf_hash,
            "model_name": MODEL_NAME,
            "prompt_path": PROMPT_PATH,
            "started_at": started_at,
            "completed_at": None,
            "status": "started",
        }

        try:
            print("Reading PDF...", flush=True)
            invoice_text = extract_transaction_text_from_pdf(pdf_path)

            if not invoice_text:
                raise ValueError("Extracted PDF text is empty.")

            print("PDF text extracted successfully.", flush=True)
            print(f"Extracted text length: {len(invoice_text)} characters", flush=True)

            prompt = prompt_template.format(invoice_text=invoice_text)

            print(f"Final prompt length: {len(prompt)} characters", flush=True)
            print("Sending request to OpenAI...", flush=True)

            extracted_data = call_openai_with_retry(prompt)

            print("OpenAI response received.", flush=True)

            cleaned_data = clean_openai_json_response(extracted_data)

            try:
                parsed_json = json.loads(cleaned_data)
            except json.JSONDecodeError:
                debug_path = DEBUG_FOLDER / f"{pdf_stem}_raw_openai_response.txt"

                with open(debug_path, "w", encoding="utf-8") as file:
                    file.write(extracted_data)

                raise ValueError(
                    f"OpenAI response was not valid JSON. Saved to {debug_path}"
                )

            metadata["completed_at"] = now_utc()
            metadata["status"] = "success"

            parsed_json["_pipeline_metadata"] = metadata

            print("Saving raw AI JSON output...", flush=True)
            save_json(parsed_json, output_path)

            print("Extraction complete.", flush=True)
            print(f"Saved to: {output_path}", flush=True)

            run_log.append(metadata)

        except Exception as error:
            metadata["completed_at"] = now_utc()
            metadata["status"] = "failed"
            metadata["error_type"] = type(error).__name__
            metadata["error_message"] = str(error)

            save_json(metadata, failed_path)

            print(f"FAILED: {pdf_filename}", flush=True)
            print(f"Error: {type(error).__name__}: {error}", flush=True)
            print(f"Failure metadata saved to: {failed_path}", flush=True)

            run_log.append(metadata)

    log_path = LOG_FOLDER / f"batch_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_json(run_log, log_path)

    print("-" * 60, flush=True)
    print("Batch extraction complete.", flush=True)
    print(f"Batch log saved to: {log_path}", flush=True)


if __name__ == "__main__":
    main()