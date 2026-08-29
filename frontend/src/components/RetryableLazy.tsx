import { Component, lazy, type ComponentType, type ReactNode } from "react";

type ModuleLoader = () => Promise<Record<string, unknown>>;

export type RetryableLazyComponent = ComponentType & {
  preload: () => Promise<unknown>;
};

export function createRetryableModuleLoader(loader: ModuleLoader, exportName: string, timeoutMs = 15_000) {
  let promise: Promise<{ default: ComponentType }> | undefined;

  return () => {
    if (promise) return promise;

    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(() => reject(new Error(`Page module load timed out after ${timeoutMs}ms`)), timeoutMs);
    });
    const current = Promise.race([Promise.resolve().then(loader), timeout])
      .then((module) => ({ default: module[exportName] as ComponentType }))
      .catch((error) => {
        if (promise === current) promise = undefined;
        throw error;
      })
      .finally(() => {
        if (timeoutId !== undefined) clearTimeout(timeoutId);
      });
    promise = current;
    return current;
  };
}

class RecoverableErrorBoundary extends Component<{
  children: ReactNode;
  onRetry: () => void;
}, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  private retry = () => {
    this.setState({ failed: false });
    this.props.onRetry();
  };

  render() {
    if (!this.state.failed) return this.props.children;
    return <section className="system-state-page" role="alert">
      <span className="system-state-code">LOAD</span>
      <h1>页面暂时无法加载</h1>
      <p>页面资源加载失败，可能是网络中断或系统刚刚更新。请重新加载本页面。</p>
      <div className="system-state-actions">
        <button className="button button-secondary" type="button" onClick={this.retry}>重新加载</button>
      </div>
    </section>;
  }
}

export function retryableLazyNamed(loader: ModuleLoader, exportName: string): RetryableLazyComponent {
  const load = createRetryableModuleLoader(loader, exportName);
  const LazyPage = lazy(load);

  function RetryableLazyPage() {
    return <RecoverableErrorBoundary onRetry={() => window.location.reload()}>
      <LazyPage />
    </RecoverableErrorBoundary>;
  }

  return Object.assign(RetryableLazyPage, { preload: load });
}
