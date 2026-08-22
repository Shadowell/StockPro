interface TogglePreferredStrategyInput {
  instanceId: string;
  automaticIds: ReadonlySet<string>;
  dismissedAutomaticIds: ReadonlySet<string>;
  favoriteIds: ReadonlySet<string>;
}

interface TogglePreferredStrategyResult {
  dismissedAutomaticIds: Set<string>;
  favoriteIds: Set<string>;
}

export function togglePreferredStrategy({
  instanceId,
  automaticIds,
  dismissedAutomaticIds,
  favoriteIds,
}: TogglePreferredStrategyInput): TogglePreferredStrategyResult {
  const nextDismissedAutomaticIds = new Set(dismissedAutomaticIds);
  const nextFavoriteIds = new Set(favoriteIds);

  if (automaticIds.has(instanceId)) {
    if (nextDismissedAutomaticIds.has(instanceId)) {
      nextDismissedAutomaticIds.delete(instanceId);
    } else {
      nextDismissedAutomaticIds.add(instanceId);
      nextFavoriteIds.delete(instanceId);
    }
  } else if (nextFavoriteIds.has(instanceId)) {
    nextFavoriteIds.delete(instanceId);
  } else {
    nextFavoriteIds.add(instanceId);
  }

  return {
    dismissedAutomaticIds: nextDismissedAutomaticIds,
    favoriteIds: nextFavoriteIds,
  };
}
