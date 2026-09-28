"""载重平衡业务规则：状态流转、字段校验、复核留痕与汇总口径都收在这里。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "loadsheet"
REQUIRED_FIELDS = ["配载单号", "关联航班", "计算重量"]
EDITABLE_FIELDS = ["关联航班", "计算重量", "重心位置", "油量数据"]
# 复核相关字段只能由复核动作产生，任何账号都不能通过普通编辑改动历史结论。
PROTECTED_FIELDS = ["复核人员", "复核意见", "复核结论", "复核记录"]

STATUS_DRAFT = "待计算"
STATUS_REVIEWING = "待复核"
STATUS_CONFIRMED = "已确认"
STATUS_RETURNED = "已退回"
STATUSES = [STATUS_DRAFT, STATUS_REVIEWING, STATUS_CONFIRMED, STATUS_RETURNED]

SUBMIT = "提交复核"
CONFIRM = "确认配载"
RETURN = "退回重算"
ACTIONS = [SUBMIT, CONFIRM, RETURN]

# 演示环境没有登录中间件，用固定账号区分配载人员与复核人员的操作边界。
LOADER_ACCOUNTS = {"张磊", "李强"}
REVIEWER_ACCOUNTS = {"王敏", "赵倩"}
DEFAULT_LOADER = "张磊"
DEFAULT_REVIEWER = "王敏"

ALLOWED_TRANSITIONS = {
    SUBMIT: (STATUS_DRAFT, STATUS_RETURNED),
    CONFIRM: (STATUS_REVIEWING,),
    RETURN: (STATUS_REVIEWING,),
}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _to_number(value: Any) -> float | None:
    """把「12000kg」这类展示值解析成数值；无法识别时不参与汇总。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


