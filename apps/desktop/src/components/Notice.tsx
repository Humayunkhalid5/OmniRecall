import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react";

interface Props {
  tone: "info" | "warning" | "error" | "success";
  title?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  /** Shows a close button; the parent removes the notice. */
  onDismiss?: () => void;
}

const icons = {
  info: Info,
  warning: TriangleAlert,
  error: CircleAlert,
  success: CircleCheck,
} as const;

export function Notice({ tone, title, children, action, onDismiss }: Props) {
  const Icon = icons[tone];
  return (
    <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon className="notice-icon" size={18} aria-hidden="true" />
      <div className="notice-content">
        {title && <strong>{title}</strong>}
        <div>{children}</div>
      </div>
      {action && <div className="notice-action">{action}</div>}
      {onDismiss && (
        <button
          type="button"
          className="ghost icon-button notice-dismiss"
          aria-label={title ? `Dismiss: ${title}` : "Dismiss"}
          onClick={onDismiss}
        >
          <X size={16} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
