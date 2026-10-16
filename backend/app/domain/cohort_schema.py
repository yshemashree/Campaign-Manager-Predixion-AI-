"""Cohort CSV validation, driven by the agent's variable definitions.

Each agent declares the variables it needs, for example:
    {"name": "customer_name", "type": "string", "required": true, "example": "Priya"}
    {"name": "emi_amount", "type": "number", "required": true, "example": "4500"}
    {"name": "plan", "type": "enum", "required": false, "allowed": ["basic", "gold"]}

The CSV must have a `phone_number` column, may have a `lead_id` column, and one column per
variable. Rows are checked one at a time, so memory stays flat for large files.
"""

import csv
import io
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import phonenumbers

PHONE_COLUMN = "phone_number"
LEAD_COLUMN = "lead_id"
RESERVED_COLUMNS = (PHONE_COLUMN, LEAD_COLUMN)
VARIABLE_TYPES = ("string", "number", "integer", "boolean", "date", "enum")
VARIABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
MAX_VALUE_LENGTH = 1000
TRUE_VALUES = {"true", "yes", "y", "1"}
FALSE_VALUES = {"false", "no", "n", "0"}


@dataclass(frozen=True)
class Variable:
    name: str
    type: str = "string"
    required: bool = True
    example: str = ""
    allowed: tuple[str, ...] = ()
    max_length: int = MAX_VALUE_LENGTH

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Variable":
        return cls(
            name=data["name"],
            type=data.get("type", "string"),
            required=bool(data.get("required", True)),
            example=str(data.get("example", "") or ""),
            allowed=tuple(str(a) for a in data.get("allowed") or ()),
            max_length=int(data.get("max_length") or MAX_VALUE_LENGTH),
        )


@dataclass
class RowError:
    row: int  # 1-based data row number (header excluded)
    column: str
    message: str


@dataclass
class ValidRow:
    row: int
    phone_e164: str
    lead_id: str | None
    variables: dict[str, str]


@dataclass
class ValidationResult:
    header_errors: list[str] = field(default_factory=list)
    valid_rows: list[ValidRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    rejected_rows: list[tuple[int, dict[str, str], str]] = field(default_factory=list)
    duplicates_in_file: int = 0
    rows_total: int = 0
    header: list[str] = field(default_factory=list)


def sample_csv(variables: Iterable[Variable]) -> str:
    """Header + one example row, generated from the agent's variables."""
    variables = list(variables)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([PHONE_COLUMN, LEAD_COLUMN, *[v.name for v in variables]])
    writer.writerow(["+919876543210", "lead-001", *[_example(v) for v in variables]])
    return buf.getvalue()


def _example(v: Variable) -> str:
    if v.example:
        return v.example
    return {
        "number": "4500.50",
        "integer": "3",
        "boolean": "true",
        "date": "2026-11-05",
        "enum": v.allowed[0] if v.allowed else "",
    }.get(v.type, f"sample {v.name}")


def normalise_phone(raw: str, default_region: str) -> str | None:
    """E.164 (+919876543210) if the number is valid, else None."""
    try:
        parsed = phonenumbers.parse(raw.strip(), default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _check_value(v: Variable, value: str) -> str | None:
    """Error message, or None if the value is fine."""
    if len(value) > v.max_length:
        return f"longer than {v.max_length} characters"
    if v.type == "number":
        try:
            float(value)
        except ValueError:
            return "must be a number"
    elif v.type == "integer":
        if not re.fullmatch(r"[+-]?\d+", value):
            return "must be a whole number"
    elif v.type == "boolean":
        if value.lower() not in TRUE_VALUES | FALSE_VALUES:
            return "must be true or false"
    elif v.type == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            return "must be a date like 2026-11-05"
    elif v.type == "enum" and v.allowed and value not in v.allowed:
        return f"must be one of: {', '.join(v.allowed)}"
    return None


def iter_csv_rows(text_stream: Iterable[str]) -> Iterator[list[str]]:
    yield from csv.reader(text_stream)


def validate(
    lines: Iterable[str],
    variables: list[Variable],
    *,
    default_region: str,
    max_rows: int,
) -> ValidationResult:
    result = ValidationResult()
    reader = csv.reader(lines)
    try:
        raw_header = next(reader)
    except StopIteration:
        result.header_errors.append("The file is empty")
        return result
    header = [h.strip().lstrip("﻿").strip() for h in raw_header]

    result.header = header
    duplicates = sorted(h for h, n in Counter(header).items() if n > 1)
    if duplicates:
        result.header_errors.append(f"Duplicate columns: {', '.join(duplicates)}")
    if PHONE_COLUMN not in header:
        result.header_errors.append(f"Missing required column: {PHONE_COLUMN}")
    known = {v.name for v in variables} | set(RESERVED_COLUMNS)
    missing = [v.name for v in variables if v.required and v.name not in header]
    if missing:
        result.header_errors.append(f"Missing required variable columns: {', '.join(missing)}")
    unknown = [h for h in header if h and h not in known]
    if unknown:
        result.header_errors.append(
            f"Unknown columns (not variables of this agent): {', '.join(unknown)}"
        )
    if result.header_errors:
        return result

    index = {name: i for i, name in enumerate(header)}
    phones_seen: set[str] = set()
    for row_no, cells in enumerate(reader, start=1):
        if not any(c.strip() for c in cells):
            continue  # skip blank lines
        result.rows_total += 1
        if result.rows_total > max_rows:
            result.header_errors.append(f"Too many rows: the limit is {max_rows}")
            return result
        record = {name: (cells[i].strip() if i < len(cells) else "") for name, i in index.items()}
        row_errors: list[RowError] = []

        phone = normalise_phone(record.get(PHONE_COLUMN, ""), default_region)
        if phone is None:
            row_errors.append(RowError(row_no, PHONE_COLUMN, "not a valid phone number"))

        values: dict[str, str] = {}
        for v in variables:
            value = record.get(v.name, "")
            if not value:
                if v.required:
                    row_errors.append(RowError(row_no, v.name, "is required"))
                continue
            problem = _check_value(v, value)
            if problem:
                row_errors.append(RowError(row_no, v.name, problem))
            else:
                values[v.name] = value

        if not row_errors and phone is not None:
            if phone in phones_seen:
                result.duplicates_in_file += 1
                row_errors.append(RowError(row_no, PHONE_COLUMN, "duplicate number in this file"))
            else:
                phones_seen.add(phone)

        if row_errors:
            result.errors.extend(row_errors)
            message = "; ".join(f"{e.column} {e.message}" for e in row_errors)
            result.rejected_rows.append((row_no, record, message))
        elif phone is not None:
            lead_id = record.get(LEAD_COLUMN) or None
            result.valid_rows.append(ValidRow(row_no, phone, lead_id, values))
    return result


def csv_safe(value: str) -> str:
    """Stop spreadsheet apps from treating a cell as a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def error_report_csv(header: list[str], rejected: list[tuple[int, dict[str, str], str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row", *header, "error"])
    for row_no, record, message in rejected:
        writer.writerow([row_no, *[csv_safe(record.get(h, "")) for h in header], message])
    return buf.getvalue()
