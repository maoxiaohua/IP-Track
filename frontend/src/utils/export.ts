import ExcelJS from 'exceljs'

/** Default header style: white text on blue background */
function styleHeader(row: ExcelJS.Row, colCount: number) {
  row.height = 24
  for (let i = 1; i <= colCount; i++) {
    const cell = row.getCell(i)
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF4472C4' } }
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 12 }
    cell.alignment = { horizontal: 'center', vertical: 'middle' }
    cell.border = {
      top: { style: 'thin', color: { argb: 'FFD0D0D0' } },
      bottom: { style: 'thin', color: { argb: 'FFD0D0D0' } },
      left: { style: 'thin', color: { argb: 'FFD0D0D0' } },
      right: { style: 'thin', color: { argb: 'FFD0D0D0' } }
    }
  }
}

/** Apply alternating row colors and borders to data rows */
function styleDataRow(row: ExcelJS.Row, colCount: number, isEven: boolean) {
  row.height = 20
  const bgColor = isEven ? 'FFF5F7FA' : 'FFFFFFFF'
  for (let i = 1; i <= colCount; i++) {
    const cell = row.getCell(i)
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bgColor } }
    cell.font = { color: { argb: 'FF333333' }, size: 11 }
    cell.alignment = { vertical: 'middle' }
    cell.border = {
      top: { style: 'thin', color: { argb: 'FFE0E0E0' } },
      bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } },
      left: { style: 'thin', color: { argb: 'FFE0E0E0' } },
      right: { style: 'thin', color: { argb: 'FFE0E0E0' } }
    }
  }
}

/**
 * Export data to Excel file (.xlsx) with styled headers and alternating rows.
 */
export async function exportToExcel(
  data: Record<string, any>[],
  filename: string,
  sheetName: string = 'Sheet1'
) {
  if (!data || data.length === 0) {
    console.warn('No data to export')
    return
  }

  const workbook = new ExcelJS.Workbook()
  const worksheet = workbook.addWorksheet(sheetName)

  const headers = Object.keys(data[0])

  // Header row
  const headerRow = worksheet.addRow(headers)
  styleHeader(headerRow, headers.length)

  // Data rows
  data.forEach((item, index) => {
    const values = headers.map(h => item[h] ?? '')
    const row = worksheet.addRow(values)
    styleDataRow(row, headers.length, index % 2 === 0)
  })

  // Auto-fit column widths
  worksheet.columns = headers.map((header, colIdx) => {
    const dataMaxLen = Math.max(...data.map(row => {
      const val = row[header]
      return val != null ? String(val).length : 0
    }))
    const headerLen = String(header).length * 2 // CJK chars are ~2x width
    return {
      header,
      key: String(colIdx),
      width: Math.min(Math.max(headerLen, dataMaxLen * 1.1) + 4, 40)
    }
  })

  // Freeze header row
  worksheet.views = [{ state: 'frozen', ySplit: 1 }]

  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  downloadBlob(blob, `${filename}.xlsx`)
}

/**
 * Export data to CSV file (plain text, UTF-8 with BOM).
 */
export function exportToCSV(data: Record<string, any>[], filename: string) {
  if (!data || data.length === 0) {
    console.warn('No data to export')
    return
  }

  const headers = Object.keys(data[0])
  const csvContent = [
    headers.join(','),
    ...data.map(row =>
      headers.map(header => {
        const value = row[header]
        if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
          return `"${value.replace(/"/g, '""')}"`
        }
        return value ?? ''
      }).join(',')
    )
  ].join('\n')

  const blob = new Blob(['﻿' + csvContent], { type: 'text/csv;charset=utf-8;' })
  downloadBlob(blob, `${filename}.csv`)
}

function downloadBlob(blob: Blob, filename: string) {
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)
  link.setAttribute('href', url)
  link.setAttribute('download', filename)
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
