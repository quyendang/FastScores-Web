/* ============================================================
   ClassPro Web — app.js
   Language switching (EN/VI), Dark/Light mode, Table sorting
   ============================================================ */

/* ── Translation strings ──────────────────────────────────── */
const STRINGS = {
  en: {
    // Navigation / General
    appName:          'ClassPro',
    tagline:          'Easy class report sharing',
    taglineSub:       'Generate beautiful, shareable reports for your classroom in seconds.',
    backHome:         '← Back to Home',
    toggleDark:       'Dark',
    toggleLight:      'Light',
    langLabel:        'VI',
    noData:           'No data',
    generatedAt:      'Generated at',
    madeFor:          'Made with ❤️ for teachers',
    viewReport:       'View Report',

    // Feature cards
    feat1Title:       'Class Report',
    feat1Desc:        'Full class overview — grades, rankings, and attendance in one shareable link.',
    feat2Title:       'Student Report',
    feat2Desc:        'Per-student breakdown with category grades, attendance, and personal info.',
    feat3Title:       'Export to Excel',
    feat3Desc:        'Download the full report as CSV or Excel for offline use and record keeping.',

    // Stats
    totalStudents:    'Total Students',
    classAverage:     'Class Average',
    attendanceRate:   'Attendance Rate',
    totalSessions:    'Total Sessions',
    students:         'Students',
    sessions:         'Sessions',
    summary:          'Summary',
    categories:       'Grade Categories',

    // Export
    exportCSV:        'Export CSV',
    exportExcel:      'Export Excel',

    // Table headers
    rank:             'Rank',
    student:          'Student',
    studentCode:      'Student Code',
    avgGrade:         'Avg Grade',
    letterGrade:      'Letter Grade',
    attendance:       'Attendance',
    sortBy:           'Sort by',
    classRank:        'Class Rank',

    // Attendance status labels
    present:          'Present',
    late:             'Late',
    absent:           'Absent',
    excused:          'Excused',
    total:            'Total',
    attendanceBreakdown: 'Attendance Breakdown',
    rankings:         'Rankings',

    // Student report
    gradeCategories:  'Grade Categories',
    category:         'Category',
    weight:           'Weight',
    score:            'Score',
    categoryAvg:      'Category Avg',
    studentInfo:      'Student Information',
    gender:           'Gender',
    parent:           'Parent / Guardian',
    phone:            'Phone',
    dateOfBirth:      'Date of Birth',
    studentDetails:   'Student Details',
    reportSubtitle:   'Individual Student Report',

    // Error page
    errorTitle404:    'Page Not Found',
    errorDetail404:   'This report link does not exist or may have been removed.',
    errorTitle410:    'Report Expired',
    errorDetail410:   'This report link has expired and is no longer available.',
    errorGeneric:     'Something went wrong.',
  },

  vi: {
    appName:          'ClassPro',
    tagline:          'Chia sẻ báo cáo lớp học dễ dàng',
    taglineSub:       'Tạo báo cáo đẹp, dễ chia sẻ cho lớp học của bạn chỉ trong vài giây.',
    backHome:         '← Về trang chủ',
    toggleDark:       'Tối',
    toggleLight:      'Sáng',
    langLabel:        'EN',
    noData:           'Chưa có dữ liệu',
    generatedAt:      'Tạo lúc',
    madeFor:          'Làm với ❤️ cho giáo viên',
    viewReport:       'Xem báo cáo',

    feat1Title:       'Báo cáo lớp học',
    feat1Desc:        'Tổng quan toàn lớp — điểm số, xếp hạng và điểm danh trong một liên kết.',
    feat2Title:       'Báo cáo học sinh',
    feat2Desc:        'Chi tiết từng học sinh với điểm theo môn, điểm danh và thông tin cá nhân.',
    feat3Title:       'Xuất Excel',
    feat3Desc:        'Tải xuống báo cáo đầy đủ dưới dạng CSV hoặc Excel để lưu trữ và sử dụng ngoại tuyến.',

    totalStudents:    'Tổng học sinh',
    classAverage:     'Điểm TB lớp',
    attendanceRate:   'Tỉ lệ điểm danh',
    totalSessions:    'Tổng số buổi',
    students:         'Học sinh',
    sessions:         'Buổi học',
    summary:          'Tổng quan',
    categories:       'Phân loại điểm',

    exportCSV:        'Xuất CSV',
    exportExcel:      'Xuất Excel',

    rank:             'Hạng',
    student:          'Học sinh',
    studentCode:      'Mã học sinh',
    avgGrade:         'Điểm TB',
    letterGrade:      'Xếp loại',
    attendance:       'Điểm danh',
    sortBy:           'Sắp xếp theo',
    classRank:        'Thứ hạng trong lớp',

    present:          'Có mặt',
    late:             'Đi muộn',
    absent:           'Vắng',
    excused:          'Có phép',
    total:            'Tổng',
    attendanceBreakdown: 'Chi tiết điểm danh',
    rankings:         'Bảng xếp hạng',

    gradeCategories:  'Điểm theo môn',
    category:         'Môn',
    weight:           'Hệ số',
    score:            'Điểm',
    categoryAvg:      'Điểm TB môn',
    studentInfo:      'Thông tin học sinh',
    gender:           'Giới tính',
    parent:           'Phụ huynh',
    phone:            'SĐT',
    dateOfBirth:      'Ngày sinh',
    studentDetails:   'Hồ sơ học sinh',
    reportSubtitle:   'Báo cáo học sinh cá nhân',

    errorTitle404:    'Không tìm thấy trang',
    errorDetail404:   'Liên kết báo cáo này không tồn tại hoặc đã bị xóa.',
    errorTitle410:    'Báo cáo đã hết hạn',
    errorDetail410:   'Liên kết báo cáo này đã hết hạn và không còn khả dụng.',
    errorGeneric:     'Đã xảy ra lỗi.',
  }
};

