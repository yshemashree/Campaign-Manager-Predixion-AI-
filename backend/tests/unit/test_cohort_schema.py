from app.domain.cohort_schema import (
    Variable,
    error_report_csv,
    normalise_phone,
    sample_csv,
    validate,
)

VARS = [
    Variable("customer_name"),
    Variable("emi_amount", type="number"),
    Variable("due_date", type="date", required=False),
    Variable("plan", type="enum", required=False, allowed=("basic", "gold")),
]


def check(text: str, max_rows: int = 100):  # type: ignore[no-untyped-def]
    return validate(text.splitlines(), VARS, default_region="IN", max_rows=max_rows)


def test_sample_csv_passes_its_own_validation() -> None:
    result = check(sample_csv(VARS))
    assert result.header_errors == [] and result.errors == []
    assert len(result.valid_rows) == 1


def test_phone_numbers_are_normalised() -> None:
    assert normalise_phone("98765 43210", "IN") == "+919876543210"
    assert normalise_phone("+91-98765-43210", "IN") == "+919876543210"
    assert normalise_phone("12345", "IN") is None
    assert normalise_phone("not a phone", "IN") is None


def test_row_errors_name_row_and_column() -> None:
    result = check(
        "phone_number,customer_name,emi_amount,due_date,plan\n"
        "9876543210,Priya,4500,2026-11-05,gold\n"
        "123,,abc,05/11/2026,platinum\n"
    )
    assert len(result.valid_rows) == 1
    got = {(e.row, e.column) for e in result.errors}
    assert got == {
        (2, "phone_number"),
        (2, "customer_name"),
        (2, "emi_amount"),
        (2, "due_date"),
        (2, "plan"),
    }


def test_duplicates_blank_lines_and_bom() -> None:
    result = check("﻿phone_number,customer_name,emi_amount\n9876543210,A,1\n\n+919876543210,B,2\n")
    assert result.header_errors == []
    assert result.rows_total == 2 and result.duplicates_in_file == 1


def test_header_problems() -> None:
    result = check("customer_name,customer_name,extra\n")
    joined = " | ".join(result.header_errors)
    assert "Duplicate columns" in joined
    assert "phone_number" in joined
    assert "emi_amount" in joined
    assert "extra" in joined
    assert check("").header_errors == ["The file is empty"]


def test_row_limit() -> None:
    rows = "\n".join(f"98765432{i:02d},A,1" for i in range(5))
    result = check("phone_number,customer_name,emi_amount\n" + rows, max_rows=3)
    assert any("Too many rows" in e for e in result.header_errors)


def test_error_report_defuses_formulas() -> None:
    report = error_report_csv(
        ["phone_number", "customer_name"],
        [(1, {"phone_number": '=HYPERLINK("x")', "customer_name": "@SUM(A1)"}, "bad")],
    )
    line = report.splitlines()[1]
    assert line.startswith("1,\"'=HYPERLINK") and ",'@SUM(A1)," in line
