export function PrototypePageFrame({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`prototype-page ${className}`.trim()}>{children}</div>;
}

export function PrototypeCardTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return <div className="prototype-card-title"><h3>{children}</h3>{action}</div>;
}
