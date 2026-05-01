export const layoutTokens = {
  sidebarWidth: 260,
  topbarHeight: 64,
  statusbarHeight: 36,
  inspectorWidth: 400,
  inspectorCompactWidth: 360,
  pageX: 32,
  pageY: 24,
  sectionGap: 28,
  sectionInnerGap: 16,
  rowCompact: 44,
  rowDefault: 56,
  rowComfortable: 64,
  rowDetail: 72,
  iconButton: 32,
  buttonHeight: 40,
  chipHeight: 36,
  inputHeight: 40,
  radius: 8,
} as const;

export const colorTokenNames = [
  "canvas",
  "surface",
  "surface-muted",
  "surface-raised",
  "text-primary",
  "text-secondary",
  "text-muted",
  "accent",
  "accent-strong",
  "info",
  "warning",
  "danger",
  "success",
  "focus",
  "border-subtle",
  "border-strong",
] as const;

export type ColorTokenName = (typeof colorTokenNames)[number];

export function cssToken(name: ColorTokenName) {
  return `var(--${name})`;
}
