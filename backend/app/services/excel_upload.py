from __future__ import annotations

import hashlib
import io
import math
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_EXCEL_BYTES = 8 * 1024 * 1024
MAX_EXCEL_ROWS = 5_000

SHEET_SPECS: dict[str, tuple[str, ...]] = {
    "发电计量": ("GENERATION_DATA",),
    "新能源预测": ("RENEWABLE_FORECAST",),
    "售电履约": ("RETAIL_DATA",),
    "用户负荷曲线": ("USER_LOAD_CURVE",),
    "虚拟电厂资源": ("VPP_RESOURCE",),
    "调度安全边界": ("GRID_CONSTRAINT",),
    "结算关联场景": ("GENERATION_DATA", "RETAIL_DATA"),
    "隐私计算输入": ("RENEWABLE_FORECAST", "USER_LOAD_CURVE", "VPP_RESOURCE"),
    "审计追踪场景": (
        "GENERATION_DATA",
        "RENEWABLE_FORECAST",
        "RETAIL_DATA",
        "USER_LOAD_CURVE",
        "VPP_RESOURCE",
        "GRID_CONSTRAINT",
    ),
    "风险处置场景": (
        "GENERATION_DATA",
        "RENEWABLE_FORECAST",
        "RETAIL_DATA",
        "USER_LOAD_CURVE",
        "VPP_RESOURCE",
        "GRID_CONSTRAINT",
    ),
}

HEADER_ALIASES: dict[str, str] = {
    "序号": "row_no",
    "row_no": "row_no",
    "资产类型": "asset_type",
    "asset_type": "asset_type",
    "数据资产名称": "label",
    "数据资产": "label",
    "label": "label",
    "批次编号": "trade_batch_no",
    "trade_batch_no": "trade_batch_no",
    "数据期间": "period",
    "period": "period",
    "记录数": "record_count",
    "record_count": "record_count",
    "功能覆盖": "function_scope",
    "关联任务编号": "task_reference",
    "关联任务": "task_reference",
    "规则版本": "rule_version",
    "计算算法": "algorithm_code",
    "审计要求": "audit_requirement",
    "风险等级": "risk_level",
    "预期处置": "expected_action",
    "建议上传角色": "recommended_role",
    "示例标记": "sample_marker",
    "来源类型": "source_type",
    "传输协议": "protocol",
    "加密方式": "encryption",
    "可信采集证明": "attestation",
    "电量MWh": "energy_mwh",
    "电量（MWh）": "energy_mwh",
    "energy_mwh": "energy_mwh",
    "预测电量MWh": "forecast_energy_mwh",
    "预测电量（MWh）": "forecast_energy_mwh",
    "forecast_energy_mwh": "forecast_energy_mwh",
    "预测准确率%": "forecast_accuracy_pct",
    "预测准确率（%）": "forecast_accuracy_pct",
    "forecast_accuracy_pct": "forecast_accuracy_pct",
    "可调容量MW": "adjustable_capacity_mw",
    "可调容量（MW）": "adjustable_capacity_mw",
    "adjustable_capacity_mw": "adjustable_capacity_mw",
    "储能电量MWh": "storage_energy_mwh",
    "储能电量（MWh）": "storage_energy_mwh",
    "storage_energy_mwh": "storage_energy_mwh",
    "响应时间分钟": "response_minutes",
    "响应时间（分钟）": "response_minutes",
    "response_minutes": "response_minutes",
    "N-1校核": "n_minus_one_passed",
    "N-1校核结果": "n_minus_one_passed",
    "n_minus_one_passed": "n_minus_one_passed",
    "剩余偏差上限MWh": "max_residual_imbalance_mwh",
    "剩余偏差上限（MWh）": "max_residual_imbalance_mwh",
    "max_residual_imbalance_mwh": "max_residual_imbalance_mwh",
    "拥塞裕度%": "congestion_margin_pct",
    "拥塞裕度（%）": "congestion_margin_pct",
    "congestion_margin_pct": "congestion_margin_pct",
}
for _hour in range(24):
    HEADER_ALIASES[f"负荷{_hour:02d}时"] = f"load_{_hour:02d}"
    HEADER_ALIASES[f"负荷{_hour}时"] = f"load_{_hour:02d}"
    HEADER_ALIASES[f"load_{_hour:02d}"] = f"load_{_hour:02d}"

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


class ExcelWorkbookError(ValueError):
    """Raised when an uploaded workbook cannot be read as the platform template."""


@dataclass(frozen=True)
class ParsedExcelRow:
    sheet_name: str
    row_number: int
    values: dict[str, Any]


@dataclass(frozen=True)
class ParsedExcelWorkbook:
    file_digest: str
    sheet_names: tuple[str, ...]
    sheet_row_counts: dict[str, int]
    rows: tuple[ParsedExcelRow, ...]


