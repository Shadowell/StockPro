export type ProviderOperationKind = 'refresh' | 'test' | 'mutation';

export interface ProviderOperationState {
  kind: ProviderOperationKind | null;
  epoch: number;
}

export interface ProviderActionStatus {
  message: string;
  providerSignature: string;
  operationEpoch: number;
  operationKind: ProviderOperationKind | null;
}

export const IDLE_PROVIDER_OPERATION: ProviderOperationState = { kind: null, epoch: 0 };

export function createProviderActionStatus(
  message: string,
  providerSignature: string,
  operation: ProviderOperationState,
): ProviderActionStatus {
  return {
    message,
    providerSignature,
    operationEpoch: operation.epoch,
    operationKind: operation.kind,
  };
}

/**
 * Reconcile operation-scoped messages when the parent provider metadata
 * changes. A message from the previous signature is stale once its operation
 * epoch is current or older. A message already associated with the new
 * signature stays visible, including a backend error from a newer operation.
 */
export function reconcileProviderActionStatus(
  current: ProviderActionStatus | null,
  providerSignature: string,
  operation: ProviderOperationState,
): ProviderActionStatus | null {
  if (!current || current.providerSignature === providerSignature) return current;

  const sameEpoch = current.operationEpoch === operation.epoch;
  const currentOperationMatches = sameEpoch && current.operationKind === operation.kind;
  const completedCurrentOperation = sameEpoch && operation.kind === null;
  const olderOperation = current.operationEpoch < operation.epoch;
  if (currentOperationMatches || completedCurrentOperation || olderOperation) return null;
  return current;
}

export function beginProviderOperation(
  current: ProviderOperationState,
  kind: ProviderOperationKind,
): ProviderOperationState {
  return { kind, epoch: current.epoch + 1 };
}

export function finishProviderOperation(
  current: ProviderOperationState,
  operation: ProviderOperationState,
): ProviderOperationState {
  if (current.epoch !== operation.epoch || current.kind !== operation.kind) return current;
  return { kind: null, epoch: current.epoch };
}

export function cancelProviderOperation(current: ProviderOperationState): ProviderOperationState {
  return { kind: null, epoch: current.epoch + 1 };
}

export function isCurrentProviderOperation(
  current: ProviderOperationState,
  operation: ProviderOperationState,
): boolean {
  return current.epoch === operation.epoch && current.kind === operation.kind;
}

export function isProviderOperationBusy(state: ProviderOperationState): boolean {
  return state.kind !== null;
}
