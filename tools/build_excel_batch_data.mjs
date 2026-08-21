import fs from "node:fs/promises";
import { resolve } from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = resolve("outputs/excel-bulk-upload-20260820");
const workbookPath = resolve(outputDir, "隐链明算_Excel批量数据_10组100条.xlsx");
const sampleCopyPath = resolve("frontend/public/sample-data/hiddenchain-excel-batch-data.xlsx");

const sheetNames = [
  "发电计量",
  "新能源预测",
  "售电履约",
  "用户负荷曲线",
  "虚拟电厂资源",
  "调度安全边界",
  "结算关联场景",
  "隐私计算输入",
  "审计追踪场景",
  "风险处置场景",
];

const headers = [
  "序号",
  "资产类型",
  "数据资产名称",
  "批次编号",
  "数据期间",
  "记录数",
  "功能覆盖",
  "关联任务编号",
  "规则版本",
  "计算算法",
  "审计要求",
  "风险等级",
  "预期处置",
  "建议上传角色",
  "示例标记",
  "来源类型",
  "传输协议",
  "加密方式",
  "可信采集证明",
  "电量MWh",
  "预测电量MWh",
  "预测准确率%",
  ...Array.from({ length: 24 }, (_, hour) => `负荷${String(hour).padStart(2, "0")}时`),
  "可调容量MW",
  "储能电量MWh",
  "响应时间分钟",
  "N-1校核",
  "剩余偏差上限MWh",
  "拥塞裕度%",
];

const roleForAsset = {
  GENERATION_DATA: "GENERATOR",
  RENEWABLE_FORECAST: "GENERATOR",
  RETAIL_DATA: "RETAILER",
  USER_LOAD_CURVE: "RETAILER",
  VPP_RESOURCE: "RETAILER",
  GRID_CONSTRAINT: "EXCHANGE",
};

const functionScopeBySheet = {
  发电计量: "数据目录|结算任务|结果确认",
  新能源预测: "规则授权|新能源预测|风险复核",
  售电履约: "数据目录|结算任务|结果确认",
  用户负荷曲线: "数据授权|隐私计算|聚合输出",
  虚拟电厂资源: "数据授权|隐私计算|调度校核",
  调度安全边界: "规则授权|安全闸门|审计凭证",
  结算关联场景: "结算任务|规则冻结|确定性计算",
  隐私计算输入: "数据空间|隐私计算|受控回执",
  审计追踪场景: "结果确认|审计复核|证据台账",
  风险处置场景: "风险处置|安全闸门|审计报告",
};

const assetTypeForSheet = {
  发电计量: () => "GENERATION_DATA",
  新能源预测: () => "RENEWABLE_FORECAST",
  售电履约: () => "RETAIL_DATA",
  用户负荷曲线: () => "USER_LOAD_CURVE",
  虚拟电厂资源: () => "VPP_RESOURCE",
  调度安全边界: () => "GRID_CONSTRAINT",
  结算关联场景: (index) => index % 2 === 0 ? "GENERATION_DATA" : "RETAIL_DATA",
  隐私计算输入: (index) => ["RENEWABLE_FORECAST", "USER_LOAD_CURVE", "VPP_RESOURCE"][index % 3],
  审计追踪场景: (index) => ["GENERATION_DATA", "RENEWABLE_FORECAST", "RETAIL_DATA", "USER_LOAD_CURVE", "VPP_RESOURCE", "GRID_CONSTRAINT"][index % 6],
  风险处置场景: (index) => ["GRID_CONSTRAINT", "RENEWABLE_FORECAST", "USER_LOAD_CURVE", "VPP_RESOURCE", "GENERATION_DATA", "RETAIL_DATA"][index % 6],
};

const algorithmForSheet = {
  发电计量: "LOCAL_CONTROLLED_SETTLEMENT_V1",
  新能源预测: "FEDERATED_LEARNING",
  售电履约: "LOCAL_CONTROLLED_SETTLEMENT_V1",
  用户负荷曲线: "PRIVACY_LOAD_ANALYSIS_V1",
  虚拟电厂资源: "SECRET_SHARING_HE",
  调度安全边界: "TEE_CONFIDENTIAL_COMPUTE",
  结算关联场景: "DETERMINISTIC_RULE_ENGINE",
  隐私计算输入: "PSI_MPC",
  审计追踪场景: "CONTROLLED_SETTLEMENT_V1",
  风险处置场景: "POLICY_SANDBOX",
};

