/* ============================================================
   FastScores Web — app.js
   Bootstrap 5.3 theme system (data-bs-theme), language
   switching (EN/VI), table sorting.
   ============================================================ */

/* ── Theme ─────────────────────────────────────────────────── */
function applyTheme(theme) {
  // theme: 'light' | 'dark' | 'auto'
  const resolved = theme === 'auto'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme;

  document.documentElement.setAttribute('data-bs-theme', resolved);
  localStorage.setItem('cp-theme', theme);

  // Update toggle button icon
  const btn = document.getElementById('themeToggle');
  if (btn) {
    btn.innerHTML = resolved === 'dark'
      ? '<i class="bi bi-sun-fill"></i>'
      : '<i class="bi bi-moon-fill"></i>';
    btn.setAttribute('aria-label', resolved === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-bs-theme') || 'light';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

/* ── Translation strings ────────────────────────────────────── */
const STRINGS = {
  en: {
    // Navigation & common
    toggleDark:    'Dark',
    toggleLight:   'Light',
    madeFor:       'Made with ❤️ for teachers',
    reportSubtitle:'Individual Student Report',

    // Index
    heroTagline:         'Easy class report sharing',
    noLoginNeeded:       'No login required',
    mobileFriendly:      'Mobile friendly',
    readOnly:            'Read-only · Secure',
    featureClassReport:  'Class Report',
    featureStudentReport:'Student Report',
    featureExport:       'Export Excel/CSV',
    featureClassDesc:    'Full class rankings, grades & attendance',
    featureStudentDesc:  'Individual performance, rank & history',
    featureExportDesc:   'Download data in one click',
    howItWorks:          'How it works',
    step1Title:          'Teacher shares',
    step2Title:          'Open link',
    step3Title:          'View report',
    step1:               'Teacher creates share link in app',
    step2:               'Parent opens link — no login needed',
    step3:               'View full report instantly',
    linkNote:            'Links expire after 7 days · Read-only · No account needed',

    // iOS Download section
    downloadEyebrow:     'iOS App',
    downloadTitle:       'Get FastScores on iPhone',
    downloadDesc:        'Manage classes, record grades & attendance, generate reports — all from your iPhone.',
    downloadFeature1:    'Grade & attendance tracking',
    downloadFeature2:    'One-tap share links for parents',
    downloadFeature3:    'Export PDF, CSV & Excel',

    // Report page
    summary:             'Summary',
    totalStudents:       'Total Students',
    students:            'Students',
    classAverage:        'Class Average',
    attendanceRate:      'Attendance Rate',
    totalSessions:       'Total Sessions',
    sessions:            'Sessions',
    rankings:            'Rankings',
    rank:                'Rank',
    student:             'Student',
    studentCode:         'Student Code',
    avgGrade:            'Avg Grade',
    letterGrade:         'Grade',
    attendance:          'Attendance',
    attendanceBreakdown: 'Attendance Breakdown',
    present:             'Present',
    late:                'Late',
    absent:              'Absent',
    excused:             'Excused',
    total:               'Total',
    noData:              'No data available',
    generatedAt:         'Generated at',
    exportCSV:           'Export CSV',
    exportExcel:         'Export Excel',
    detail:              'Details',

    // Student page
    classRank:       'Class Rank',
    gradeCategories: 'Grade Categories',
    category:        'Category',
    weight:          'Weight',
    score:           'Scores',
    categoryAvg:     'Avg',
    studentInfo:     'Student Info',
    gender:          'Gender',
    dateOfBirth:     'Date of Birth',
    parent:          'Parent',
    phone:           'Phone',

    // Error
    goHome:          'Back to Home',
    pageNotFound:    'Page Not Found',
    linkExpired:     'Link Expired',
    pageNotFoundMsg: 'This report link is invalid or does not exist.',
    linkExpiredMsg:  'This report link has expired. Please ask the teacher to generate a new one.',
  },

  vi: {
    toggleDark:    'Tối',
    toggleLight:   'Sáng',
    madeFor:       'Làm với ❤️ cho các giáo viên',

    heroTagline:         'Chia sẻ báo cáo lớp học dễ dàng',
    noLoginNeeded:       'Không cần đăng nhập',
    mobileFriendly:      'Thân thiện di động',
    readOnly:            'Chỉ xem · Bảo mật',
    featureClassReport:  'Báo cáo lớp',
    featureStudentReport:'Báo cáo học sinh',
    featureExport:       'Xuất Excel/CSV',
    featureClassDesc:    'Bảng xếp hạng, điểm số & điểm danh toàn lớp',
    featureStudentDesc:  'Kết quả cá nhân, thứ hạng & lịch sử',
    featureExportDesc:   'Tải dữ liệu lớp chỉ với một cú nhấp',
    howItWorks:          'Cách hoạt động',
    step1Title:          'Giáo viên chia sẻ',
    step2Title:          'Mở link',
    step3Title:          'Xem báo cáo',
    step1:               'Giáo viên tạo link chia sẻ trong app',
    step2:               'Phụ huynh mở link — không cần đăng nhập',
    step3:               'Xem báo cáo đầy đủ ngay lập tức',
    linkNote:            'Link hết hạn sau 7 ngày · Chỉ xem · Không cần tài khoản',

    // iOS Download section
    downloadEyebrow:     'Ứng dụng iOS',
    downloadTitle:       'Tải FastScores trên iPhone',
    downloadDesc:        'Quản lý lớp học, ghi điểm & điểm danh, tạo báo cáo — ngay trên iPhone.',
    downloadFeature1:    'Theo dõi điểm số & điểm danh',
    downloadFeature2:    'Chia sẻ link cho phụ huynh chỉ một chạm',
    downloadFeature3:    'Xuất PDF, CSV & Excel',

    summary:             'Tổng quan',
    totalStudents:       'Tổng học sinh',
    students:            'Học sinh',
    classAverage:        'Điểm TB lớp',
    attendanceRate:      'Tỉ lệ điểm danh',
    totalSessions:       'Tổng số buổi',
    sessions:            'Buổi học',
    rankings:            'Bảng xếp hạng',
    rank:                'Hạng',
    student:             'Học sinh',
    studentCode:         'Mã học sinh',
    avgGrade:            'Điểm TB',
    letterGrade:         'Xếp loại',
    attendance:          'Điểm danh',
    attendanceBreakdown: 'Chi tiết điểm danh',
    present:             'Có mặt',
    late:                'Đi muộn',
    absent:              'Vắng',
    excused:             'Có phép',
    total:               'Tổng',
    noData:              'Chưa có dữ liệu',
    generatedAt:         'Tạo lúc',
    exportCSV:           'Xuất CSV',
    exportExcel:         'Xuất Excel',
    detail:              'Chi tiết',

    classRank:       'Thứ hạng',
    gradeCategories: 'Điểm theo môn',
    category:        'Môn',
    weight:          'Hệ số',
    score:           'Điểm',
    categoryAvg:     'TB',
    studentInfo:     'Thông tin học sinh',
    gender:          'Giới tính',
    dateOfBirth:     'Ngày sinh',
    parent:          'Phụ huynh',
    phone:           'SĐT',

    goHome:          'Về trang chủ',
    pageNotFound:    'Không tìm thấy trang',
    linkExpired:     'Link đã hết hạn',
    pageNotFoundMsg: 'Link báo cáo này không hợp lệ hoặc không tồn tại.',
    linkExpiredMsg:  'Link báo cáo này đã hết hạn. Vui lòng yêu cầu giáo viên tạo link mới.',
  }
};

/* ── Badge display names ────────────────────────────────────── */
const BADGE_NAMES = {
  en: {
    monitor:      'Monitor',
    vice_monitor: 'Vice Monitor',
    secretary:    'Secretary',
    treasurer:    'Treasurer',
    member:       'Member',
  },
  vi: {
    monitor:      'Lớp trưởng',
    vice_monitor: 'Lớp phó',
    secretary:    'Thư ký',
    treasurer:    'Thủ quỹ',
    member:       'Thành viên',
  }
};

/* ── Language ───────────────────────────────────────────────── */
let currentLang = localStorage.getItem('cp-lang') || 'vi';

function applyLang(lang) {
  currentLang = lang;
  localStorage.setItem('cp-lang', lang);

  const strings = STRINGS[lang] || STRINGS.vi;

  // Update all [data-i18n] elements
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (strings[key] !== undefined) el.textContent = strings[key];
  });

  // Update badge chips
  document.querySelectorAll('[data-badge]').forEach(el => {
    const badge = el.dataset.badge;
    const name = (BADGE_NAMES[lang] || BADGE_NAMES.vi)[badge];
    if (name) {
      el.textContent = name;
      el.style.display = '';
    } else {
      el.style.display = 'none';
    }
  });

  // Show/hide [data-lang] blocks (used by support & privacy pages)
  document.querySelectorAll('[data-lang]').forEach(el => {
    el.style.display = el.dataset.lang === lang ? '' : 'none';
  });

  // Update lang toggle label (shows the OTHER language)
  const btn = document.getElementById('langToggle');
  if (btn) {
    btn.textContent = lang === 'vi' ? 'EN' : 'VI';
    btn.setAttribute('aria-label', lang === 'vi' ? 'Switch to English' : 'Chuyển sang tiếng Việt');
  }

  document.documentElement.lang = lang === 'vi' ? 'vi' : 'en';
}

function toggleLang() {
  applyLang(currentLang === 'vi' ? 'en' : 'vi');
}

/* ── Table sorting ──────────────────────────────────────────── */
function initTableSort(tableId) {
  const table = tableId ? document.getElementById(tableId) : null;
  const tables = table ? [table] : document.querySelectorAll('table');
  tables.forEach(t => _attachSortListeners(t));
}

function _attachSortListeners(table) {
  if (!table) return;
  let sortCol = -1, sortAsc = true;

  table.querySelectorAll('th.sortable').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const col  = parseInt(th.dataset.col, 10);
      const type = th.dataset.type || 'string';

      if (sortCol === col) {
        sortAsc = !sortAsc;
      } else {
        sortCol = col;
        sortAsc = true;
      }

      table.querySelectorAll('th').forEach(t => t.classList.remove('sort-asc', 'sort-desc'));
      th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');

      const tbody = table.querySelector('tbody');
      const rows  = Array.from(tbody.querySelectorAll('tr'));

      rows.sort((a, b) => {
        const aCell = a.cells[col];
        const bCell = b.cells[col];
        const aVal  = aCell?.dataset.sort ?? aCell?.textContent.trim() ?? '';
        const bVal  = bCell?.dataset.sort ?? bCell?.textContent.trim() ?? '';

        let cmp = type === 'number'
          ? (parseFloat(aVal) || -Infinity) - (parseFloat(bVal) || -Infinity)
          : aVal.localeCompare(bVal, undefined, { sensitivity: 'base' });

        return sortAsc ? cmp : -cmp;
      });

      rows.forEach(r => tbody.appendChild(r));
    });
  });
}

