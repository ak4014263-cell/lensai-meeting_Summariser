"""CSV export for meeting action items (compatible with Jira, Asana, Monday, Excel)."""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List


def export_action_items_csv(action_items: List[Dict[str, Any]], meeting_title: str = "") -> str:
    """Export action items into standard CSV format."""
    output = io.StringIO()
    fieldnames = ["Meeting", "Task", "Assignee", "Deadline", "Priority", "Context Quote"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for item in action_items:
        writer.writerow({
            "Meeting": meeting_title,
            "Task": item.get("task", ""),
            "Assignee": item.get("assignee") or "Unassigned",
            "Deadline": item.get("deadline") or "",
            "Priority": item.get("priority", "medium"),
            "Context Quote": item.get("context_quote") or "",
        })

    return output.getvalue()
