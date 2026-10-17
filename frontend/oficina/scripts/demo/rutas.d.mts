export declare const MARKER: string;
export declare const DEFAULT_DIR_NAME: string;
export declare function defaultDemoDir(env?: NodeJS.ProcessEnv): string;
export declare function defaultRealDbDir(env?: NodeJS.ProcessEnv, platform?: NodeJS.Platform): string;
export declare function checkDemoDir(
  dir: string,
  options?: { env?: NodeJS.ProcessEnv; repoRoot?: string; platform?: NodeJS.Platform },
): string[];
export declare function isDemoDir(dir: string): boolean;
export declare function lastClosedUtcDay(now?: Date): string;
