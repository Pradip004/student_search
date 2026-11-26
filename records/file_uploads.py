import csv
import io
import json
import re
import shutil
from pathlib import PurePosixPath
from zipfile import BadZipFile, LargeZipFile, ZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from PIL import Image, UnidentifiedImageError
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError
import pytesseract
from pytesseract import TesseractError, TesseractNotFoundError


MAX_UPLOAD_SIZE = 5 * 1024 * 1024
MAX_RECORDS = 1000
MAX_PDF_PAGES = 100
MAX_IMAGE_PIXELS = 20_000_000
MAX_ARCHIVE_SIZE = 50 * 1024 * 1024

SUPPORTED_EXTENSIONS = {
    ".csv", ".xlsx", ".json", ".txt", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
}

FIELD_ALIASES = {
    "person_type": "person_type",
    "persontype": "person_type",
    "type": "person_type",
    "category": "person_type",
    "name": "name",
    "fullname": "name",
    "studentname": "name",
    "candidatename": "name",
    "email": "email",
    "emailaddress": "email",
    "phone": "phone",
    "phonenumber": "phone",
    "mobile": "phone",
    "mobilenumber": "phone",
    "department": "department",
    "dept": "department",
    "course": "course",
    "program": "course",
    "year": "year",
    "academicyear": "year",
    "designation": "designation",
    "title": "designation",
    "status": "status",
}

EMAIL_PATTERN = re.compile(
    r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+"
    r"(?:\.[a-z0-9-]+)+\b"
)


class UploadFileError(ValueError):
    pass


def parse_people_upload(uploaded_file):
    extension = _extension(uploaded_file.name)
    if extension not in SUPPORTED_EXTENSIONS:
        raise UploadFileError(
            "Unsupported file type. Use CSV, XLSX, JSON, TXT, DOCX, "
            "text-based PDF, PNG, JPG, JPEG, WEBP, BMP, or TIFF."
        )

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise UploadFileError("Files must be 5 MB or smaller.")

    data = uploaded_file.read(MAX_UPLOAD_SIZE + 1)
    if len(data) > MAX_UPLOAD_SIZE:
        raise UploadFileError("Files must be 5 MB or smaller.")
    if not data:
        raise UploadFileError("The uploaded file is empty.")

    if extension == ".csv":
        records = _parse_csv(data)
    elif extension == ".xlsx":
        records = _parse_xlsx(data)
    elif extension == ".json":
        records = _parse_json(data)
    elif extension == ".docx":
        records = _parse_docx(data)
    elif extension == ".pdf":
        records = _parse_pdf(data)
    elif extension == ".txt":
        records = _parse_text(_decode_text(data))
    else:
        records = _parse_image(data)

    if not records:
        raise UploadFileError(
            "No person records were found. Include a name or email, "
            "or use a table with a header row."
        )
    if len(records) > MAX_RECORDS:
        raise UploadFileError(
            f"Files may contain no more than {MAX_RECORDS} records."
        )
    return [_normalize_record(record) for record in records]


def _extension(filename):
    normalized_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return PurePosixPath(normalized_name).suffix.lower()


def _decode_text(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UploadFileError(
            "Text files must use UTF-8 encoding."
        ) from error


def _parse_csv(data):
    text = _decode_text(data)
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise UploadFileError("The CSV file needs a header row.")
        return _records_from_rows(reader.fieldnames, reader)
    except csv.Error as error:
        raise UploadFileError("The CSV file could not be read.") from error


def _parse_xlsx(data):
    _validate_archive_size(data)
    try:
        workbook = load_workbook(
            io.BytesIO(data), read_only=True, data_only=True
        )
        try:
            worksheet = workbook.active
            rows = worksheet.iter_rows(values_only=True)
            headers = next(rows, None)
            if not headers:
                raise UploadFileError("The Excel sheet is empty.")
            return _records_from_rows(headers, rows)
        finally:
            workbook.close()
    except UploadFileError:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError) as error:
        raise UploadFileError("The Excel file could not be read.") from error


def _parse_json(data):
    try:
        content = json.loads(_decode_text(data))
    except json.JSONDecodeError as error:
        raise UploadFileError("The JSON file is not valid JSON.") from error

    if isinstance(content, dict):
        content = content.get("people", content.get("records", [content]))
    if not isinstance(content, list) or not all(
        isinstance(record, dict) for record in content
    ):
        raise UploadFileError(
            "JSON must contain a person object, a list of people, "
            "or a 'people'/'records' list."
        )
    if len(content) > MAX_RECORDS:
        raise UploadFileError(
            f"Files may contain no more than {MAX_RECORDS} records."
        )
    return [_normalize_record(record) for record in content]


