import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

const SELECT_MENU_OPEN_EVENT = "memwing-select-menu-open";

export function SelectMenu({
  label,
  value,
  options,
  className,
  onChange,
}: {
  label?: string;
  value: string;
  options: string[];
  className: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    function closeForExternalOpen(event: Event) {
      if ((event as CustomEvent<string>).detail !== menuId) {
        setOpen(false);
      }
    }

    function closeForOutsidePointer(event: Event) {
      const target = event.target;
      if (target instanceof Node && rootRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    }

    window.addEventListener(SELECT_MENU_OPEN_EVENT, closeForExternalOpen as EventListener);
    window.addEventListener("pointerdown", closeForOutsidePointer, true);
    return () => {
      window.removeEventListener(SELECT_MENU_OPEN_EVENT, closeForExternalOpen as EventListener);
      window.removeEventListener("pointerdown", closeForOutsidePointer, true);
    };
  }, [menuId, open]);

  return (
    <div
      ref={rootRef}
      className={`${className} ${open ? "is-open" : ""}`}
      onBlur={(event) => {
        const nextTarget = event.relatedTarget;
        if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
          return;
        }
        setOpen(false);
      }}
    >
      <button
        className={`${className}__button`}
        type="button"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => {
          setOpen((current) => {
            const nextOpen = !current;
            if (nextOpen) {
              window.dispatchEvent(new CustomEvent<string>(SELECT_MENU_OPEN_EVENT, { detail: menuId }));
            }
            return nextOpen;
          });
        }}
      >
        <span className={`${className}__content`}>
          {label ? <span className={`${className}__label`}>{label}</span> : null}
          <span className={`${className}__value`}>{value}</span>
        </span>
        <ChevronDown size={16} />
      </button>
      {open ? (
        <div className={`${className}__menu`} id={menuId} role="listbox">
          {options.map((option) => (
            <button
              key={option}
              className={option === value ? "is-active" : ""}
              type="button"
              role="option"
              aria-selected={option === value}
              onClick={() => {
                onChange(option);
                setOpen(false);
              }}
            >
              {option}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
