"""90日を超えた生成監査ログを日次で削除する。"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.audit import delete_expired_audit_logs


def cleanup_audit_logs() -> dict[str, int]:
    deleted_count = delete_expired_audit_logs(90)
    logging.getLogger(__name__).info("Deleted %d expired audit logs", deleted_count)
    return {"deleted_count": deleted_count}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(cleanup_audit_logs()))
