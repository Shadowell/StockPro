import { useCallback, useEffect, useRef, useState } from 'react';

interface UsePollingOptions<T> {
  fetchFn: () => Promise<T>;
  shouldPoll: boolean;
  onSuccess?: (data: T) => void;
  onError?: (error: Error) => void;
  initialInterval?: number;
  maxInterval?: number;
  backoffMultiplier?: number;
  backoffAfterPolls?: number;
  maxConsecutiveErrors?: number;
}

interface UsePollingReturn {
  isPolling: boolean;
  error: Error | null;
  consecutiveErrors: number;
  currentInterval: number;
  manualRefresh: () => void;
  resetBackoff: () => void;
}

/**
 * Smart polling hook with exponential backoff
 * 
 * Features:
 * - Initial fast polling (1s by default)
 * - Exponential backoff after N polls (interval doubles)
 * - Smart recovery: reset to fast polling when data changes
 * - Auto cleanup on unmount
 * - Error handling with backoff on consecutive failures
 */
export function usePolling<T>({
  fetchFn,
  shouldPoll,
  onSuccess,
  onError,
  initialInterval = 1000,
  maxInterval = 10000,
  backoffMultiplier = 2,
  backoffAfterPolls = 5,
  maxConsecutiveErrors = 3,
}: UsePollingOptions<T>): UsePollingReturn {
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [consecutiveErrors, setConsecutiveErrors] = useState(0);
  const [currentInterval, setCurrentInterval] = useState(initialInterval);
  
  const pollCountRef = useRef(0);
  const timeoutRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const lastDataRef = useRef<string | null>(null);

  const clearPollingTimeout = useCallback(() => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const resetBackoff = useCallback(() => {
    pollCountRef.current = 0;
    setCurrentInterval(initialInterval);
    setConsecutiveErrors(0);
    setError(null);
  }, [initialInterval]);

  const calculateNextInterval = useCallback((pollCount: number, errors: number): number => {
    // If we have consecutive errors, back off more aggressively
    if (errors > 0) {
      const errorBackoff = initialInterval * Math.pow(backoffMultiplier, errors);
      return Math.min(errorBackoff, maxInterval);
    }

    // Normal backoff after N polls
    if (pollCount > 0 && pollCount % backoffAfterPolls === 0) {
      const backoffFactor = Math.floor(pollCount / backoffAfterPolls);
      const newInterval = initialInterval * Math.pow(backoffMultiplier, backoffFactor);
      return Math.min(newInterval, maxInterval);
    }

    return currentInterval;
  }, [initialInterval, maxInterval, backoffMultiplier, backoffAfterPolls, currentInterval]);

  const poll = useCallback(async () => {
    if (!mountedRef.current || !shouldPoll) {
      setIsPolling(false);
      return;
    }

    setIsPolling(true);

    try {
      const data = await fetchFn();
      
      if (!mountedRef.current) return;

      // Check if data changed - if so, reset backoff for faster updates
      const dataString = JSON.stringify(data);
      if (lastDataRef.current !== null && lastDataRef.current !== dataString) {
        // Data changed, reset to fast polling
        pollCountRef.current = 0;
        setCurrentInterval(initialInterval);
      }
      lastDataRef.current = dataString;

      setError(null);
      setConsecutiveErrors(0);
      onSuccess?.(data);

      pollCountRef.current++;
      const nextInterval = calculateNextInterval(pollCountRef.current, 0);
      setCurrentInterval(nextInterval);

      // Schedule next poll
      if (shouldPoll && mountedRef.current) {
        timeoutRef.current = window.setTimeout(poll, nextInterval);
      }
    } catch (err) {
      if (!mountedRef.current) return;

      const error = err instanceof Error ? err : new Error('Polling failed');
      setError(error);
      
      const newErrorCount = consecutiveErrors + 1;
      setConsecutiveErrors(newErrorCount);
      onError?.(error);

      // Stop polling after too many consecutive errors
      if (newErrorCount >= maxConsecutiveErrors) {
        console.warn(`[usePolling] Stopped after ${newErrorCount} consecutive errors`);
        setIsPolling(false);
        return;
      }

      // Back off on error
      const nextInterval = calculateNextInterval(pollCountRef.current, newErrorCount);
      setCurrentInterval(nextInterval);

      // Schedule retry
      if (shouldPoll && mountedRef.current) {
        timeoutRef.current = window.setTimeout(poll, nextInterval);
      }
    }
  }, [
    fetchFn,
    shouldPoll,
    onSuccess,
    onError,
    initialInterval,
    maxConsecutiveErrors,
    consecutiveErrors,
    calculateNextInterval,
  ]);

  const manualRefresh = useCallback(() => {
    clearPollingTimeout();
    resetBackoff();
    poll();
  }, [clearPollingTimeout, resetBackoff, poll]);

  // Start/stop polling based on shouldPoll
  useEffect(() => {
    mountedRef.current = true;

    if (shouldPoll) {
      // Start polling immediately
      poll();
    } else {
      clearPollingTimeout();
      setIsPolling(false);
    }

    return () => {
      mountedRef.current = false;
      clearPollingTimeout();
    };
  }, [shouldPoll]); // Only depend on shouldPoll to avoid infinite loops

  return {
    isPolling,
    error,
    consecutiveErrors,
    currentInterval,
    manualRefresh,
    resetBackoff,
  };
}

export default usePolling;
