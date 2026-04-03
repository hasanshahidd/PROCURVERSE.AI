/**
 * Rate Limit Error Handler
 * 
 * Handles 429 Too Many Requests responses with user-friendly messages
 * and automatic retry timing.
 */

export interface RateLimitInfo {
  isRateLimited: boolean;
  retryAfterSeconds?: number;
  limit?: number;
  reset?: number;
  message: string;
}

/**
 * Parse rate limit headers from a fetch response
 */
export function parseRateLimitHeaders(response: Response): RateLimitInfo {
  if (response.status !== 429) {
    return {
      isRateLimited: false,
      message: ""
    };
  }

  const retryAfter = response.headers.get("Retry-After");
  const limit = response.headers.get("X-RateLimit-Limit");
  const reset = response.headers.get("X-RateLimit-Reset");

  const retryAfterSeconds = retryAfter ? parseInt(retryAfter, 10) : 60;
  const limitNumber = limit ? parseInt(limit, 10) : undefined;
  const resetNumber = reset ? parseInt(reset, 10) : undefined;

  return {
    isRateLimited: true,
    retryAfterSeconds,
    limit: limitNumber,
    reset: resetNumber,
    message: formatRateLimitMessage(retryAfterSeconds)
  };
}

/**
 * Format a user-friendly rate limit message
 */
export function formatRateLimitMessage(retryAfterSeconds: number): string {
  if (retryAfterSeconds < 60) {
    return `Too many requests. Please wait ${retryAfterSeconds} seconds before trying again.`;
  }
  
  const minutes = Math.ceil(retryAfterSeconds / 60);
  return `Too many requests. Please wait ${minutes} minute${minutes > 1 ? 's' : ''} before trying again.`;
}

/**
 * Fetch wrapper with rate limit handling
 * 
 * @example
 * const result = await fetchWithRateLimit('/api/chat', {
 *   method: 'POST',
 *   body: JSON.stringify({ message: 'Hello' })
 * }, (info) => {
 *   toast({ 
 *     title: "Rate Limited", 
 *     description: info.message,
 *     variant: "destructive"
 *   });
 * });
 */
export async function fetchWithRateLimit(
  url: string,
  options?: RequestInit,
  onRateLimited?: (info: RateLimitInfo) => void
): Promise<Response> {
  const response = await fetch(url, options);

  if (response.status === 429) {
    const info = parseRateLimitHeaders(response);
    
    if (onRateLimited) {
      onRateLimited(info);
    }
    
    // Log for debugging
    console.warn(`[RATE LIMIT] ${info.message}`, {
      retryAfter: info.retryAfterSeconds,
      limit: info.limit,
      reset: info.reset
    });
  }

  return response;
}

/**
 * Hook-style rate limit state manager
 * Use with React components to track rate limit status
 */
export class RateLimitManager {
  private rateLimitedUntil: number | null = null;
  private listeners: Set<() => void> = new Set();

  /**
   * Check if currently rate limited
   */
  isRateLimited(): boolean {
    if (this.rateLimitedUntil === null) return false;
    
    const now = Date.now();
    if (now >= this.rateLimitedUntil) {
      this.rateLimitedUntil = null;
      this.notify();
      return false;
    }
    
    return true;
  }

  /**
   * Get seconds remaining until rate limit expires
   */
  getSecondsRemaining(): number {
    if (!this.isRateLimited()) return 0;
    return Math.ceil((this.rateLimitedUntil! - Date.now()) / 1000);
  }

  /**
   * Set rate limit based on retry-after seconds
   */
  setRateLimit(retryAfterSeconds: number): void {
    this.rateLimitedUntil = Date.now() + (retryAfterSeconds * 1000);
    this.notify();
  }

  /**
   * Clear rate limit manually
   */
  clearRateLimit(): void {
    this.rateLimitedUntil = null;
    this.notify();
  }

  /**
   * Subscribe to rate limit state changes
   */
  subscribe(callback: () => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  private notify(): void {
    this.listeners.forEach(listener => listener());
  }
}

/**
 * Global rate limit manager instance
 * Use across your application to track rate limit state
 */
export const globalRateLimitManager = new RateLimitManager();

/**
 * Format countdown timer display
 * @example "Please wait 45 seconds" or "Please wait 2:30"
 */
export function formatCountdown(seconds: number): string {
  if (seconds < 60) {
    return `Please wait ${seconds} second${seconds !== 1 ? 's' : ''}`;
  }
  
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `Please wait ${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
}
