import * as XLSX from 'xlsx'

/**
 * Export data to CSV file
 */
export function exportToCSV(data: any[], filename: string) {
  if (!data || data.length === 0) {
    console.warn('No data to export')
    return
  }

  // Convert data to CSV format
  const headers = Object.keys(data[0])
  const csvContent = [
    headers.join(','),
    ...data.map(row =>
      headers.map(header => {
        const value = row[header]
        // Escape commas and quotes
        if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
          return `"${value.replace(/"/g, '""')}"`
        }
        return value ?? ''
      }).join(',')
    )
  ].join('\n')

  // Create blob and download
  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)

  link.setAttribute('href', url)
  link.setAttribute('download', `${filename}.csv`)
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

/**
 * Export data to Excel file
 */
export function exportToExcel(data: any[], filename: string, sheetName: string = 'Sheet1') {
  if (!data || data.length === 0) {
    console.warn('No data to export')
    return
  }

  // Create worksheet
  const worksheet = XLSX.utils.json_to_sheet(data)

  // Create workbook
  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, sheetName)

  // Generate Excel file and download
  XLSX.writeFile(workbook, `${filename}.xlsx`)
}

/**
 * Export multiple sheets to Excel
 */
export function exportMultiSheetExcel(
  sheets: Array<{ name: string; data: any[] }>,
  filename: string
) {
  const workbook = XLSX.utils.book_new()

  sheets.forEach(sheet => {
    if (sheet.data && sheet.data.length > 0) {
      const worksheet = XLSX.utils.json_to_sheet(sheet.data)
      XLSX.utils.book_append_sheet(workbook, worksheet, sheet.name)
    }
  })

  XLSX.writeFile(workbook, `${filename}.xlsx`)
}

/**
 * Format data for export (remove unnecessary fields, format dates, etc.)
 */
export function formatDataForExport(data: any[], fieldsToRemove: string[] = []): any[] {
  return data.map(item => {
    const formatted: any = {}

    Object.keys(item).forEach(key => {
      // Skip fields to remove
      if (fieldsToRemove.includes(key)) {
        return
      }

      const value = item[key]

      // Format dates
      if (value instanceof Date) {
        formatted[key] = value.toLocaleString()
      }
      // Format ISO date strings
      else if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
        formatted[key] = new Date(value).toLocaleString()
      }
      // Format booleans
      else if (typeof value === 'boolean') {
        formatted[key] = value ? 'Yes' : 'No'
      }
      // Keep other values as is
      else {
        formatted[key] = value
      }
    })

    return formatted
  })
}
