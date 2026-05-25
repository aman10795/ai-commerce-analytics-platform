import os
import json
import glob
import fitz  # PyMuPDF

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


INPUT_PATTERN = "data/invoices/*.pdf"
PROMPT_PATH = "prompts/invoice_schema_discovery_2.txt"
OUTPUT_FOLDER = "outputs"


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


def extract_invoice_data(invoice_text):
    prompt_template = load_prompt_template(PROMPT_PATH)

    prompt = prompt_template.format(
        invoice_text=invoice_text
    )

    print("Prompt preview:", flush=True)
    print(prompt[:500], flush=True)

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        temperature=0,
    )

    return response.output_text


def save_extraction_output(extracted_data, output_path):
    cleaned_data = extracted_data.strip()

    if cleaned_data.startswith("```json"):
        cleaned_data = cleaned_data.removeprefix("```json").strip()

    if cleaned_data.startswith("```"):
        cleaned_data = cleaned_data.removeprefix("```").strip()

    if cleaned_data.endswith("```"):
        cleaned_data = cleaned_data.removesuffix("```").strip()

    try:
        parsed_json = json.loads(cleaned_data)
    except json.JSONDecodeError:
        debug_path = "outputs/debug_raw_openai_response.txt"

        with open(debug_path, "w", encoding="utf-8") as file:
            file.write(extracted_data)

        raise ValueError(
            f"OpenAI response was not valid JSON. Raw response saved to {debug_path}"
        )

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(parsed_json, file, indent=2, ensure_ascii=False)


def process_single_pdf(pdf_path):
    pdf_filename = os.path.basename(pdf_path)
    pdf_stem = os.path.splitext(pdf_filename)[0]
    output_path = os.path.join(OUTPUT_FOLDER, f"{pdf_stem}_extraction.json")

    print("-" * 60, flush=True)
    print(f"Processing PDF: {pdf_filename}", flush=True)

    print("Reading PDF...", flush=True)
    invoice_text = extract_transaction_text_from_pdf(pdf_path)

    print("PDF text extracted successfully.", flush=True)
    print(f"Extracted text length: {len(invoice_text)} characters", flush=True)

    print("Sending request to OpenAI...", flush=True)
    extracted_data = extract_invoice_data(invoice_text)

    print("OpenAI response received.", flush=True)

    print("Saving JSON output...", flush=True)
    save_extraction_output(extracted_data, output_path)

    print("Extraction complete.", flush=True)
    print(f"Saved to: {output_path}", flush=True)


def main():
    print("Starting batch invoice extraction pipeline...", flush=True)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    pdf_files = glob.glob(INPUT_PATTERN)

    if not pdf_files:
        print("No PDF files found in data/invoices/", flush=True)
        return

    print(f"Found {len(pdf_files)} PDF file(s).", flush=True)

    for pdf_path in pdf_files:
        process_single_pdf(pdf_path)

    print("-" * 60, flush=True)
    print("Batch extraction complete.", flush=True)


if __name__ == "__main__":
    main()