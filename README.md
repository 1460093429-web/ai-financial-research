# AI Financial Research Platform

一个基于 Streamlit 的多语言金融研究平台，整合股票行情、技术指标、宏观数据、期权分析、新闻与情绪分析、估值、ETF/因子观察和 IBKR What-if 模拟。

金融数据可能延迟、不完整或因上游服务不可用而进入 fallback。界面和分析结果应同时检查数据来源、价格/观察时间、更新时间和 fallback 状态；本项目不保证数据为交易所实时数据，也不构成投资建议。

## 当前入口

当前仓库支持的 Streamlit 主入口是 [`dashboard.py`](dashboard.py)：

```bash
streamlit run dashboard.py
```

`dashboard.py` 负责页面编排，并调用根目录中的财务、宏观、ETF/因子、期权墙和 IBKR What-if 模块。完整的运行链路、重复实现和待确认事项见 [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md)。

Streamlit Community Cloud 的 **Main file path** 保存在 Cloud 控制台中，仓库内没有该设置的可验证副本。当前代码和本地运行证据均指向 `dashboard.py`，部署前仍应在控制台确认。

## 主要功能

- 股票行情、公司快照和技术指标
- 宏观经济数据、市场序列和美国市场估值观察
- 期权链、GEX、Put Wall、Call Wall 和期权结构摘要
- 公司新闻、市场新闻、翻译和情绪/可信度分析
- 多代理股票研究、公司估值和目标价分析
- ETF 新闻/资金流和因子轮动观察
- IBKR 活动报表、实时/收盘价/CSV fallback 与 What-if 分析
- Streamlit 缓存、刷新和 session state
- English、简体中文、Español 三语言界面

## 项目结构

```text
dashboard.py                  Streamlit 主入口和当前页面编排
config.py                     环境变量、.env 和 Streamlit secrets
financials.py                 FMP/Yahoo 公司、历史行情和新闻数据
macro_data.py                 FMP 宏观数据和 Yahoo fallback
etf_news_monitor.py           ETF 新闻和资金流数据处理
factor_watch.py               因子行情与轮动分析
option_walls.py               Put Wall / Call Wall 纯计算
ibkr_client.py                IBKR 只读连接与数据获取
ibkr_statement_parser.py      IBKR CSV 报表标准化
what_if_analysis.py           持仓和交易 What-if 计算
tests/                        当前 Dashboard 相关模块测试
ai_research_project/tests/    历史目录中的测试；裸导入目标见结构文档
ai_research_project/          保留的旧版或独立实现，不应直接删除
.github/workflows/            定时监控与研究任务
AGENTS.md                     工程、数据和测试约束
PROJECT_STRUCTURE.md          真实运行链路和模块状态审计
```

当前代码尚未完全实现 Provider → Service → Analytics → UI 分层，部分获取、标准化、计算和渲染逻辑仍集中在 `dashboard.py`。后续应采用分阶段、保持行为兼容的方式整理，不应一次性重写。

## 数据源

- **FMP**：公司财务、快照、新闻和部分宏观数据。
- **Yahoo Finance / yfinance**：行情、历史序列、技术数据、期权链、新闻、因子和多种 fallback。
- **IBKR**：What-if 工作流中的只读账户/市场数据；需要本地 TWS 或 IB Gateway 配置时，以页面连接设置为准。
- **CSV / 本地文件**：IBKR 报表上传、价格 fallback、观察列表、历史估值和回测输入。
- **OpenAI**：在配置可用时生成摘要、翻译或分析；相关工作流应保留无模型或失败时的明确状态。

不同功能的数据源优先级并不完全相同。fallback 不应被视为原数据源或实时数据，具体链路见 `PROJECT_STRUCTURE.md` 和相应页面的来源提示。

## 环境变量

复制示例文件并填入本地密钥：

```bash
cp .env.example .env
```

| 变量 | 用途 | 是否所有页面必需 |
| --- | --- | --- |
| `OPENAI_API_KEY` | AI 摘要、翻译和分析 | 否；仅相关 AI 功能需要 |
| `FMP_API_KEY` | FMP 财务、新闻和宏观数据 | 否；缺失时部分功能不可用或使用明确 fallback |
| `EMAIL_ADDRESS` | GitHub Actions 通知任务 | 本地 Dashboard 不需要 |
| `EMAIL_PASSWORD` | GitHub Actions 邮件认证 | 本地 Dashboard 不需要 |

本地 `.env` 和 `.streamlit/secrets.toml` 已被 Git 忽略。不要把真实密钥写入代码、README、`.env.example`、日志或提交记录。Streamlit Cloud 中应使用 App settings → Secrets 配置相同名称的密钥。

## 安装

建议使用独立虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Windows PowerShell 激活命令：

```powershell
.venv\Scripts\Activate.ps1
```

`requirements.txt` 使用 UTF-8 编码并固定当前依赖版本。GitHub Actions 的定时任务目前安装独立的依赖子集，而不是完整 requirements。

## 本地运行

从仓库根目录运行：

```bash
streamlit run dashboard.py
```

没有配置外部 API、IBKR 未连接或上游请求失败时，应用的相关区域可能显示不可用、空数据或 fallback。不要用占位金融数据替代失败结果。

## Streamlit Community Cloud 部署

1. 将仓库连接到 Streamlit Community Cloud。
2. 在 Cloud 控制台确认 Main file path 为 `dashboard.py`。
3. 使用仓库根目录的 `requirements.txt` 安装依赖。
4. 在 App settings → Secrets 配置需要的密钥，不要提交 `.streamlit/secrets.toml`。
5. 部署后检查启动日志、三种语言、无数据/fallback 状态和主要页面。

仓库当前没有提交 `.streamlit/config.toml`、容器文件或其他可证明 Cloud 控制台入口的配置。部署使用的 Python 版本和 Main file path 应以 Cloud 控制台实际设置为准。

## 测试

从仓库根目录运行：

```bash
pytest -q tests
pytest -q ai_research_project/tests
pytest -q
```

先运行与修改模块直接相关的测试，再运行完整测试。`ai_research_project/tests/` 当前使用裸导入；从仓库根运行时，其中多个测试实际解析到根目录同名模块，详情及后续修复方案见 `PROJECT_STRUCTURE.md`。

## 多语言

当前 Streamlit 界面支持：

- English
- 简体中文
- Español

新增用户可见文本必须补齐三种语言，并保留 English fallback。切换语言后还应检查缓存键、session state 和长文本布局。

## 自动化任务

`.github/workflows/monitor.yml` 在工作日运行：

- `monitor.py`
- `news_sentiment.py`
- `signal_system.py`

该工作流通过 GitHub Secrets 注入密钥，并使用显式依赖子集。它与 Streamlit Cloud Dashboard 是独立运行链路。

## Legacy：历史报告流程

早期 README 将 `main.py` 描述为主入口。该脚本目前仍保留，用于以下非 Streamlit 报告链：

```text
main.py
├── news.py
├── financials.py
├── charts.py
└── pdf_generator.py
```

历史运行方式：

```bash
python main.py
```

此流程可能生成图表和 PDF，但不是当前 Streamlit 主入口。`ai_research_project/` 也保留若干旧版或独立实现；在确认外部使用者和数据依赖前不要删除。
