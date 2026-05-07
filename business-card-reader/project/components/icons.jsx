// SVG icon set for Business Card Reader UI
const Icons = {
  scan: (props) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" {...props}>
      <rect x="1" y="4" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="1.5"/>
      <rect x="13" y="4" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="1.5"/>
      <rect x="1" y="10" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M9 2v14M2 9h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  contacts: (props) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" {...props}>
      <circle cx="9" cy="6" r="3" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M2 16c0-3.314 3.134-6 7-6s7 2.686 7 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  history: (props) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" {...props}>
      <path d="M9 5v4l2.5 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M3.5 9A5.5 5.5 0 1 0 5 5.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M1 5.5l2 2 2-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  upload: (props) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...props}>
      <path d="M10 13V3M6 7l4-4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M3 14v2a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  settings: (props) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" {...props}>
      <circle cx="9" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M9 1v2M9 15v2M1 9h2M15 9h2M3.1 3.1l1.4 1.4M13.5 13.5l1.4 1.4M3.1 14.9l1.4-1.4M13.5 4.5l1.4-1.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  check: (props) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" {...props}>
      <path d="M3 8l3.5 3.5L13 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  download: (props) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" {...props}>
      <path d="M8 3v7M5 7l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M2 12v1a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  search: (props) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" {...props}>
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  trash: (props) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" {...props}>
      <path d="M2 4h12M6 4V2h4v2M5 4l.5 9h5l.5-9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  edit: (props) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" {...props}>
      <path d="M11 2l3 3-8 8H3v-3l8-8z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  close: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  chevronRight: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  chevronDown: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M3 5l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  card: (props) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" {...props}>
      <rect x="1" y="3" width="16" height="12" rx="2" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M1 7h16" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M5 12h3M5 10h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  email: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <rect x="1" y="2.5" width="12" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M1 4l6 4 6-4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  ),
  phone: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M4.5 1.5h-2a1 1 0 0 0-1 1 10 10 0 0 0 10 10 1 1 0 0 0 1-1v-2l-2.5-1L9 9.5s-2.5-1-3-3l1-1.5L5.5 2.5l-1-1z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  globe: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M7 1.5c0 0-2.5 2-2.5 5.5s2.5 5.5 2.5 5.5M7 1.5c0 0 2.5 2 2.5 5.5S7 12.5 7 12.5" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M1.5 7h11" stroke="currentColor" strokeWidth="1.3"/>
    </svg>
  ),
  building: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <rect x="2" y="1.5" width="10" height="11" rx="1" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M5 4.5h1M8 4.5h1M5 7h1M8 7h1M5 9.5h1M8 9.5h1" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  ),
  linkedin: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <rect x="1" y="1" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M4 6v4M4 4.5v.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M7 10V7.5a1.5 1.5 0 0 1 3 0V10M7 6v4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  ),
  qr: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <rect x="1" y="1" width="4" height="4" rx="0.5" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="9" y="1" width="4" height="4" rx="0.5" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="1" y="9" width="4" height="4" rx="0.5" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M9 9h1M12 9h1M9 12h1M12 12h1M9 10.5h4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
      <path d="M2.5 2.5h1v1h-1zM10.5 2.5h1v1h-1zM2.5 10.5h1v1h-1z" fill="currentColor"/>
    </svg>
  ),
  cpu: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <rect x="3" y="3" width="8" height="8" rx="1" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M5 1v2M7 1v2M9 1v2M5 11v2M7 11v2M9 11v2M1 5h2M1 7h2M1 9h2M11 5h2M11 7h2M11 9h2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  ),
  spark: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M7 1l1.5 4H13l-3.5 2.5 1.5 4.5L7 9.5 3 12l1.5-4.5L1 5h4.5L7 1z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
    </svg>
  ),
  plus: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  refresh: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M12 7A5 5 0 1 1 9 2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
      <path d="M9 1v3h3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  filter: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M2 3h10M4 7h6M6 11h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  grid: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <rect x="1" y="1" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="8" y="1" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="1" y="8" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="8" y="8" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.3"/>
    </svg>
  ),
  list: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M5 3h7M5 7h7M5 11h7M2 3h.1M2 7h.1M2 11h.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  bolt: (props) => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" {...props}>
      <path d="M8 1L3 8h4.5L5 13l6-7H6.5L8 1z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
    </svg>
  ),
  lock: (props) => (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" {...props}>
      <rect x="2" y="6" width="9" height="6.5" rx="1" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M4 6V4.5a2.5 2.5 0 0 1 5 0V6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  ),
};

Object.assign(window, { Icons });
