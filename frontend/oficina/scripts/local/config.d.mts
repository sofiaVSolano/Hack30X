export declare function checkConfigPath(path: string, options?: { env?: NodeJS.ProcessEnv; repoRoot?: string }): string[];
export declare function parseConfig(text: string): { values: Record<string, string>; errors: string[] };
export declare function projectEnvWithToken(dir: string, names: string[], read: (file: string) => string): string[];