/* ── Badge display names ──────────────────────────────────── */
const BADGE_NAMES = {
  en: {
    '':            '',
    'none':        '',
    'monitor':     'Monitor',
    'vice_monitor':'Vice Monitor',
    'secretary':   'Secretary',
    'treasurer':   'Treasurer',
    'member':      'Member',
  },
  vi: {
    '':            '',
    'none':        '',
    'monitor':     'Lớp trưởng',
    'vice_monitor':'Lớp phó',
    'secretary':   'Thư ký',
    'treasurer':   'Thủ quỹ',
    'member':      'Thành viên',
  }
};

/* ── State ────────────────────────────────────────────────── */
let currentLang  = localStorage.getItem('cp_lang')  || 'vi';
let currentTheme = localStorage.getItem('cp_theme') || 'auto';

/* ── Initialise ───────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  applyTheme(currentTheme);
  applyLang(currentLang);
  initSorting();
});

/* ── Theme ────────────────────────────────────────────────── */
function applyTheme(theme) {
  currentTheme = theme;
  localStorage.setItem('cp_theme', theme);

  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const isDark = theme === 'dark' || (theme === 'auto' && prefersDark);

  document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
  updateThemeButton(isDark);
}

function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  applyTheme(isDark ? 'light' : 'dark');
}

function updateThemeButton(isDark) {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  const t = STRINGS[currentLang];
  if (isDark) {
    btn.innerHTML = `${sunIcon()} <span>${t.toggleLight}</span>`;
    btn.setAttribute('aria-label', 'Switch to light mode');
  } else {
    btn.innerHTML = `${moonIcon()} <span>${t.toggleDark}</span>`;
    btn.setAttribute('aria-label', 'Switch to dark mode');
  }
}

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (currentTheme === 'auto') applyTheme('auto');
});

/* ── Language ─────────────────────────────────────────────── */
function applyLang(lang) {
  currentLang = lang;
  localStorage.setItem('cp_lang', lang);
  document.documentElement.setAttribute('lang', lang === 'vi' ? 'vi' : 'en');

  // Update all [data-i18n] elements
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (STRINGS[lang] && STRINGS[lang][key] !== undefined) {
      el.textContent = STRINGS[lang][key];
    }
  });

  // Update lang toggle button label (shows the OTHER language)
  const langBtn = document.getElementById('langToggle');
  if (langBtn) {
    langBtn.textContent = lang === 'vi' ? 'EN' : 'VI';
    langBtn.setAttribute('aria-label', lang === 'vi' ? 'Switch to English' : 'Chuyển sang tiếng Việt');
  }

  // Re-sync theme button label after lang change
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  updateThemeButton(isDark);

  // Update badge chips
  document.querySelectorAll('[data-badge]').forEach(el => {
    const badge = el.getAttribute('data-badge');
    const name = (BADGE_NAMES[lang] || {})[badge] || '';
    el.textContent = name;
    el.style.display = name ? '' : 'none';
  });
}

function toggleLang() {
  applyLang(currentLang === 'vi' ? 'en' : 'vi');
}

/* ── Table Sorting ────────────────────────────────────────── */
function initSorting() {
  document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const table = th.closest('table');
      const tbody = table.querySelector('tbody');
      const col   = parseInt(th.getAttribute('data-col'), 10);
      const type  = th.getAttribute('data-type') || 'string';

      // Determine direction
      const wasAsc = th.classList.contains('sort-asc');
      const dir    = wasAsc ? 'desc' : 'asc';

      // Clear all sort indicators in this table
      table.querySelectorAll('th.sortable').forEach(h => {
        h.classList.remove('sort-asc', 'sort-desc');
      });
      th.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');

      // Sort rows
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort((a, b) => {
        const aCell = a.querySelectorAll('td')[col];
        const bCell = b.querySelectorAll('td')[col];
        let aVal = aCell ? (aCell.getAttribute('data-sort') || aCell.textContent.trim()) : '';
        let bVal = bCell ? (bCell.getAttribute('data-sort') || bCell.textContent.trim()) : '';

        if (type === 'number') {
          aVal = parseFloat(aVal) || -Infinity;
          bVal = parseFloat(bVal) || -Infinity;
          return dir === 'asc' ? aVal - bVal : bVal - aVal;
        } else {
          // Case-insensitive locale compare
          return dir === 'asc'
            ? aVal.localeCompare(bVal, undefined, { sensitivity: 'base' })
            : bVal.localeCompare(aVal, undefined, { sensitivity: 'base' });
        }
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
}

/* ── SVG icon helpers ─────────────────────────────────────── */
function moonIcon() {
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
}

function sunIcon() {
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
}

/* ── Utility: letter-grade CSS class ─────────────────────── */
function gradeChipClass(letter) {
  if (!letter) return '';
  const l = letter.trim().toUpperCase().charAt(0);
  const map = { A: 'grade-chip-A', B: 'grade-chip-B', C: 'grade-chip-C', D: 'grade-chip-D', F: 'grade-chip-F' };
  return 'chip ' + (map[l] || '');
}

/* ── Utility: attendance chip class ──────────────────────── */
function attChipClass(rate) {
  const n = parseFloat(rate);
  if (n >= 80) return 'chip att-chip-good';
  if (n >= 60) return 'chip att-chip-ok';
  return 'chip att-chip-bad';
}
