export interface CallController {
  toggleCall(): Promise<void>;
  toggleMute(): void;
  sendTextMessage(): void;
  handleKey(event: { key: string }): void;
  destroy(): void;
  getMeasurements(): Record<string, unknown>;
  downloadMeasurements(): void;
}
export function createCallSimulator(
  root: HTMLElement | Document,
  options: { agent?: { id: string; config: Record<string, any> }; draft?: boolean },
): CallController;
