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
2. **工坊 chip**：仅作缸位筛选，无独立工坊 CRUD 页
3. **点缸展开**：同页内登记浸染批次、改状态、看近几笔；无平行「染缸表 / 批次表」

**业务规则**：
- 状态改为 `ready`（可染色）时，最新批次 `redoxMv` 须已填且 ≤ -500（见 `vat_rules.py`）。
- 闲置缸（`idle`）改为还原中（`reducing`）前，按缸所属工坊校验**有效水质证**；没有则中文拒绝。chip 筛选片不提供任何放行旁路。

## 水质证

顶栏「水质证」进入专页 `/water-certs`，字段：工坊、取样日、硬度值（0–350）、是否合格、化验人。

- **有效期 14 个自然日**：仅「合格 + 未作废 + 取样日在最近 14 日内」的证算有效；作废后立即失效。
- **同坊同日唯一**：同一工坊同一天至多一张证；新建与更新共用同一套唯一与硬度区间校验。
- **并发拒证**：两人几乎同时提交同坊同日证时，数据库唯一约束保证至多一笔入库，另一笔收到中文重复提示；被拒后还原台与水质证专页仍可正常打开。
- **权限**：染缸工（`worker`）可新建/编辑；仅主管（`admin`）可作废。
- **三处同源**：闲置→还原中放行、工坊 chip 旁「有效/缺证」、专页「最新有效」标记，结论全部取自 `app/services/water_certs.py` 的 `latest_valid_by_workshop()`，不会出现 chip 与专页不一致。

种子数据：蓝靛湾一号坊持 3 日内合格证；清水江二号坊仅有一张 21 日前的过期证并保留闲置缸 V-11（用于验证无证拒绝）。

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
4. **WaterCert**：归属工坊、`sampled_on`、`hardness`(0–350)、`passed`、`chemist`、`voided`；同坊同日唯一

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
    routers/
    services/vat_rules.py
    services/water_certs.py  # 有效水质证唯一判定来源
    templates/   # base / bay / login / water
```