/* ── Utility: grade chip class ──────────────────────────────── */
function gradeChipClass(letter) {
  if (!letter) return 'chip';
  const l = letter.trim().toUpperCase().charAt(0);
  const map = { A: 'grade-chip-A', B: 'grade-chip-B', C: 'grade-chip-C', D: 'grade-chip-D', F: 'grade-chip-F' };
  return 'chip ' + (map[l] || '');
}

/* ── Utility: attendance chip class ────────────────────────── */
function attChipClass(rate) {
  const n = parseFloat(rate);
  if (n >= 80) return 'chip att-chip-good';
  if (n >= 60) return 'chip att-chip-ok';
  return 'chip att-chip-bad';
}

/* ── Init ───────────────────────────────────────────────────── */
// Script is at end of <body> so DOM is ready — no DOMContentLoaded needed.
(function init() {
  // Theme
  const savedTheme = localStorage.getItem('cp-theme') || 'light';
  applyTheme(savedTheme);

  // Language
  applyLang(currentLang);

  // Table sort
  initTableSort('rankingsTable');
  initTableSort(null);

  // Button event listeners
  const langBtn  = document.getElementById('langToggle');
  const themeBtn = document.getElementById('themeToggle');
  if (langBtn)  langBtn.addEventListener('click',  toggleLang);
  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

  // Footer year
  const yearEl = document.getElementById('footerYear');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // Follow system preference changes when theme is 'auto'
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (localStorage.getItem('cp-theme') === 'auto') applyTheme('auto');
  });
}());
