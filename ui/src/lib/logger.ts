// logger.ts

// Determine if we're in browser or server environment
const isBrowser = typeof window !== 'undefined';
const isDevelopment = process.env.NODE_ENV === 'development';

// Helper to get timestamp
function getTimestamp(): string {
  const now = new Date();
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  const seconds = String(now.getSeconds()).padStart(2, '0');
  const ms = String(now.getMilliseconds()).padStart(3, '0');
  return `${hours}:${minutes}:${seconds}.${ms}`;
}

// Helper to get clean caller info (for development)
function getCallerInfo(): string {
  if (!isDevelopment) return '';

  try {
    const err = new Error();
    const stack = err.stack?.split('\n');

    if (!stack || stack.length < 4) return '';

    // Look for the first non-logger file in the stack
    for (let i = 3; i < Math.min(stack.length, 10); i++) {
      const line = stack[i];

      // Skip logger.ts itself and node internals
      if (line.includes('logger.ts') ||
          line.includes('logger.js') ||
          line.includes('node_modules') ||
          line.includes('node:') ||
          line.includes('webpack-internal') ||
          line.includes('<anonymous>')) continue;

      // Try multiple patterns to extract file info
      const patterns = [
        // Standard stack trace pattern
        /(?:at\s+.*?\s+\(|at\s+)(.*?):(\d+):(\d+)\)?/,
        // Webpack pattern
        /at\s+(?:async\s+)?(?:.*?\s+)?(?:\()?webpack-internal:\/\/\/(?:\.\/)?(.+?):(\d+):(\d+)/,
        // Next.js server component pattern
        /at\s+(?:async\s+)?(?:.*?\s+)?(?:\()?(.+?):(\d+):(\d+)/
      ];

      for (const pattern of patterns) {
        const match = line.match(pattern);
        if (match) {
          let filePath = match[1];
          const lineNum = match[2];

          // Clean up various path formats
          filePath = filePath
            // Handle file:// URLs from source maps
            .replace(/^file:\/\//, '')
            // Remove webpack prefixes
            .replace(/^webpack-internal:\/\/\/(?:\.\/)?\(rsc\)\/(?:\.\/)/, '')
            .replace(/^webpack-internal:\/\/\/(?:\.\/)/, '')
            // Remove absolute paths to make them relative
            .replace(/^.*\/dograh\/ui\//, '')
            // Remove .next build paths
            .replace(/.*\.next\/server\/app\//, 'app/')
            .replace(/.*\.next\/server\//, '')
            // Clean up app directory paths
            .replace(/^app\//, '')
            // Remove query strings
            .replace(/\?.*$/, '')
            // Clean up compiled chunk names - extract the likely source
            .replace(/chunks\/ssr\/_?[a-f0-9]+_?\.?/, '')
            .replace(/_[a-f0-9]{6,}\./, '.')
            // Try to infer original file from common patterns
            .replace(/^([a-z0-9]+)\._.js$/, (_, name) => {
              // Common Next.js page mappings
              if (name === 'page') return 'page.tsx';
              return `${name}.ts`;
            });

          // If we still have a chunk-like name, try to make it more readable
          if (filePath.match(/^_?[a-f0-9]+_?\./)) {
            // This is likely a compiled chunk, extract what we can
            const cleanMatch = line.match(/at\s+(?:async\s+)?(\w+)/);
            if (cleanMatch && cleanMatch[1] !== 'async') {
              // Use the function name as a hint
              const funcName = cleanMatch[1];
              if (funcName === 'Home') filePath = 'page.tsx';
              else if (funcName.includes('Page')) filePath = `${funcName.replace('Page', '').toLowerCase()}/page.tsx`;
              else filePath = `${funcName}.tsx`;
            }
          }

          // No need to add prefixes since we have clean relative paths from source maps

          return `${filePath}:${lineNum}`;
        }
      }
    }

    return '';
  } catch {
    return '';
  }
}

// Color codes for terminal output
const colors = {
  reset: '\x1b[0m',
  dim: '\x1b[2m',
  bright: '\x1b[1m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
};

// Format log level with color
function formatLevel(level: string): string {
  if (!isDevelopment || isBrowser) return level.toUpperCase();

  switch (level) {
    case 'debug':
      return `${colors.gray}DEBUG${colors.reset}`;
    case 'info':
      return `${colors.cyan}INFO${colors.reset}`;
    case 'warn':
      return `${colors.yellow}WARN${colors.reset}`;
    case 'error':
      return `${colors.red}ERROR${colors.reset}`;
    default:
      return level.toUpperCase();
  }
}

// Wrapper interface that matches existing usage
interface Logger {
  debug: (...args: unknown[]) => void;
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
}

// Server-side logging function
function serverLog(level: string, args: unknown[]): void {
  const timestamp = getTimestamp();
  const caller = getCallerInfo();
  const levelStr = formatLevel(level);

  // Format the message
  const message = args.map(arg => {
    if (arg instanceof Error) {
      return `${arg.message}\n${arg.stack}`;
    }
    return typeof arg === 'object' ? JSON.stringify(arg, null, 2) : String(arg);
  }).join(' ');

  // Build the log line
  const prefix = `${colors.gray}[${timestamp}]${colors.reset} ${levelStr}`;
  const callerInfo = caller ? ` ${colors.dim}[${caller}]${colors.reset}` : '';

  // Use appropriate console method
  switch (level) {
    case 'debug':
      console.debug(`${prefix}${callerInfo} ${message}`);
      break;
    case 'info':
      console.info(`${prefix}${callerInfo} ${message}`);
      break;
    case 'warn':
      console.warn(`${prefix}${callerInfo} ${message}`);
      break;
    case 'error':
      console.error(`${prefix}${callerInfo} ${message}`);
      break;
  }
}

// Create a wrapper that adds caller info and handles multiple arguments
const logger: Logger = {
  debug: (...args: unknown[]): void => {
    if (!isDevelopment) return;

    if (isBrowser) {
      const caller = getCallerInfo();
      console.debug(`[DEBUG] [${caller}]`, ...args);
    } else {
      serverLog('debug', args);
    }
  },

  info: (...args: unknown[]): void => {
    if (isBrowser) {
      const caller = getCallerInfo();
      console.info(`[INFO] [${caller}]`, ...args);
    } else {
      serverLog('info', args);
    }
  },

  warn: (...args: unknown[]): void => {
    if (isBrowser) {
      const caller = getCallerInfo();
      console.warn(`[WARN] [${caller}]`, ...args);
    } else {
      serverLog('warn', args);
    }
  },

  error: (...args: unknown[]): void => {
    if (isBrowser) {
      const caller = getCallerInfo();
      console.error(`[ERROR] [${caller}]`, ...args);
    } else {
      serverLog('error', args);
    }
  },
};

export default logger;