def _parse_docx(data):
    _validate_archive_size(data)
    try:
        document = Document(io.BytesIO(data))
    except (
        BadZipFile,
        PackageNotFoundError,
        XMLSyntaxError,
        KeyError,
        ValueError,
    ) as error:
        raise UploadFileError("The DOCX file could not be read.") from error

    records = []
    for table in document.tables:
        table_rows = [
            [cell.text for cell in row.cells]
            for row in table.rows
        ]
        if table_rows:
            for record in _records_from_rows(table_rows[0], table_rows[1:]):
                _append_record(records, record)

    text = "\n\n".join(paragraph.text for paragraph in document.paragraphs)
    for record in _parse_text(text):
            _append_record(records, record)
    return records


def _validate_archive_size(data):
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > 5000 or sum(
                item.file_size for item in archive.infolist()
            ) > MAX_ARCHIVE_SIZE:
                raise UploadFileError(
                    "This compressed document is too large to process."
                )
    except UploadFileError:
        raise
    except (BadZipFile, LargeZipFile, OSError) as error:
        raise UploadFileError("The compressed document could not be read.") from error


def _parse_pdf(data):
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if len(reader.pages) > MAX_PDF_PAGES:
            raise UploadFileError(
                f"PDF files may contain no more than {MAX_PDF_PAGES} pages."
            )
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except UploadFileError:
        raise
    except (
        FileNotDecryptedError,
        PdfReadError,
        OSError,
        ValueError,
    ) as error:
        raise UploadFileError("The PDF file could not be read.") from error

    if not text.strip():
        raise UploadFileError(
            "This PDF has no selectable text. For scanned documents, "
            "upload a PNG or JPG image for local OCR instead."
        )
    return _parse_text(text)


def _parse_image(data):
    if not shutil.which("tesseract"):
        raise UploadFileError(
            "Image OCR needs Tesseract installed and available on PATH. "
            "No external OCR service is used."
        )

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise UploadFileError(
                    "Images must be 20 megapixels or smaller."
                )
            text = pytesseract.image_to_string(image)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise UploadFileError("The image file could not be read.") from error
    except TesseractNotFoundError as error:
        raise UploadFileError(
            "Image OCR needs Tesseract installed and available on PATH."
        ) from error
    except TesseractError as error:
        raise UploadFileError("Tesseract could not read this image.") from error

    return _parse_text(text)


def _parse_text(text):
    records = _parse_text_table(text)
    if records:
        return records

    records = []
    current = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                _append_record(records, current)
                current = {}
            continue

        for segment in re.split(r"\s*[|;]\s*", line.strip()):
            match = re.match(r"^\s*([^:]{1,40})\s*:\s*(.*?)\s*$", segment)
            if not match:
                continue
            field = _canonical_field(match.group(1))
            if not field:
                continue
            if field == "name" and "name" in current:
                _append_record(records, current)
                current = {}
            current[field] = match.group(2).strip()

    if current:
        _append_record(records, current)
    if records:
        return records

    # Plain text name/email lists are useful for search; imports still require
    # the record type and name fields validated by PersonForm.
    for line in text.splitlines():
        value = line.strip().strip(" -*,;")
        if not value:
            continue
        emails = EMAIL_PATTERN.findall(value)
        if emails:
            record = {"email": emails[0]}
            name = EMAIL_PATTERN.sub("", value).strip(" -,:;<>")
            if name:
                record["name"] = name
            _append_record(records, record)
        else:
            _append_record(records, {"name": value})
    return records


def _parse_text_table(text):
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    for delimiter in ("\t", "|", ","):
        if delimiter not in lines[0]:
            continue
        try:
            rows = list(csv.reader(lines, delimiter=delimiter))
        except csv.Error:
            continue
        if rows and _has_person_header(rows[0]):
            return _records_from_rows(rows[0], rows[1:])
    return []


def _records_from_rows(headers, rows):
    headers = list(headers)
    canonical_headers = [_canonical_field(header) for header in headers]
    if not any(canonical_headers):
        raise UploadFileError(
            "No recognized headers found. Use name, email, person_type, "
            "phone, department, course, year, designation, or status."
        )

    records = []
    for row in rows:
        values = (
            [row.get(header) for header in headers]
            if isinstance(row, dict)
            else list(row)
        )
        record = {
            field: value
            for field, value in zip(canonical_headers, values)
            if field and value is not None
        }
        if any(str(value).strip() for value in record.values()):
            _append_record(records, record)
    return records


def _append_record(records, record):
    records.append(record)
    if len(records) > MAX_RECORDS:
        raise UploadFileError(
            f"Files may contain no more than {MAX_RECORDS} records."
        )


def _has_person_header(headers):
    return any(_canonical_field(header) for header in headers)


def _canonical_field(label):
    normalized = re.sub(r"[^a-z0-9]", "", str(label).strip().lower())
    return FIELD_ALIASES.get(normalized)


def _normalize_record(record):
    normalized = {}
    for key, value in record.items():
        field = _canonical_field(key)
        if not field or value is None:
            continue
        if field == "year" and isinstance(value, float) and value.is_integer():
            value = int(value)
        normalized[field] = str(value).strip()

    if "person_type" in normalized:
        normalized["person_type"] = normalized["person_type"].lower()
    if not normalized.get("status"):
        normalized["status"] = "active"
    return normalized
