/**
 * Presentational badges.
 *
 * These map a server-supplied value to a colour and a label. That is presentation, which the
 * frontend owns. What they deliberately do NOT do is decide anything: no priority ranking is
 * computed here, no category is inferred, and no status transition is judged. The moment this
 * file contains a rule, there are two sources of truth and one of them will rot (§2.1).
 */

import type { Category, Priority, Status } from '../api/client';

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={`badge badge-priority-${priority}`} data-testid="priority-badge">
      {priority}
    </span>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge badge-status-${status}`} data-testid="status-badge">
      {status.replace('_', ' ')}
    </span>
  );
}

export function CategoryBadge({ category }: { category: Category }) {
  return <span className={`badge badge-category-${category}`}>{category}</span>;
}
