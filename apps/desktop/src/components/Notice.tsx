interface Props {
  tone: "info" | "warning" | "error" | "success";
  title?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}

export function Notice({ tone, title, children, action }: Props) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <div>
        {title && <strong>{title}</strong>}
        <div>{children}</div>
      </div>
      {action && <div className="notice-action">{action}</div>}
    </div>
  );
}
