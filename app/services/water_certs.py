"""水质证业务规则：唯一判定来源，还原台状态门、chip 标记与水质证专页共用。"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.models import WaterCert

HARDNESS_MIN = Decimal("0")
HARDNESS_MAX = Decimal("350")

DUPLICATE_MSG = "该工坊当日已有水质证，同坊同日不可重复提交。"


class WaterCertError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def today_local() -> date:
    """业务按自然日判定（容器统一北京时间）。"""
    return date.today()


def is_valid_cert(cert: Optional[WaterCert], today: Optional[date] = None) -> bool:
    """有效 = 合格且未作废且取样日落在最近 14 个自然日内（含当日）。"""
    if cert is None:
        return False
    return cert.is_valid_on(today or today_local())


def latest_valid_by_workshop(
    db: Session, today: Optional[date] = None
) -> dict[int, WaterCert]:
    """各坊最新一张有效证（无有效证的坊不出现）。

    chip 有效/缺失标记、专页「最新有效」标记、闲置→还原中放行三处结论
    全部取自本函数，保证同源。
    """
    day = today or today_local()
    latest: dict[int, WaterCert] = {}
    for cert in db.query(WaterCert).filter(WaterCert.voided.is_(False)).all():
        if is_valid_cert(cert, day):
            cur = latest.get(cert.workshop_id)
            if cur is None or (cert.sampled_on, cert.id) > (cur.sampled_on, cur.id):
                latest[cert.workshop_id] = cert
    return latest


def workshop_has_valid_cert(db: Session, workshop_id: int) -> bool:
    """闲置改还原中前按缸所属工坊查有效证；与 chip、专页同源。"""
    return workshop_id in latest_valid_by_workshop(db)


def parse_hardness(raw: str) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise WaterCertError("硬度值须为 0 到 350 之间的数字。")
    if not value.is_finite() or value < HARDNESS_MIN or value > HARDNESS_MAX:
        raise WaterCertError("硬度值须在 0 到 350 之间（含边界）。")
    return value


def parse_sample_date(raw: str) -> date:
    try:
        return date.fromisoformat(str(raw).strip())
    except (ValueError, AttributeError):
        raise WaterCertError("取样日格式无效，应为 YYYY-MM-DD。")


def validate_unique(
    db: Session,
    workshop_id: int,
    sampled_on: date,
    exclude_id: Optional[int] = None,
) -> None:
    """同坊同日唯一（含已作废记录仍占位，避免与历史证撞键）。

    仅为友好提示；并发下真正的拦截靠数据库唯一约束 + 提交时 IntegrityError。
    """
    q = db.query(WaterCert).filter(
        WaterCert.workshop_id == workshop_id,
        WaterCert.sampled_on == sampled_on,
    )
    if exclude_id is not None:
        q = q.filter(WaterCert.id != exclude_id)
    if q.first():
        raise WaterCertError(DUPLICATE_MSG)
