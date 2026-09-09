/** Zero-dependency Excel (.xls SpreadsheetML) download — opens in Microsoft Excel. */

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cellXml(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return `<Cell><Data ss:Type="String"></Data></Cell>`;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<Cell><Data ss:Type="Number">${value}</Data></Cell>`;
  }
  const text = String(value);
  const asNum = Number(text);
  if (text.trim() !== "" && Number.isFinite(asNum) && /^-?\d+(\.\d+)?$/.test(text.trim())) {
    return `<Cell><Data ss:Type="Number">${text.trim()}</Data></Cell>`;
  }
  return `<Cell><Data ss:Type="String">${escapeXml(text)}</Data></Cell>`;
}

export function downloadExcelSheet(options: {
  filename: string;
  sheetName?: string;
  headers: string[];
  rows: Array<Array<string | number | boolean | null | undefined>>;
}) {
  const sheetName = (options.sheetName || "Sheet1").slice(0, 31);
  const headerRow = `<Row>${options.headers.map((h) => cellXml(h)).join("")}</Row>`;
  const bodyRows = options.rows
    .map((row) => `<Row>${row.map((c) => cellXml(c)).join("")}</Row>`)
    .join("");

  const xml = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
 <Worksheet ss:Name="${escapeXml(sheetName)}">
  <Table>
   ${headerRow}
   ${bodyRows}
  </Table>
 </Worksheet>
</Workbook>`;

  const blob = new Blob([xml], {
    type: "application/vnd.ms-excel;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const name = options.filename.endsWith(".xls")
    ? options.filename
    : `${options.filename}.xls`;
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