function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function batchFor(index) {
  const month = String(7 + (index % 3)).padStart(2, "0");
  return `TB-EXCEL-2026${month}-${String(index + 1).padStart(3, "0")}`;
}

function payloadFor(assetType, index) {
  if (assetType === "GENERATION_DATA") {
    return { "记录数": 96, "电量MWh": round(720 + index * 3.4 + (index % 7) * 4.2) };
  }
  if (assetType === "RETAIL_DATA") {
    return { "记录数": 96, "电量MWh": round(660 + index * 2.8 + (index % 9) * 3.6) };
  }
  if (assetType === "RENEWABLE_FORECAST") {
    return {
      "记录数": 96,
      "预测电量MWh": round(310 + index * 1.45 + (index % 5) * 2.2),
      "预测准确率%": round(88 + (index % 10) * 0.9, 1),
    };
  }
  if (assetType === "USER_LOAD_CURVE") {
    const curve = {};
    for (let hour = 0; hour < 24; hour += 1) {
      const base = 48 + 18 * Math.sin((hour / 24) * Math.PI * 2 - Math.PI / 2);
      curve[`负荷${String(hour).padStart(2, "0")}时`] = round(Math.max(8, base + (index % 6) * 1.8 + (hour % 5) * 0.7));
    }
    return { "记录数": 24, ...curve };
  }
  if (assetType === "VPP_RESOURCE") {
    return {
      "记录数": 12,
      "可调容量MW": round(120 + index * 0.55),
      "储能电量MWh": round(80 + index * 0.35),
      "响应时间分钟": 5 + (index % 8),
    };
  }
  const failedGate = index % 7 === 0;
  return {
    "记录数": 1,
    "N-1校核": !failedGate,
    "剩余偏差上限MWh": round(20 + (index % 13) * 2.1),
    "拥塞裕度%": failedGate ? round(10 + (index % 3) * 1.5, 1) : round(28 + (index % 4) * 3.5, 1),
  };
}

function rowFor(sheetName, index) {
  const assetType = assetTypeForSheet[sheetName](index);
  const isRiskSheet = sheetName === "风险处置场景";
  const riskLevel = isRiskSheet && index % 3 === 0 ? "HIGH" : index % 4 === 0 ? "MEDIUM" : "LOW";
  const expectedAction = isRiskSheet
    ? (riskLevel === "HIGH" ? "触发安全闸门并转人工复核" : "记录风险信号并继续预检")
    : sheetName === "审计追踪场景" ? "保留摘要、承诺与证据引用"
      : sheetName === "隐私计算输入" ? "仅输出聚合结果，不返回原始值"
        : "进入对应业务流程预检";
  return {
    "序号": index + 1,
    "资产类型": assetType,
    "数据资产名称": `${sheetName}-${String(index + 1).padStart(3, "0")}`,
    "批次编号": batchFor(index),
    "数据期间": `2026-${String(7 + (index % 3)).padStart(2, "0")}`,
    "功能覆盖": functionScopeBySheet[sheetName],
    "关联任务编号": `TASK-EXCEL-${String(index + 1).padStart(3, "0")}`,
    "规则版本": "RULE-SETTLEMENT-2026-V1",
    "计算算法": algorithmForSheet[sheetName],
    "审计要求": "记录来源、数据摘要、承诺和处理责任主体",
    "风险等级": riskLevel,
    "预期处置": expectedAction,
    "建议上传角色": roleForAsset[assetType],
    "示例标记": "示例数据",
    "来源类型": "EXCEL_BATCH_UPLOAD",
    "传输协议": "HTTPS",
    "加密方式": "TLS1.3",
    "可信采集证明": "工作簿结构校验",
    ...payloadFor(assetType, index),
  };
}

function valuesForSheet(sheetName) {
  return [headers, ...Array.from({ length: 100 }, (_, index) => {
    const row = rowFor(sheetName, index);
    return headers.map((header) => row[header] ?? null);
  })];
}

