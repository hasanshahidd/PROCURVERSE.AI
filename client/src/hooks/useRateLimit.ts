/**
 * React hook for handling rate limiting in components
 */
import { useState, useEffect, useCallback } from "react";
import {
  globalRateLimitManager,
  formatCountdown,
  type RateLimitInfo
} from "../lib/rateLimit";

export interface UseRateLimitReturn {
  isRateLimited: boolean;
  secondsRemaining: number;
  countdownMessage: string;
  handleRateLimit: (info: RateLimitInfo) => void;
  clearRateLimit: () => void;
}

/**
 * Hook to manage rate limit state in React components
 * 
 * @example
 * const { isRateLimited, countdownMessage, handleRateLimit } = useRateLimit();
 * 
 * const handleSubmit = async () => {
 *   const response = await fetchWithRateLimit('/api/chat', {
 *     method: 'POST',
 *     body: JSON.stringify({ message })
 *   }, handleRateLimit);
 * };
 * 
 * <button disabled={isRateLimited}>
 *   {isRateLimited ? countdownMessage : 'Submit'}
 * </button>
 */
export function useRateLimit(): UseRateLimitReturn {
  const [isRateLimited, setIsRateLimited] = useState(false);
  const [secondsRemaining, setSecondsRemaining] = useState(0);

  // Update state when rate limit changes
  useEffect(() => {
    const checkRateLimit = () => {
      const limited = globalRateLimitManager.isRateLimited();
      const remaining = globalRateLimitManager.getSecondsRemaining();
      
      setIsRateLimited(limited);
      setSecondsRemaining(remaining);
    };

    // Initial check
    checkRateLimit();

    // Subscribe to changes
    const unsubscribe = globalRateLimitManager.subscribe(checkRateLimit);

    // Update countdown every second when rate limited
    let intervalId: number | undefined;
    if (isRateLimited) {
      intervalId = window.setInterval(checkRateLimit, 1000);
    }

    return () => {
      unsubscribe();
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [isRateLimited]);

  const handleRateLimit = useCallback((info: RateLimitInfo) => {
    if (info.isRateLimited && info.retryAfterSeconds) {
      globalRateLimitManager.setRateLimit(info.retryAfterSeconds);
    }
  }, []);

  const clearRateLimit = useCallback(() => {
    globalRateLimitManager.clearRateLimit();
  }, []);

  const countdownMessage = formatCountdown(secondsRemaining);

  return {
    isRateLimited,
    secondsRemaining,
    countdownMessage,
    handleRateLimit,
    clearRateLimit
  };
}