class LoadsheetService:
    def _filtered_rows(self, keyword: str | None, status: str | None) -> list[dict[str, Any]]:
        rows = list(store.rows(MODULE))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("配载单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filtered_rows(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self, *, keyword: str | None = None, status: str | None = None) -> dict[str, int | float]:
        """列表与卡片共用同一筛选口径，避免页面数字和清单条数对不上。"""
        rows = self._filtered_rows(keyword=keyword, status=status)
        confirmed = [row for row in rows if row.get("status") == STATUS_CONFIRMED]
        weights = [weight for row in confirmed if (weight := _to_number(row.get("计算重量"))) is not None]
        centers = [center for row in confirmed if (center := _to_number(row.get("重心位置"))) is not None]
        return {
            "reviewing": sum(1 for row in rows if row.get("status") == STATUS_REVIEWING),
            "total": len(rows),
            "returned": sum(1 for row in rows if row.get("status") == STATUS_RETURNED),
            "confirmed": len(confirmed),
            "confirmedWeight": sum(weights),
            "confirmedCenterOfGravity": round(sum(centers) / len(centers), 2) if centers else 0,
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        order_number = str(values["配载单号"]).strip()
        if any(str(row.get("配载单号") or "") == order_number for row in rows):
            return None, [f"配载单号 {order_number} 已存在，不能重复登记"]
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["重心位置"] = values.get("重心位置")
        entry["油量数据"] = values.get("油量数据")
        entry["配载人员"] = str(values.get("配载人员") or values.get("operator") or DEFAULT_LOADER).strip()
        entry["复核人员"] = None
        entry["复核意见"] = None
        entry["复核结论"] = None
        entry["复核记录"] = []
        entry["status"] = STATUS_DRAFT
        entry["配载状态"] = STATUS_DRAFT
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        operator: str | None,
    ) -> tuple[dict[str, Any] | None, str]:
        """允许配载人员在退回重算后修正配载数据；复核结论字段对所有编辑入口只读。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"配载单 {entry_id} 不存在或已归档"
        protected = [field for field in PROTECTED_FIELDS if field in values]
        if protected:
            return None, f"{'、'.join(protected)}为复核留痕字段，账号不能直接改动复核结论"
        account = str(operator or entry.get("配载人员") or DEFAULT_LOADER).strip()
        if account not in LOADER_ACCOUNTS:
            return None, "只有配载人员可以修改配载数据，复核人员无此权限"
        if account != str(entry.get("配载人员") or ""):
            return None, "只有原配载人员可以修改本配载单"
        if entry.get("status") not in (STATUS_DRAFT, STATUS_RETURNED):
            return None, "配载单提交后对配载人员只读，需退回重算后才能修改"

        merged = {**entry, **values}
        missing = [field for field in REQUIRED_FIELDS if not str(merged.get(field) or "").strip()]
        if missing:
            return None, f"必填字段不能为空：{'、'.join(missing)}"
        for field in EDITABLE_FIELDS:
            if field in values:
                entry[field] = values[field]
        return entry, "配载数据已保存；复核意见仍归属原复核人员，未被改动"

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str | None = None,
        opinion: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"配载单 {entry_id} 不存在或已归档"
        if action not in ACTIONS:
            return None, f"动作「{action}」不属于载重平衡可执行范围"

        current_status = str(entry.get("status") or "")
        if current_status not in ALLOWED_TRANSITIONS[action]:
            expected = "或".join(ALLOWED_TRANSITIONS[action])
            return None, f"配载单当前为{current_status}，不能重复{action}；仅{expected}状态可执行"

        account = str(operator or "").strip()
        note = str(opinion or "").strip()
        if action == SUBMIT:
            return self._submit(entry, account)
        if action == CONFIRM:
            return self._confirm(entry, account, note)
        return self._return(entry, account, note)

    def _submit(self, entry: dict[str, Any], account: str) -> tuple[dict[str, Any] | None, str]:
        account = account or str(entry.get("配载人员") or DEFAULT_LOADER)
        if account not in LOADER_ACCOUNTS:
            return None, "只有配载人员可以提交复核"
        if account != str(entry.get("配载人员") or ""):
            return None, "只有原配载人员可以提交本配载单"
        entry["status"] = STATUS_REVIEWING
        entry["配载状态"] = STATUS_REVIEWING
        # 新一轮复核尚未签字，不能沿用上一轮的复核人员或结论。
        entry["复核人员"] = None
        entry["复核意见"] = None
        entry["复核结论"] = None
        entry["pending"] = True
        entry["abnormal"] = False
        return entry, "配载单已提交复核"

    def _confirm(
        self,
        entry: dict[str, Any],
        account: str,
        opinion: str,
    ) -> tuple[dict[str, Any] | None, str]:
        account = account or DEFAULT_REVIEWER
        if account not in REVIEWER_ACCOUNTS:
            return None, "只有复核人员可以确认配载"
        if not opinion:
            return None, "确认配载必须填写复核意见，结论需归属到具体复核人员"
        history = list(entry.get("复核记录") or [])
        round_no = len(history) + 1
        record = self._review_record(round_no, CONFIRM, account, opinion)
        history.append(record)
        entry["复核记录"] = history
        entry["复核人员"] = account
        entry["复核意见"] = opinion
        entry["复核结论"] = CONFIRM
        entry["status"] = STATUS_CONFIRMED
        entry["配载状态"] = STATUS_CONFIRMED
        entry["pending"] = False
        entry["abnormal"] = False
        return entry, f"配载单已确认，复核意见归属{account}"

    def _return(
        self,
        entry: dict[str, Any],
        account: str,
        opinion: str,
    ) -> tuple[dict[str, Any] | None, str]:
        account = account or DEFAULT_REVIEWER
        if account not in REVIEWER_ACCOUNTS:
            return None, "只有复核人员可以退回重算"
        if not opinion:
            return None, "退回重算必须填写复核意见，便于配载人员定位问题"
        history = list(entry.get("复核记录") or [])
        round_no = len(history) + 1
        record = self._review_record(round_no, RETURN, account, opinion)
        history.append(record)
        entry["复核记录"] = history
        # 历史意见保留留痕；撤销当前签字和结论，待办计数随 pending 一起归零。
        entry["复核人员"] = None
        entry["复核意见"] = opinion
        entry["复核结论"] = RETURN
        entry["status"] = STATUS_RETURNED
        entry["配载状态"] = STATUS_RETURNED
        entry["pending"] = False
        entry["abnormal"] = True
        return entry, f"配载单已退回重算，签字已撤销，{account}的复核意见已留痕"

    def _review_record(self, round_no: int, result: str, reviewer: str, opinion: str) -> dict[str, Any]:
        return {
            "轮次": round_no,
            "复核结论": result,
            "复核人员": reviewer,
            "复核意见": opinion,
            "复核时间": _now_text(),
        }
