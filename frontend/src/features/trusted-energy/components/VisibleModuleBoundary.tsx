import { useEffect, useRef, useState, type ReactNode } from "react";
import { RemoteState } from "./ui-primitives";

type VisibleModuleBoundaryProps<Module> = {
  loader: () => Promise<Module>;
  className: string;
  ariaLabel: string;
  renderLoaded: (module: Module) => ReactNode;
};

export function VisibleModuleBoundary<Module>({ loader, className, ariaLabel, renderLoaded }: VisibleModuleBoundaryProps<Module>) {
  const boundaryRef = useRef<HTMLDivElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ module?: Module; error?: string }>({});

  useEffect(() => {
    const target = boundaryRef.current;
    if (!target) return undefined;
    let active = true;
    const load = () => {
      void loader()
        .then((module) => { if (active) setState({ module }); })
        .catch((error) => { if (active) setState({ error: error instanceof Error ? error.message : "图表资源加载失败" }); });
    };

    if (!("IntersectionObserver" in window)) {
      load();
      return () => { active = false; };
    }

    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      load();
    }, { rootMargin: "160px" });
    observer.observe(target);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [attempt, loader]);

  if (state.module) return renderLoaded(state.module);
  return <div ref={boundaryRef} className={className} role="region" aria-label={ariaLabel} aria-busy={!state.error || undefined}>
    <RemoteState
      loading={!state.error}
      error={state.error}
      onRetry={state.error ? () => { setState({}); setAttempt((value) => value + 1); } : undefined}
    />
  </div>;
}
