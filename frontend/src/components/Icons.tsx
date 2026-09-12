/** Иконочный набор: тонкий линейный стиль, один и тот же штрих у всех. */
type P = { size?: number; className?: string }
const base = (size: number) => ({
  width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.7,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
})

export const IconSearch = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" /></svg>
)
export const IconCompass = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5z" /></svg>
)
export const IconChart = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>
)
export const IconPin = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11Z" /><circle cx="12" cy="10" r="2.5" /></svg>
)
export const IconDocs = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h4" /></svg>
)
export const IconPayment = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><rect x="2.5" y="5.5" width="19" height="13" rx="2.5" /><path d="M2.5 10h19M6 14.5h3" /></svg>
)
export const IconClock = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="12" cy="12" r="9" /><path d="M12 7v5.2l3.2 2" /></svg>
)
export const IconCheck = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M20 6 9 17l-5-5" /></svg>
)
export const IconWarning = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 4.5 2.8 20h18.4z" /><path d="M12 10v4M12 17h.01" /></svg>
)
export const IconUsers = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="9" cy="8" r="3.2" /><path d="M2.8 19a6.2 6.2 0 0 1 12.4 0M16.5 5.3a3.2 3.2 0 0 1 0 5.4M18 19a6 6 0 0 0-2-4.3" /></svg>
)
export const IconRoute = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M8.5 6H14a3.5 3.5 0 0 1 0 7h-4a3.5 3.5 0 0 0 0 7h5.5" /></svg>
)
export const IconTag = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M3 12.5V4a1 1 0 0 1 1-1h8.5L21 11.5 12.5 20z" /><circle cx="7.5" cy="7.5" r="1.3" /></svg>
)
export const IconClose = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M18 6 6 18M6 6l12 12" /></svg>
)
export const IconSend = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M4.5 12h14M12.5 5.5 19 12l-6.5 6.5" /></svg>
)
export const IconSpark = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 3.5 13.9 9l5.6 2-5.6 2-1.9 5.5L10.1 13 4.5 11l5.6-2z" /></svg>
)
export const IconBack = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M19 12H5M11.5 5.5 5 12l6.5 6.5" /></svg>
)
export const IconCopy = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5.5 15H5a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 5 3.5h8.5A1.5 1.5 0 0 1 15 5v.5" /></svg>
)
export const IconSun = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="12" cy="12" r="4" /><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8" /></svg>
)
export const IconMoon = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" /></svg>
)
export const IconDatabase = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>
)
export const IconLayers = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="m12 3 9 5-9 5-9-5z" /><path d="m3.5 12.5 8.5 4.7 8.5-4.7" /></svg>
)

export const SECTION_ICONS: Record<string, (p: P) => JSX.Element> = {
  documents: IconDocs, payment: IconPayment, term: IconClock,
  result: IconCheck, reject: IconWarning, recipients: IconUsers,
  ordering: IconRoute, title: IconTag,
}
