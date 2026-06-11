// VitaTrack — Google Apps Script
// ─────────────────────────────────────────────────────────────
// HOW TO DEPLOY:
//  1. Go to script.google.com → New project → paste this file
//  2. Click Deploy → New deployment → Web app
//  3. Execute as: Me | Who has access: Anyone
//  4. Copy the web app URL → paste into VitaTrack Settings
// ─────────────────────────────────────────────────────────────

const CATEGORY_NAMES = {
  tasks:     'Tasks',
  fitness:   'Fitness',
  diet:      'Diet',
  sleep:     'Sleep',
  mood:      'Mood',
  journal:   'Journal',
  habits:    'Habits',
  learning:  'Learning',
  gratitude: 'Gratitude',
  challenge: 'Challenge'
};

const HEADER_COLOR  = '#16A34A';
const HEADER_FONT   = '#FFFFFF';
const BACKUP_COLOR  = '#1C1917';

// ── Entry point ───────────────────────────────────────────────
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const ss   = SpreadsheetApp.getActiveSpreadsheet();

    if (data.type === 'full_backup') {
      saveFullBackup(ss, data.payload);
    } else if (data.category && data.headers && data.row) {
      saveCategoryRow(ss, data);
    }

    return jsonResponse({ status: 'ok' });
  } catch (err) {
    return jsonResponse({ status: 'error', message: err.message });
  }
}

// ── Per-category row (called on every check-in) ───────────────
function saveCategoryRow(ss, data) {
  const name  = CATEGORY_NAMES[data.category] || capitalize(data.category);
  let   sheet = ss.getSheetByName(name);

  if (!sheet) {
    sheet = ss.insertSheet(name);
    styleHeader(sheet, data.headers);
  }

  const date       = String(data.row[0]);
  const dateValues = sheet.getRange('A:A').getValues().flat().map(String);
  const existing   = dateValues.indexOf(date);

  if (existing > 0) {
    sheet.getRange(existing + 1, 1, 1, data.row.length).setValues([data.row]);
  } else {
    sheet.appendRow(data.row);
  }

  sheet.autoResizeColumns(1, data.headers.length);
}

// ── Full JSON backup ──────────────────────────────────────────
function saveFullBackup(ss, payload) {
  let sheet = ss.getSheetByName('Full Backup');
  if (!sheet) {
    sheet = ss.insertSheet('Full Backup');
    const h = sheet.getRange(1, 1, 1, 3);
    h.setValues([['Timestamp', 'Date', 'JSON Data']]);
    h.setFontWeight('bold');
    h.setBackground(BACKUP_COLOR);
    h.setFontColor(HEADER_FONT);
    sheet.setFrozenRows(1);
    sheet.setColumnWidth(1, 180);
    sheet.setColumnWidth(2, 100);
    sheet.setColumnWidth(3, 900);
  }

  const now = new Date();
  sheet.appendRow([
    now.toISOString(),
    Utilities.formatDate(now, Session.getScriptTimeZone(), 'yyyy-MM-dd'),
    JSON.stringify(payload)
  ]);
}

// ── Helpers ───────────────────────────────────────────────────
function styleHeader(sheet, headers) {
  const range = sheet.getRange(1, 1, 1, headers.length);
  range.setValues([headers]);
  range.setFontWeight('bold');
  range.setBackground(HEADER_COLOR);
  range.setFontColor(HEADER_FONT);
  sheet.setFrozenRows(1);
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