def normalize_row_values(values: dict[str, Any]) -> dict[str, Any]:
    """Map the human-readable template headers to stable API field names."""

    normalized: dict[str, Any] = {}
    for header, value in values.items():
        key = HEADER_ALIASES.get(str(header).strip(), str(header).strip())
        normalized[key] = value
    return normalized


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Za-z]+", reference)
    if letters is None:
        raise ExcelWorkbookError(f"单元格引用无效：{reference}")
    result = 0
    for char in letters.group(0).upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def _parse_scalar(value: str, cell_type: str | None) -> Any:
    if cell_type == "b":
        return value == "1"
    if cell_type in {"s", "str", "inlineStr", "e"}:
        return value
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return value
    if not math.isfinite(number):
        return value
    return int(number) if number.is_integer() else number


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text(item) for item in root if _local_name(item.tag) == "si"]


def _worksheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise ExcelWorkbookError("Excel 文件缺少工作簿结构") from exc

    targets: dict[str, str] = {}
    for relationship in relationships:
        if _local_name(relationship.tag) != "Relationship":
            continue
        relation_id = relationship.attrib.get("Id")
        target = relationship.attrib.get("Target")
        if not relation_id or not target:
            continue
        target_path = target.lstrip("/")
        if not target_path.startswith("xl/"):
            target_path = posixpath.normpath(posixpath.join("xl", target_path))
        targets[relation_id] = target_path

    result: dict[str, str] = {}
    for sheet in workbook.iter(f"{{{_NS_MAIN}}}sheet"):
        name = sheet.attrib.get("name", "").strip()
        relation_id = sheet.attrib.get(f"{{{_NS_REL}}}id")
        if name and relation_id in targets:
            result[name] = targets[relation_id]
    return result


def _read_sheet(
    archive: zipfile.ZipFile,
    target: str,
    shared_strings: list[str],
) -> tuple[list[str], list[tuple[int, dict[str, Any]]]]:
    try:
        root = ET.fromstring(archive.read(target))
    except KeyError as exc:
        raise ExcelWorkbookError(f"工作表文件不存在：{target}") from exc

    matrix: list[tuple[int, dict[int, Any]]] = []
    for row in root.iter(f"{{{_NS_MAIN}}}row"):
        row_number = int(row.attrib.get("r", len(matrix) + 1))
        cells: dict[int, Any] = {}
        for cell in row:
            if _local_name(cell.tag) != "c":
                continue
            reference = cell.attrib.get("r", "")
            if not reference:
                continue
            column = _column_index(reference)
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = _text(cell.find(f"{{{_NS_MAIN}}}is"))
            else:
                value = _text(cell.find(f"{{{_NS_MAIN}}}v"))
                if cell_type == "s" and value:
                    try:
                        value = shared_strings[int(value)]
                    except (IndexError, ValueError) as exc:
                        raise ExcelWorkbookError(f"共享字符串索引无效：{value}") from exc
                else:
                    value = _parse_scalar(value, cell_type)
            if value is not None and value != "":
                cells[column] = value
        matrix.append((row_number, cells))

    if not matrix:
        return [], []
    header_cells = matrix[0][1]
    if not header_cells:
        raise ExcelWorkbookError("工作表第一行必须是字段表头")
    max_column = max(header_cells)
    headers = [str(header_cells.get(column, "")).strip() for column in range(max_column + 1)]
    if any(not header for header in headers):
        raise ExcelWorkbookError("工作表表头不能包含空列")

    rows: list[tuple[int, dict[str, Any]]] = []
    for row_number, cells in matrix[1:]:
        values = {
            headers[column]: value
            for column, value in cells.items()
            if column < len(headers) and value is not None and value != ""
        }
        if values:
            rows.append((row_number, values))
    return headers, rows


def parse_excel_workbook(content: bytes) -> ParsedExcelWorkbook:
    if len(content) > MAX_EXCEL_BYTES:
        raise ExcelWorkbookError("Excel 文件不能超过 8 MB")
    if not content.startswith(b"PK"):
        raise ExcelWorkbookError("文件不是有效的 .xlsx 工作簿")

    digest = hashlib.sha256(content).hexdigest()
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ExcelWorkbookError("Excel 压缩包结构损坏") from exc

    with archive:
        targets = _worksheet_targets(archive)
        expected = set(SHEET_SPECS)
        actual = set(targets)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            raise ExcelWorkbookError(f"缺少工作表：{'、'.join(missing)}")
        if extra:
            raise ExcelWorkbookError(f"存在未识别的工作表：{'、'.join(extra)}")

        shared_strings = _shared_strings(archive)
        parsed_rows: list[ParsedExcelRow] = []
        row_counts: dict[str, int] = {}
        for sheet_name in SHEET_SPECS:
            _, rows = _read_sheet(archive, targets[sheet_name], shared_strings)
            row_counts[sheet_name] = len(rows)
            parsed_rows.extend(
                ParsedExcelRow(sheet_name, row_number, values)
                for row_number, values in rows
            )
        if len(parsed_rows) == 0:
            raise ExcelWorkbookError("Excel 工作簿没有可导入的数据行")
        if len(parsed_rows) > MAX_EXCEL_ROWS:
            raise ExcelWorkbookError(f"数据行数不能超过 {MAX_EXCEL_ROWS} 行")

    return ParsedExcelWorkbook(
        file_digest=digest,
        sheet_names=tuple(SHEET_SPECS),
        sheet_row_counts=row_counts,
        rows=tuple(parsed_rows),
    )
