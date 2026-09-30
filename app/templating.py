"""共享 Jinja2 模板环境：还原台与水质证专页共用同一 env（含 tojson 过滤器）。"""

import json

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2.utils import markupsafe

templates = Jinja2Templates(directory="app/templates")


def _tojson(value):
    return markupsafe.Markup(json.dumps(value, ensure_ascii=False))


templates.env.filters["tojson"] = _tojson


def render(request: Request, name: str, context: dict, status_code: int = 200):
    ctx = {k: v for k, v in context.items() if k != "request"}
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
