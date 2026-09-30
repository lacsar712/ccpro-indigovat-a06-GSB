"""水质证业务规则。

改状态校验、专页「最新有效」标记、工坊 chip 的有效/缺失判断
三处都调用本模块的同一套函数，保证结论同源。
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models import WaterCert

# 有效窗口：最近 14 个自然日（含取样当日与今天）
VALID_WINDOW_DAYS = 14

HARDNESS_MIN = Decimal("0")
HARDNESS_MAX = Decimal("350")


class WaterCertError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def validate_cert_fields(hardness: Decimal) -> None:
    """新建与更新共用：硬度区间 0–350。"""
    if hardness < HARDNESS_MIN or hardness > HARDNESS_MAX:
        raise WaterCertError(f"硬度值须在 0 到 350 之间，当前为 {hardness}。")


def _valid_window(today: date) -> tuple[date, date]:
    """最近 VALID_WINDOW_DAYS 个自然日 [起, 止]，含两端；止为今天。"""
    return today - timedelta(days=VALID_WINDOW_DAYS - 1), today


def cert_is_valid(cert: WaterCert, today: Optional[date] = None) -> bool:
    """有效 = 未作废 且 合格 且 取样日落在最近 14 个自然日内。"""
    today = today or date.today()
    if cert.voided or not cert.qualified:
        return False
    start, end = _valid_window(today)
    return start <= cert.sampled_on <= end


def cert_status_label(cert: WaterCert, today: Optional[date] = None) -> str:
    """台账展示用状态文案，与 cert_is_valid 同一窗口。"""
    today = today or date.today()
    if cert.voided:
        return "已作废"
    if not cert.qualified:
        return "不合格"
    start, end = _valid_window(today)
    if cert.sampled_on > end:
        return "未到取样日"
    if cert.sampled_on < start:
        return "已过期"
    return "有效"


def latest_valid_cert(
    db: Session, workshop_id: int, today: Optional[date] = None
) -> Optional[WaterCert]:
    """工坊当前有效证（取样日最新的一张），没有则 None。

    闲置改还原中校验、专页「最新有效」标记、工坊 chip 有效/缺失
    三处结论都从这里取，禁止各自另写查询旁路放行。
    """
    today = today or date.today()
    candidates = (
        db.query(WaterCert)
        .filter(WaterCert.workshop_id == workshop_id)
        .order_by(WaterCert.sampled_on.desc(), WaterCert.id.desc())
        .all()
    )
    for cert in candidates:
        if cert_is_valid(cert, today):
            return cert
    return None