function columnLetter(index) {
  let value = "";
  let number = index + 1;
  while (number > 0) {
    const remainder = (number - 1) % 26;
    value = String.fromCharCode(65 + remainder) + value;
    number = Math.floor((number - 1) / 26);
  }
  return value;
}

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(resolve("frontend/public/sample-data"), { recursive: true });

const workbook = Workbook.create();
sheetNames.forEach((sheetName, sheetIndex) => {
  const sheet = workbook.worksheets.add(sheetName);
  const values = valuesForSheet(sheetName);
  const usedRange = sheet.getRangeByIndexes(0, 0, values.length, headers.length);
  usedRange.values = values;
  // Keep the native Excel worksheet appearance: white cells, black text, and
  // the standard gridlines instead of the product's web color palette.
  sheet.showGridLines = true;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(3);

  usedRange.format = {
    fill: "#FFFFFF",
    font: { color: "#000000" },
  };
  usedRange.format.borders = { preset: "all", style: "thin", color: "#B7B7B7" };

  const header = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  header.format = {
    fill: "#FFFFFF",
    font: { bold: true, color: "#000000" },
    wrapText: true,
  };
  header.format.rowHeight = 28;
  usedRange.format.borders = { preset: "outside", style: "thin", color: "#C9D5D4" };

  const widths = {
    0: 8, 1: 18, 2: 24, 3: 22, 4: 12, 5: 10, 6: 30, 7: 20, 8: 22,
    9: 28, 10: 30, 11: 10, 12: 30, 13: 16, 14: 12, 15: 20, 16: 12,
    17: 12, 18: 22, 19: 13, 20: 15, 21: 13,
    ...Object.fromEntries(Array.from({ length: 24 }, (_, hour) => [22 + hour, 10])),
    46: 14, 47: 14, 48: 14, 49: 12, 50: 18, 51: 14,
  };
  Object.entries(widths).forEach(([column, width]) => {
    sheet.getRangeByIndexes(0, Number(column), values.length, 1).format.columnWidth = width;
  });

  const numericFormats = {
    "电量MWh": "#,##0.00",
    "预测电量MWh": "#,##0.00",
    "预测准确率%": "0.0",
    "可调容量MW": "#,##0.00",
    "储能电量MWh": "#,##0.00",
    "响应时间分钟": "0",
    "剩余偏差上限MWh": "#,##0.00",
    "拥塞裕度%": "0.0",
  };
  Object.entries(numericFormats).forEach(([headerName, format]) => {
    const column = headers.indexOf(headerName);
    sheet.getRangeByIndexes(1, column, values.length - 1, 1).setNumberFormat(format);
  });
  const loadStart = headers.indexOf("负荷00时");
  sheet.getRangeByIndexes(1, loadStart, values.length - 1, 24).setNumberFormat("#,##0.00");

  const allowed = [...new Set(Array.from({ length: 100 }, (_, index) => assetTypeForSheet[sheetName](index)))];
  sheet.getRangeByIndexes(1, headers.indexOf("资产类型"), 100, 1).dataValidation = { rule: { type: "list", values: allowed } };
  sheet.getRangeByIndexes(1, headers.indexOf("风险等级"), 100, 1).dataValidation = { rule: { type: "list", values: ["LOW", "MEDIUM", "HIGH"] } };
  sheet.getRangeByIndexes(1, headers.indexOf("N-1校核"), 100, 1).dataValidation = { rule: { type: "list", values: ["通过", "未通过"] } };

  console.log(`${sheetName}: ${values.length - 1} rows, range A1:${columnLetter(headers.length - 1)}101, allowed=${allowed.join(",")}, sheetIndex=${sheetIndex + 1}`);
});

const check = await workbook.inspect({
  kind: "table",
  range: "发电计量!A1:AO5",
  include: "values,formulas",
  tableMaxRows: 5,
  tableMaxCols: 12,
  maxChars: 6000,
});
console.log(check.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(formulaErrors.ndjson);

for (const sheetName of sheetNames) {
  const preview = await workbook.render({ sheetName, range: "A1:AO12", scale: 1, format: "png" });
  await fs.writeFile(resolve(outputDir, `preview-${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(workbookPath);
await fs.copyFile(workbookPath, sampleCopyPath);
console.log(JSON.stringify({ workbookPath, sampleCopyPath, sheetCount: sheetNames.length, rowsPerSheet: 100, totalRows: 1000 }, null, 2));
