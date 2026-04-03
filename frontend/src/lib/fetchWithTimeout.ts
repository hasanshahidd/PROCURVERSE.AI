/**
 * Fetch Wrapper with Timeout
 * Prevents hanging requests by aborting after specified duration
 * 
 * Usage:
 *   const data = await fetchWithTimeout('/api/endpoint', { method: 'POST' }, 30000);
 */

export interface FetchWithTimeoutOptions extends RequestInit {
  timeout?: number;  // Timeout in milliseconds (default: 30000)
}

export class TimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TimeoutError';
  }
}

/**
 * Fetch with automatic timeout and abort
 * @param url - URL to fetch
 * @param options - Fetch options with optional timeout
 * @returns Response promise that rejects on timeout
 */
export async function fetchWithTimeout(
  url: string,
  options: FetchWithTimeoutOptions = {},
  timeoutMs: number = 30000
): Promise<Response> {
  const { timeout = timeoutMs, ...fetchOptions } = options;
  
  // Create AbortController for timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  
  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    return response;
    
  } catch (error: any) {
    clearTimeout(timeoutId);
    
    if (error.name === 'AbortError') {
      throw new TimeoutError(
        `Request timed out after ${timeout / 1000} seconds. The server may be busy. Please try again.`
      );
    }
    
    throw error;
  }
}

/**
 * Fetch JSON with timeout
 * @param url - URL to fetch
 * @param options - Fetch options
 * @returns Parsed JSON response or throws TimeoutError
 */
export async function fetchJsonWithTimeout<T = any>(
  url: string,
  options: FetchWithTimeoutOptions = {},
  timeoutMs: number = 30000
): Promise<T> {
  const response = await fetchWithTimeout(url, options, timeoutMs);
  
  if (!response.ok) {
    if (response.status === 504) {
      throw new TimeoutError('Server timeout. Your request took too long to process. Try simplifying your query.');
    }
    const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
    throw new Error(errorData.error || errorData.message || `HTTP ${response.status}`);
  }
  
  return response.json();
}
