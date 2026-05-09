import type { LucideIcon } from "lucide-react";

export function Button({
  icon: Icon,
  label,
  primary,
  danger,
  onClick,
  disabled,
}: {
  icon: LucideIcon;
  label: string;
  primary?: boolean;
  danger?: boolean;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      className={`button ${primary ? "button--primary" : ""} ${danger ? "button--danger" : ""}`}
      type="button"
      onClick={onClick}
      disabled={disabled}
    >
      <Icon size={17} />
      {label}
    </button>
  );
}

export function IconButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
}) {
  return (
    <button className="icon-button" type="button" aria-label={label} title={label} onClick={onClick}>
      <Icon size={18} />
    </button>
  );
}
