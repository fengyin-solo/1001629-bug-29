"""载重平衡业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "loadsheet"
REQUIRED_FIELDS = ["配载单号", "关联航班", "计算重量"]
DETAIL_FIELDS = ["关联航班", "计算重量", "重心位置", "油量数据", "配载人员"]
LOAD_EDIT_FIELDS = ["关联航班", "计算重量", "重心位置", "油量数据"]
REVIEW_FIELDS = ["复核人员", "复核意见", "复核结论", "结论复核人员", "复核签字", "复核记录"]
STATUS_DRAFT = "待计算"
STATUS_PENDING = "待复核"
STATUS_CONFIRMED = "已确认"
STATUS_RETURNED = "已退回"
STATUS_ORDER = [STATUS_DRAFT, STATUS_PENDING, STATUS_CONFIRMED, STATUS_RETURNED]
ACTION_RULES = {"提交复核": STATUS_PENDING, "确认配载": STATUS_CONFIRMED, "退回重算": STATUS_RETURNED}
NEGATIVE_ACTIONS = ["退回重算"]
PLANNER_ROLE = "配载人员"
REVIEWER_ROLE = "复核人员"
DEFAULT_REVIEWER = "值班复核人员"


class LoadsheetService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._query_rows(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_summary(self, *, keyword: str | None = None, status: str | None = None) -> dict[str, int | float]:
        rows = self._query_rows(keyword=keyword, status=status)
        confirmed_rows = [row for row in rows if row.get("status") == STATUS_CONFIRMED]
        return {
            "待复核配载": sum(1 for row in rows if row.get("status") == STATUS_PENDING),
            "配载单总数": len(rows),
            "退回重算数": sum(1 for row in rows if row.get("status") == STATUS_RETURNED),
            "已确认配载数": len(confirmed_rows),
            "已确认计算重量": sum(self._to_number(row.get("计算重量")) for row in confirmed_rows),
            "已确认重心配载数": sum(1 for row in confirmed_rows if self._has_value(row.get("重心位置"))),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        order_no = str(values.get("配载单号") or "").strip()
        if any(str(row.get("配载单号") or "").strip() == order_no for row in rows):
            return None, [f"配载单号 {order_no} 已存在，不能重复建单"]

        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = values.get(field)
        for field in DETAIL_FIELDS:
            entry.setdefault(field, values.get(field) if self._has_value(values.get(field)) else None)
        if not self._has_value(entry.get("配载人员")):
            entry["配载人员"] = None

        entry.update({
            "status": STATUS_DRAFT,
            "配载状态": STATUS_DRAFT,
            "pending": True,
            "abnormal": False,
            "只读": False,
            "重心位置": entry.get("重心位置"),
            "油量数据": entry.get("油量数据"),
            "复核人员": None,
            "复核意见": None,
            "复核结论": None,
            "结论复核人员": None,
            "复核签字": None,
            "复核记录": [],
        })
        rows.append(entry)
        return entry, []

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        *,
        operator: str | None = None,
        role: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"配载单 {entry_id} 不存在或已归档"
        account = str(operator or "").strip()
        account_role = str(role or "").strip()
        if account_role not in {PLANNER_ROLE, REVIEWER_ROLE}:
            return None, "缺少配载人员或复核人员账号，不能修改配载单"

        if account_role == PLANNER_ROLE:
            if entry.get("status") != STATUS_DRAFT:
                return None, "配载单提交后对配载人员只读，退回单也不能改动复核结论"
            planner = str(entry.get("配载人员") or "").strip()
            if account and planner and account != planner:
                return None, "只有该单配载人员可以在提交前修改配载数据"
            forbidden = [field for field in values if field in REVIEW_FIELDS or field in {"status", "pending", "abnormal", "只读"}]
            if forbidden:
                return None, "配载人员不能改动复核字段或流程状态"
            for field in LOAD_EDIT_FIELDS:
                if field in values:
                    entry[field] = values.get(field)
            return entry, "配载数据已更新"

        if entry.get("status") != STATUS_PENDING:
            return None, "复核结论一经提交即锁定，接收退回的账号不能改动复核结论"
        forbidden = [field for field in values if field in REVIEW_FIELDS or field in LOAD_EDIT_FIELDS]
        if forbidden:
            return None, "复核人员只能通过确认或退回动作形成复核结论"
        return entry, "复核中的配载单请使用复核动作填写结论"

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str | None = None,
        role: str | None = None,
        opinion: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"配载单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于载重平衡可执行范围"

        account = str(operator or "").strip()
        account_role = str(role or "").strip()
        comment = str(opinion or "").strip() or None
        current_status = str(entry.get("status") or "")
        current_planner = str(entry.get("配载人员") or "").strip() or None

        if action == "提交复核":
            if account_role and account_role != PLANNER_ROLE:
                return None, "只有配载人员可以提交复核"
            planner = account or str(entry.get("配载人员") or "").strip()
            if not planner:
                return None, "缺少配载人员账号，不能提交复核"
            if str(entry.get("配载人员") or "").strip() and planner != str(entry.get("配载人员") or "").strip():
                return None, "只有该单配载人员可以提交复核"
            if current_status == STATUS_PENDING:
                return None, "该配载单已在待复核队列，不能重复提交"
            if current_status != STATUS_DRAFT:
                return None, "已确认或已退回的配载单为只读单据，如需重算请新建配载单"

            record = {
                "结论": STATUS_PENDING,
                "提交人": planner,
                "复核人员": None,
                "复核意见": None,
                "签字": False,
                "时间": self._now(),
            }
            entry.setdefault("复核记录", []).append(record)
            entry.update({
                "复核人员": None,
                "复核意见": None,
                "复核结论": STATUS_PENDING,
                "结论复核人员": None,
                "复核签字": None,
            })
            self._set_status(entry, STATUS_PENDING)
            return entry, "配载单已提交复核"

        if account_role and account_role != REVIEWER_ROLE:
            return None, "只有复核人员可以确认或退回配载单"
        if current_status != STATUS_PENDING:
            return None, f"配载单当前为{current_status}，不能重复形成复核结论"
        reviewer = account or DEFAULT_REVIEWER
        if action == "退回重算" and not comment:
            return None, "退回重算必须填写复核意见"

        target = ACTION_RULES[action]
        action_time = self._now()
        record = self._open_review_record(entry, planner=current_planner)
        record.update({
            "结论": target,
            "复核人员": reviewer,
            "复核意见": comment,
            "签字": target == STATUS_CONFIRMED,
            "时间": action_time,
        })

        if target == STATUS_CONFIRMED:
            entry.update({
                "复核人员": reviewer,
                "复核意见": comment,
                "复核结论": STATUS_CONFIRMED,
                "结论复核人员": reviewer,
                "复核签字": f"{reviewer} {action_time}",
            })
        else:
            # 退回意见保留给配载人员查看，但待办队列中的有效复核签字必须撤销。
            entry.update({
                "复核人员": None,
                "复核意见": comment,
                "复核结论": STATUS_RETURNED,
                "结论复核人员": reviewer,
                "复核签字": None,
            })

        self._set_status(entry, target)
        return entry, f"配载单已{action}"

    def _query_rows(self, *, keyword: str | None, status: str | None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            keyword = keyword.strip()
            rows = [row for row in rows if keyword in str(row.get("配载单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    @staticmethod
    def _set_status(entry: dict[str, Any], status: str) -> None:
        entry["status"] = status
        entry["配载状态"] = status
        entry["pending"] = status in {STATUS_DRAFT, STATUS_PENDING}
        entry["abnormal"] = status in NEGATIVE_ACTIONS
        entry["只读"] = status != STATUS_DRAFT

    @staticmethod
    def _open_review_record(entry: dict[str, Any], *, planner: str | None = None) -> dict[str, Any]:
        records = entry.setdefault("复核记录", [])
        for record in records:
            if record.get("结论") == STATUS_PENDING:
                return record
        record = {
            "结论": STATUS_PENDING,
            "提交人": planner or entry.get("配载人员"),
            "复核人员": None,
            "复核意见": None,
            "签字": False,
            "时间": LoadsheetService._now(),
        }
        records.append(record)
        return record

    @staticmethod
    def _to_number(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
        return float(match.group()) if match else 0.0

    @staticmethod
    def _has_value(value: Any) -> bool:
        return value is not None and str(value).strip() != ""

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
