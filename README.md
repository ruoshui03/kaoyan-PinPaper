# 📚 考研拼好卷 (kaoyan-PinPaper)

> **Pin Your Best Exam Papers · 智能组卷 · 错题靶向攻坚 · 真题级三版式导出**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

考研数学智能组卷与错题攻坚系统。按真题结构从题库中组卷、按科目独立管理错题、导出考场级 PDF，帮助你把有限的刷题时间集中到薄弱考点上。题库可扩展，当前内置李林《880》数一 / 数二 / 数三。答案与解析待添加。

---

## ✨ 核心特性

- 🎯 **智能组卷**：
  - **组卷规格**：真题结构（10 选择 + 6 填空 + 6 解答）、5-3-3 突击模考、3 套全章节覆盖联考、自定义题量与配比；
  - **难度梯度**：按基础 / 综合 / 拓展三档加权抽题；
  - **考点专项**：按标签（高频经典、易错点、计算量大、综合压轴）定向抽题。
- 📕 **错题靶向重练**：
  - **按题号导入**：刷完一章后，分基础 / 综合 / 拓展篇输入做错题号批量标记；
  - **优先重练**：组卷默认以待练错题为题源，直接生成错题卷；
  - **顽固错题**：做错次数累计，反复做错的题重点标记、集中攻坚。
- 📈 **考点雷达**：
  - **覆盖进度**：目标章节的组卷覆盖率与进度条；
  - **顽固清单**：本科目高频顽固错题按做错次数排序汇总；
  - **分科画像**：按高数 / 线代 / 概率分类展示各章覆盖与错题分布。
- 📑 **三版式 PDF 导出**：
  - **真题版**：紧密排版，无答案，需自备答题卡；
  - **A4 做题本**：全卷留白演算空间，适合 iPad 导题与打印刷题；
  - **详细解析版**：参考答案与分步解析。
- 🤖 **AI 解题私教**：接入任意兼容 OpenAI 规范的大模型 API（DeepSeek、通义千问、智谱、Ollama 本地等），逐题输出分步推导与答疑。
- 🔗 **链接即存档（无后端跨设备）**：错题状态与上次生成的试卷都编码进页面网址，收藏或复制该链接即可在其他设备恢复——无需登录、无需数据库。
  - **错题进度**：各科错题以位图压缩进网址（约 30 字符），做错次数分待练 / 顽固两档保真；
  - **上次的卷**：记住上次生成的是哪几道题（5-3-3 / 自定义 / 3 套联考通用），做完后凭链接回来查阅答案；
  - **安全**：API Key 出于安全**不写入网址**，仅本会话使用或经环境变量预置。

---

## 🚀 快速启动

### 0. 免安装在线体验（最快）

直接打开：<https://kaoyan-pinpaper.streamlit.app/> —— 无需安装即可使用。

> 云端不保存数据：错题与试卷编码在页面网址里，请收藏 / 复制该链接以便下次或换设备恢复。

### 1. 克隆项目与安装依赖

```bash
git clone https://github.com/ruoshui03/kaoyan-PinPaper.git
cd kaoyan-PinPaper

# 创建并激活虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

> WeasyPrint 依赖 GTK 系统库来渲染 PDF。Windows 下建议直接安装 GTK3 Runtime，
> Linux 参见 [`packages.txt`](packages.txt)（`libpango`、`libcairo` 等）。

### 2. 启动应用

```bash
streamlit run app.py
```

Windows 用户可直接双击 [`启动应用.bat`](启动应用.bat)，浏览器将自动打开 `http://localhost:8501`。

---

## 🧭 三大工作区

| 工作区 | 作用 |
| --- | --- |
| 🎯 **智能拼好卷** | 选科目、选规格、调难度梯度与学科配比，一键生成试卷并导出 PDF |
| 🏷️ **题库逐题标错** | 按章节浏览题目，逐题或批量标记错题、增减做错次数 |
| 📈 **全科考点雷达** | 查看章节覆盖进度、顽固错题清单与分科目覆盖画像 |

---

## 📁 目录架构

```text
kaoyan-PinPaper/
├── app.py                     # Streamlit 交互式主界面（默认入口）
├── core/                      # 核心领域模型与业务引擎
│   ├── bank_loader.py         # 题库解析、多维索引与科目路由
│   ├── models.py              # 数据结构、枚举与各科章节定义
│   ├── paper_engine.py        # 拼卷算法引擎 (10-6-6 / 5-3-3 / 联考 / 自定义)
│   ├── pdf_service.py         # 三版式高清 PDF 导出引擎
│   ├── state_manager.py       # 按科目隔离的错题本与进度状态管理
│   └── ai_tutor.py            # AI 解题私教（OpenAI 兼容流式调用）
├── server.py + web/           # 可选的原生 Web 前端（复用同一 core 引擎）
├── 题库资料/                  # 880 数一 / 数二 / 数三题库
│   └── 880数学X/
│       ├── metadata/*.json    #   题目元数据（章节、难度、标签、答案）
│       └── problems/*.md      #   题面正文（LaTeX 公式）
└── user_data/                 # 错题本模板与用户存档
```

---

## 🤖 AI 私教配置

在侧边栏「AI 名师答疑」中选择预设服务商或自定义，填入 API Base URL、API Key 与模型名称即可。也支持通过环境变量预置：

```bash
export DEEPSEEK_API_KEY=sk-xxx        # 或 OPENAI_API_KEY
export OPENAI_BASE_URL=https://api.deepseek.com
```

Key 仅用于本地会话调用，不会写入仓库。

---

## 📄 开源许可

本项目遵循 [MIT License](LICENSE) 开源协议。题库素材版权归原作者所有，仅供学习交流，请勿用于商业用途。
