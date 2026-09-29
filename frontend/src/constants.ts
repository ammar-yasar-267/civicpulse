/**
 * Shared domain constants for the frontend.
 *
 * These mirror the backend enums in app/domain/enums.py. They are used as display lists in
 * filter dropdowns and form selects. The values themselves come from the generated
 * schema.d.ts (via the Category/Priority/Status types), but the *ordered arrays* used for
 * rendering dropdowns live here so they are defined in exactly one place.
 *
 * If the backend adds a new category, update app/domain/enums.py, re-run `npm run api:types`
 * to regenerate schema.d.ts, and add the new value here — the TypeScript compiler will flag
 * any mismatch in components that destructure these arrays with `satisfies`.
 */

import type { Category, Priority, Status } from './api/client';

/** All complaint categories in display order. */
export const CATEGORIES: Category[] = [
  'water',
  'electricity',
  'sanitation',
  'roads',
  'streetlights',
  'other',
];

/** All priority levels from most to least urgent. */
export const PRIORITIES: Priority[] = ['high', 'normal', 'low'];

/** All complaint statuses in workflow order. */
export const STATUSES: Status[] = ['open', 'in_progress', 'resolved', 'rejected'];

/** Human-readable labels for display. Replace underscores and title-case each word. */
export function labelOf(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}
