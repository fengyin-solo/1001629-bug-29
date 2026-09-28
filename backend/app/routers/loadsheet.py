"""载重平衡接口：维护配载单，覆盖提交复核、确认配载、退回重算等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.loadsheet import (
    ACTIONS,
    STATUSES,
    LoadsheetService,
)

router = APIRouter(prefix="/api/loadsheet", tags=["载重平衡"])

service = LoadsheetService()

LIST_FIELDS = ["配载单号", "关联航班", "计算重量", "重心位置", "油量数据", "配载人员", "复核人员", "配载状态"]


def _validate_status(status: str | None) -> None:
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态仅支持：{'、'.join(STATUSES)}")


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按配载单号检索"),
    status: str | None = Query(default=None, description="待计算、待复核、已确认、已退回"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按配载单号与状态过滤载重平衡列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    _validate_status(status)
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary(
    keyword: str | None = Query(default=None, description="与列表保持同一检索口径"),
    status: str | None = Query(default=None, description="与列表保持同一状态口径"),
) -> dict[str, Any]:
    """待复核待办与已确认汇总：数字由当前清单实时统计，退回即归零、刷新仍成立。"""
    _validate_status(status)
    return {"module": "loadsheet", **service.stats(keyword=keyword, status=status)}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出载重平衡清单：返回当前全量数据及与页面一致的汇总数字。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "loadsheet", "total": total, "summary": service.stats(), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条配载单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"配载单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条配载单，缺字段或单号重复时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        message = problems[0] if len(problems) == 1 else f"缺少必填字段：{'、'.join(problems)}"
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="配载单已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """退回重算后由原配载人员修正配载数据；复核结论字段对任何编辑入口只读。"""
    values = dict(payload.values)
    operator = str(values.pop("operator", None) or payload.operator or "").strip()
    entry, message = service.update_entry(entry_id, values, operator or None)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条配载单执行提交复核、确认配载、退回重算；不允许的动作会被拦下并说明原因。

    提交/确认/退回都按当前状态机校验，连续重复提交或重复确认只会得到一条结论。
    """
    values = dict(payload.values)
    action = str(values.pop("action", None) or payload.action or "").strip()
    operator = str(values.pop("operator", None) or payload.operator or "").strip()
    opinion = values.pop("opinion", None)
    if opinion is None:
        opinion = payload.opinion
    if not action:
        return ActionResult(ok=False, message="缺少动作名称")
    if action not in ACTIONS:
        return ActionResult(ok=False, message=f"动作「{action}」不属于载重平衡可执行范围")
    entry, message = service.run_action(
        entry_id,
        action,
        operator=operator or None,
        opinion=str(opinion or "").strip() or None,
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
