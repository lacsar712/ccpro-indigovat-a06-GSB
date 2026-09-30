# IndigoVat-01 · 染缸还原台

FastAPI + PostgreSQL + Jinja2：主界面是横向**缸位条**（Alpine 反应式），不是工坊/染缸/批次三表导航。Session Cookie 登录；规则在 `app/services/vat_rules.py`。

## 技术栈

- FastAPI、SQLAlchemy 2、PostgreSQL
- 启动时 `create_all` + 幂等种子（蓝靛湾一号坊 / 清水江二号坊）
- Session Cookie 认证（Starlette SessionMiddleware）
- Jinja2 + Alpine.js + Pico（叠靛蓝水墨自定义样式）
- Docker Compose：`web` + `db`

## 端口与数据库

| 服务 | 端口 |
|------|------|
| Web  | **4720** |
| Postgres | **6120**（容器内 5432） |

数据库账号：`indigovat` / `indigovat` / 库名 `indigovat`

## 快速启动

```bash
cd IndigoVat/IndigoVat-01
docker compose up --build -d
```

浏览器打开：http://localhost:4720

演示账号（登录页已预填）：

- `admin` / `123456`
- `worker` / `123456`

## 交互（信息架构）

1. **染缸还原台**：横滑缸位条，每缸显示状态、最近电位与 redox sparkline
2. **工坊 chip**：仅作缸位筛选，无独立工坊 CRUD 页；chip 旁直接标注该坊「水质证有效 / 水质证缺失」
3. **点缸展开**：同页内登记浸染批次、改状态、看近几笔；无平行「染缸表 / 批次表」
4. **水质证专页**：顶栏进入 `/water-certs`，按工坊看有效证现状、登记/更新/作废水质证，台账行标注「最新有效」

**业务规则**：

- 状态改为 `ready`（可染色）时，最新批次 `redoxMv` 须已填且 ≤ -500（见 `vat_rules.py`）。
- **闲置缸改还原中**前，按缸所属工坊查有效水质证；没有有效证则中文拒绝，且只有这一个服务端入口，chip 与专页都不能旁路放行。

### 水质证（WaterCert）

- 字段：工坊、取样日、硬度值（0–350）、是否合格、化验人；另有无作废标记。
- **有效 = 合格 且 取样日在最近 14 个自然日内（含取样当日与今天）且未作废**；作废后立即失效。
- **同坊同日仅一张**：新建与更新共用同一套「同坊同日唯一 + 硬度区间」校验；数据库唯一约束 `uniq_water_cert_workshop_day` 兜底——两人几乎同时提交同坊同日证时**至多一笔入库**，其余在提交时被拒并回滚，页面给出中文提示，还原台与水质证专页照常可打开。
- 权限：染缸工（worker）可登记与更新；作废仅主管（admin，is_superuser）可操作。
- **三处同源**：改状态校验、专页「最新有效」标记、工坊 chip 的有效/缺失，全部调用 `app/services/water_rules.py` 的 `latest_valid_cert`，禁止各自另写查询。

## 本地开发（可选）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
set POSTGRES_HOST=localhost
set POSTGRES_PORT=6120
uvicorn app.main:app --host 0.0.0.0 --port 4720 --reload
```

## 业务模型

1. **Workshop**：`name`、`region`、`notes`（UI 上仅为筛选片）
2. **Vat**：归属工坊、`code`、`dyeType`、`volumeL`、状态 `idle|reducing|ready`
3. **DipLot**：归属染缸、`dippedAt`、`clothMeters`、`redoxMv`（可空）
4. **WaterCert**：归属工坊、`sampled_on`、`hardness`（0–350）、`qualified`、`tester`、`voided`；`(workshop_id, sampled_on)` 唯一

种子数据：蓝靛湾一号坊持有效水质证（另留一张已过期证作台账演示）；清水江二号坊**刻意缺证**并保留闲置缸 V-13，用于演示无证拒绝改还原中。

## 目录结构

```
IndigoVat-01/
  Dockerfile
  entrypoint.sh
  docker-compose.yml
  requirements.txt
  app/
    main.py
    db.py
    models.py
    schemas.py
    auth.py
    seed.py
    templating.py          # 共享 Jinja 环境（tojson / render）
    routers/               # auth / pages / water
    services/vat_rules.py  # 染缸状态规则（含闲置改还原中查有效证）
    services/water_rules.py# 水质证有效性单一来源（14 自然日窗口）
    templates/   # base / bay / water_certs / login
```
