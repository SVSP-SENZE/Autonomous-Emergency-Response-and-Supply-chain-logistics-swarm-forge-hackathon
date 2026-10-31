import type { OrderStatus, Severity, SupplyType, VehicleStatus } from '../types';

export function formatNumber(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatKg(value: number | null | undefined): string {
  return formatNumber(value, 1) === '—' ? '—' : `${formatNumber(value, 1)} kg`;
}

export function formatPercent(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${Number(value).toFixed(decimals)}%`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function titleCase(value: string): string {
  return value
    .split(/[_\s]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export const SUPPLY_LABELS: Record<SupplyType, string> = {
  water_litre: 'Water',
  food_kit: 'Food Kits',
  medical_kit: 'Medical Kits',
  hygiene_kit: 'Hygiene Kits',
};

export function supplyLabel(supplyType: string): string {
  return SUPPLY_LABELS[supplyType as SupplyType] ?? titleCase(supplyType);
}

export const SEVERITY_CLASS: Record<Severity, string> = {
  low: 'sev-low',
  medium: 'sev-medium',
  high: 'sev-high',
  critical: 'sev-critical',
};

export const PRIORITY_CLASS = SEVERITY_CLASS;

export const OPERATIONAL_STATUS_CLASS: Record<string, string> = {
  operational: 'op-operational',
  degraded: 'op-degraded',
  unavailable: 'op-unavailable',
};

export const ORDER_STATUS_CLASS: Record<OrderStatus, string> = {
  draft: 'os-draft',
  awaiting_approval: 'os-awaiting',
  approved: 'os-approved',
  dispatched: 'os-dispatched',
  in_transit: 'os-transit',
  delivered: 'os-delivered',
  cancelled: 'os-cancelled',
  delayed: 'os-delayed',
};

export const VEHICLE_STATUS_CLASS: Record<VehicleStatus, string> = {
  available: 'vs-available',
  assigned: 'vs-assigned',
  in_transit: 'vs-transit',
  delayed: 'vs-delayed',
  maintenance: 'vs-maintenance',
};

/** Severity ranking used to pick the highest-priority active incident. */
export function severityRank(severity: Severity): number {
  return { low: 0, medium: 1, high: 2, critical: 3 }[severity];
}
