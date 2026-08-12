# RAG 智能问答 — 技术文档知识库 & 企业微信接入 完整说明文档

> 项目全生命周期复盘 | 2026-04  
> 颗粒度：每一个具体细节、问题处理过程、决策依据

---

## 目录

1. [项目概述与最终成果](#一项目概述与最终成果)
2. [环境搭建全过程](#二环境搭建全过程)
3. [文档分类系统 (doc_classifier.py)](#三文档分类系统)
4. [RAG 向量库构建 (rag_builder.py)](#四rag-向量库构建)
5. [智能问答 Web UI (rag_web.py)](#五智能问答-web-ui)
6. [一键启动脚本 (start_rag.sh)](#六一键启动脚本)
7. [MkDocs 文档站 (generate_mkdocs.py)](#七mkdocs-文档站)
8. [企业微信接入方案](#八企业微信接入方案)
9. [踩坑记录 — 逐条细节复盘](#九踩坑记录--逐条细节复盘)
10. [项目文件清单与路径地图](#十项目文件清单与路径地图)
11. [快速使用手册](#十一快速使用手册)
12. [后续规划](#十二后续规划)

---

## 一、项目概述与最终成果

### 1.1 项目目标

为工业自动化领域构建一套 **RAG（Retrieval-Augmented Generation，检索增强生成）智能问答系统**。核心需求：

- 将散落在 C/D 盘的 **数百份技术文档**（PDF、Word、PPT、Excel）统一管理
- 按主题自动分类、去重
- 提取文本 → 向量化 → 构建可检索的知识库
- 提供 Web UI 自然语言问答
- 接入企业微信，支持 `/查` 命令即时查询

### 1.2 最终成果数据

| 指标 | 数值 | 说明 |
|------|------|------|
| 有效文档数 | 442 份 | 经分类去重后的有效技术文档 |
| 提取文本缓存 | 460 个 JSON 文件 | 含空文件和提取失败的缓存记录 |
| 向量数量 | 22,181 条 | ChromaDB 中的 chunk 向量 |
| 嵌入模型 | BAAI/bge-base-zh-v1.5 | 768维，中文优化 |
| 向量数据库 | ChromaDB | 持久化，cosine 相似度，HNSW 索引 |
| LLM 通道 | 3 通道容灾 | MiMo-Flash → Qwen-Plus → Qwen2.5:3b(本地) |
| Web UI | Gradio | http://localhost:7860，流式输出 |
| 向量库大小 | ~116 MB | `/home/hp/rag_chromadb/chroma.sqlite3` |

### 1.3 系统全景架构

```
┌─────────────────────────────────────────────────────────┐
│                   数据准备层                              │
│                                                         │
│  C:/D: 原始文档  ──→  doc_classifier.py (自动分类)       │
│       │                    │                            │
│       │              classification_result.json          │
│       ▼                    │                            │
│  /mnt/d/知识库wiki/        ▼                            │
│  (按分类目录组织)     generate_mkdocs.py                 │
│                      (生成MkDocs站点)                    │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                   向量化层                                │
│                                                         │
│  rag_builder.py:                                        │
│    [1] 文本提取 (pymupdf4llm/docx/pptx/openpyxl)       │
│    [2] 文本分块 (RecursiveCharacterTextSplitter)         │
│    [3] 向量嵌入 (bge-base-zh-v1.5, CPU)                 │
│    [4] 入库 (ChromaDB, cosine, batch=256)               │
│    [5] 知识点归档 (关键词提取, 分类统计)                   │
│                                                         │
│  输出: /home/hp/rag_chromadb/ (22,181 vectors)          │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                   服务层                                  │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ rag_web.py   │  │ wecom_bot.py │  │ MkDocs serve  │  │
│  │ Gradio :7860 │  │ FastAPI :8001│  │ :8000         │  │
│  │ (Web问答)    │  │ (企业微信)    │  │ (文档浏览)    │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┘  │
│         │                 │                              │
│         ▼                 ▼                              │
│  ┌─────────────────────────────────┐                    │
│  │         rag_core.py             │                    │
│  │  (共享: 检索 + LLM三通道容灾)    │                    │
│  └────────────┬────────────────────┘                    │
│               │                                         │
│     ┌─────────┼──────────┐                              │
│     ▼         ▼          ▼                              │
│  MiMo-Flash Qwen-Plus  Qwen2.5:3b                      │
│  (小米云)    (通义云)    (Ollama本地)                     │
└─────────────────────────────────────────────────────────┘
```

---

## 二、环境搭建全过程

### 2.1 基础环境

```
操作系统:    WSL2 on Windows (Linux 6.6.87.2-microsoft-standard-WSL2)
Python:     3.12
虚拟环境:    /home/hp/mkdocs-env/
激活命令:    source /home/hp/mkdocs-env/bin/activate
```

### 2.2 虚拟环境创建过程

```bash
# 在 WSL2 中创建 Python 虚拟环境
python3 -m venv /home/hp/mkdocs-env
source /home/hp/mkdocs-env/bin/activate
```

**为什么用 venv 而不是 conda？**  
WSL2 环境下 venv 更轻量，且与系统 Python 3.12 直接兼容，不引入额外的包管理复杂性。

### 2.3 依赖安装

核心依赖分为四组，按用途安装：

**第一组：文本提取相关**
```bash
pip install pymupdf pymupdf4llm      # PDF 提取（pymupdf4llm 将 PDF 转 Markdown）
pip install python-docx               # DOCX 提取
pip install python-pptx               # PPTX 提取
pip install openpyxl                   # XLSX 提取
```

**第二组：RAG 核心**
```bash
pip install chromadb                   # 向量数据库 (安装后版本 1.5.7)
pip install sentence-transformers      # 嵌入模型加载框架 (5.4.1)
pip install torch                      # PyTorch (CPU 推理)
pip install langchain-text-splitters   # 文本分块工具
```

**第三组：Web UI 和 LLM**
```bash
pip install gradio                     # Web UI 框架 (6.12.0)
pip install openai                     # OpenAI 兼容 SDK (2.32.0)，用于调用所有 LLM
```

**第四组：辅助工具**
```bash
pip install fastapi uvicorn            # API 框架 (为企业微信接入准备)
pip install pyyaml                     # YAML 配置解析
pip install requests                   # HTTP 请求
pip install lxml                       # XML 解析
pip install python-dotenv              # 环境变量管理
```

**安装过程遇到的问题：**

1. **PyTorch 安装耗时长**：torch 包体约 2GB，WSL2 网络通过 Windows 代理，下载速度受限。解决：使用国内镜像 `pip install torch -i https://pypi.tuna.tsinghua.edu.cn/simple`
2. **sentence-transformers 依赖链**：会自动拉取 transformers、tokenizers、huggingface-hub 等大包，总安装约 800MB
3. **ChromaDB 的 SQLite 版本要求**：ChromaDB 要求 SQLite ≥ 3.35.0，WSL2 Ubuntu 自带版本满足要求，无需额外处理

### 2.4 Ollama 安装（本地 LLM 兜底通道）

```bash
# Ollama 安装到 D 盘（节省系统盘空间）
# 二进制: /mnt/d/ollama/bin/ollama
# 模型:   /mnt/d/ollama/models/

# 设置环境变量
export OLLAMA_MODELS="/mnt/d/ollama/models"
export OLLAMA_HOST="0.0.0.0:11434"

# 启动服务
ollama serve &

# 拉取中文模型
ollama pull qwen2.5:3b
```

**为什么选 qwen2.5:3b？**  
- 3B 参数量在 CPU 推理下可接受（~25秒延迟）
- 中文能力相对同体量模型最好
- 磁盘占用约 2GB，不算大
- 作为兜底通道，不追求极致质量，要的是"能用"

### 2.5 嵌入模型首次下载

```bash
# 首次运行时 sentence-transformers 会自动从 HuggingFace 下载模型
# BAAI/bge-base-zh-v1.5 约 400MB
# 下载到: ~/.cache/huggingface/hub/models--BAAI--bge-base-zh-v1.5/
```

**首次下载遇到的问题：**  
HuggingFace 在国内访问不稳定。解决方案：设置镜像 `export HF_ENDPOINT=https://hf-mirror.com` 或手动下载放到缓存目录。

### 2.6 关键路径总表

| 用途 | 路径 | 所在文件系统 |
|------|------|-------------|
| Python 虚拟环境 | `/home/hp/mkdocs-env/` | Linux ext4 |
| 项目脚本 | `/home/hp/*.py`, `/home/hp/*.sh` | Linux ext4 |
| Wiki 根目录 | `/mnt/d/知识库wiki/` | Windows NTFS |
| 分类结果 | `/mnt/d/知识库wiki/00_目录索引/classification_result.json` | NTFS |
| 提取文本缓存 | `/mnt/d/知识库wiki/rag_data/extracted/` | NTFS |
| 知识点归档 | `/mnt/d/知识库wiki/rag_data/knowledge_points.json` | NTFS |
| **向量数据库** | **`/home/hp/rag_chromadb/`** | **Linux ext4** |
| Ollama 二进制 | `/mnt/d/ollama/bin/ollama` | NTFS |
| Ollama 模型 | `/mnt/d/ollama/models/` | NTFS |
| HuggingFace 缓存 | `~/.cache/huggingface/` | Linux ext4 |

> **重要**：向量数据库必须在 Linux 原生文件系统上。详见踩坑记录。

---

## 三、文档分类系统

### 3.1 脚本：`/home/hp/doc_classifier.py`

**功能**：扫描 C/D 盘的技术文档，按主题自动分类，去重，生成分类索引。

**输入**：散落在多个目录的原始技术文档  
**输出**：`/mnt/d/知识库wiki/00_目录索引/classification_result.json`

```json
{
  "documents": [
    {
      "name": "G120变频器调试手册.pdf",
      "category": "变频器/西门子G120",
      "dest_path": "/mnt/d/知识库wiki/变频器/西门子G120/G120变频器调试手册.pdf",
      "size": 2456789,
      "hash": "abc123..."
    }
  ]
}
```

**分类逻辑**：
- 基于文件名关键词匹配（如"G120" → 变频器/西门子G120）
- 基于目录结构推断
- 文件哈希去重（同一文件在多处出现只保留一份）

### 3.2 分类结果

最终分类出 442 份有效技术文档，涵盖：
- PLC 编程（西门子、三菱等）
- 变频器（G120、ABB 等）
- 机器人（FANUC、ABB 等）
- SICAR 标准块
- 电气图纸
- 安全标准
- 等等

---

## 四、RAG 向量库构建

### 4.1 脚本：`/home/hp/rag_builder.py`

这是 RAG 系统的核心构建工具，实现完整的 ETL 流水线。

### 4.2 全局配置

```python
WIKI_ROOT = Path("/mnt/d/知识库wiki")
RAG_DIR = WIKI_ROOT / "rag_data"
EXTRACTED_DIR = RAG_DIR / "extracted"
CHROMA_DIR = Path("/home/hp/rag_chromadb")     # Linux fs，避免 SQLite 问题
RESULT_FILE = WIKI_ROOT / "00_目录索引" / "classification_result.json"

COLLECTION_NAME = "wiki_docs"
EMBEDDING_MODEL = "BAAI/bge-base-zh-v1.5"
CHUNK_SIZE = 800          # 每块 800 字符
CHUNK_OVERLAP = 100       # 重叠 100 字符
MAX_TEXT_PER_DOC = 100000 # 单文档最大提取 10 万字符
```

**参数选择依据**：
- **CHUNK_SIZE=800**：中文场景下，800 字符约 400-500 个汉字，一个完整段落或操作步骤。太小会丢失上下文，太大会稀释相关性
- **CHUNK_OVERLAP=100**：12.5% 重叠率，确保段落边界的信息不丢失
- **MAX_TEXT_PER_DOC=100000**：电气图纸 PDF 转文本可达 3M+ 字符，全部入库既慢又无意义（大量坐标数据），截断到 10 万字符

### 4.3 阶段一：文本提取 (extract_all)

#### 4.3.1 多格式提取器

```python
EXTRACTORS = {
    '.pdf':  extract_pdf,   # pymupdf4llm → pymupdf 双层回退
    '.docx': extract_docx,  # python-docx (段落 + 表格)
    '.doc':  extract_docx,  # python-docx 尝试处理老格式
    '.pptx': extract_pptx,  # python-pptx (逐 slide)
    '.ppt':  extract_pptx,  # python-pptx 尝试
    '.xlsx': extract_xlsx,  # openpyxl (逐 sheet 逐行)
    '.xls':  extract_xls,   # openpyxl 尝试，失败跳过
}
```

#### 4.3.2 PDF 提取细节

```python
def extract_pdf(filepath):
    import pymupdf4llm
    try:
        # 第一层：pymupdf4llm 将 PDF 转为 Markdown 格式
        # 优点：保留标题层级、表格结构、列表格式
        return pymupdf4llm.to_markdown(str(filepath))
    except Exception as e:
        # 第二层回退：pymupdf 纯文本提取
        # 适用于 pymupdf4llm 处理失败的特殊 PDF
        import pymupdf
        doc = pymupdf.open(str(filepath))
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        return text
```

**为什么用 pymupdf4llm 而不是直接用 pymupdf？**  
pymupdf4llm 专为 LLM 场景优化，输出 Markdown 格式：
- 保留 `# 标题` 层级 → 分块时能按章节切分
- 保留表格结构 → LLM 能理解表格数据
- 保留列表格式 → 操作步骤不会混成一段

**但 pymupdf4llm 的问题**：
- 对扫描版 PDF（纯图片）无能为力（输出空字符串）
- 对某些加密或损坏的 PDF 直接报错
- 对超大电气图纸 PDF 可能内存溢出

所以必须有 pymupdf 纯文本作为回退。

#### 4.3.3 DOCX 提取细节

```python
def extract_docx(filepath):
    from docx import Document
    doc = Document(str(filepath))
    parts = []
    # 提取所有段落文本
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    # 提取所有表格（逐行拼接单元格）
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)
```

**关键处理**：表格用 `|` 分隔符拼接，让 LLM 能理解表格结构。

#### 4.3.4 PPTX 提取细节

```python
def extract_pptx(filepath):
    from pptx import Presentation
    prs = Presentation(str(filepath))
    parts = []
    for i, slide in enumerate(prs.slides):
        slide_texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        slide_texts.append(text)
        if slide_texts:
            # 标注 slide 编号，便于定位
            parts.append(f"[Slide {i+1}]\n" + "\n".join(slide_texts))
    return "\n\n".join(parts)
```

**设计决策**：每个 slide 用 `[Slide N]` 标记，方便用户根据 RAG 结果回到原文定位。

#### 4.3.5 XLSX 提取细节

```python
def extract_xlsx(filepath):
    from openpyxl import load_workbook
    wb = load_workbook(str(filepath), read_only=True, data_only=True)
    parts = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            parts.append(f"[{sheet_name}]\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(parts)
```

**关键参数**：
- `read_only=True`：只读模式，大幅减少内存占用
- `data_only=True`：只读单元格值，不读公式（公式对 RAG 无意义）

#### 4.3.6 缓存机制

```python
# 缓存键 = 文件路径的 MD5 哈希
cache_key = hashlib.md5(dest.encode()).hexdigest()
cache_file = EXTRACTED_DIR / f"{cache_key}.json"

# 如果缓存存在且非强制模式，直接读取
if not force and cache_file.exists():
    with open(str(cache_file), 'r', encoding='utf-8') as f:
        cached = json.load(f)
    results.append(cached)
    stats["cached"] += 1
    continue
```

**为什么需要缓存？**  
- 文本提取是最耗时的步骤（442 份文档约需 20-30 分钟）
- 增量构建时，只需提取新增/修改的文档
- 缓存存储在 NTFS（`/mnt/d/`），因为是纯 JSON 读写，不涉及 SQLite

每个缓存文件包含：
```json
{
  "source": "/mnt/d/知识库wiki/变频器/G120变频器调试手册.pdf",
  "filename": "G120变频器调试手册.pdf",
  "category": "变频器",
  "subcategory": "西门子G120",
  "file_type": ".pdf",
  "size": 2456789,
  "text": "（提取的全文文本）"
}
```

### 4.4 阶段二：文本分块 (chunk_documents)

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", "；", " ", ""],
)
```

**分隔符优先级设计**：
1. `\n\n` — 段落分隔（最优先，保持完整段落）
2. `\n` — 行分隔（次优先）
3. `。` — 中文句号（中文文档的自然断句）
4. `；` — 中文分号（次级断句）
5. ` ` — 空格（英文单词边界）
6. `""` — 最后手段，硬切字符

**为什么加入中文标点？**  
默认的 RecursiveCharacterTextSplitter 只有英文分隔符（`\n\n`, `\n`, ` `, `""`），对中文文档会在汉字中间硬切，导致句子不完整。加入 `。` 和 `；` 后，切分点会落在句子边界上。

**分块 ID 生成**：
```python
chunk_id = f"{hashlib.md5(doc['source'].encode()).hexdigest()}_{chunk_index}"
```
格式为 `文件路径MD5_块序号`，保证全局唯一且可追溯源文件。

**每个 chunk 的 metadata**：
```python
{
    "source": "文件完整路径",
    "filename": "文件名",
    "category": "大类",
    "subcategory": "子类",
    "file_type": ".pdf",
    "chunk_index": 3,        # 当前块在文档中的序号
    "total_chunks": 28,      # 文档总块数
}
```

### 4.5 阶段三：向量嵌入与入库 (build_vectordb)

```python
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# 嵌入函数
ef = SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-base-zh-v1.5",
    device="cpu",              # 强制 CPU（CUDA 不兼容）
    trust_remote_code=False,
)

# ChromaDB 持久化客户端
client = chromadb.PersistentClient(path="/home/hp/rag_chromadb")
collection = client.get_or_create_collection(
    name="wiki_docs",
    embedding_function=ef,
    metadata={"hnsw:space": "cosine"},  # 余弦相似度
)

# 批量入库
batch_size = 256
for start in range(0, total, batch_size):
    batch = chunks[start:start+batch_size]
    collection.add(
        ids=[c["id"] for c in batch],
        documents=[c["text"] for c in batch],
        metadatas=[c["metadata"] for c in batch],
    )
```

**嵌入模型选择依据**：

| 模型 | 维度 | 中文能力 | 大小 | 选择原因 |
|------|------|----------|------|----------|
| bge-base-zh-v1.5 | 768 | 优秀 | ~400MB | **最终选择**。中文检索 SOTA，社区活跃 |
| bge-large-zh-v1.5 | 1024 | 最佳 | ~1.2GB | CPU 推理太慢，内存占用大 |
| bge-small-zh-v1.5 | 512 | 良好 | ~90MB | 质量牺牲太多 |
| text-embedding-ada-002 | 1536 | 一般 | 云端 | 需 OpenAI API，中文不如 bge |

**为什么选 cosine 而不是 L2/IP？**  
cosine 相似度对文本长度不敏感。同一概念在短句和长段落中的余弦相似度接近，但 L2 距离会因文本长度差异而失真。

**batch_size=256 的选择**：
- 太小（如 32）：API 调用次数多，总耗时长
- 太大（如 1024）：单批次内存峰值高，在 CPU 上可能 OOM
- 256 是实测的性能-内存平衡点

### 4.6 阶段四：知识点归档 (generate_knowledge_points)

按分类维度统计文档信息，提取高频关键词：

```python
def extract_keywords(text, top_n=20):
    # 简单的中文词频统计
    words = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]{2,}', text)
    words = [w for w in words if w not in stop_words and len(w) >= 2]
    counter = Counter(words)
    return counter.most_common(top_n)
```

输出两个文件：
- `knowledge_points.json`：结构化数据，含每个分类的文档数、文本量、关键词、示例文件
- `knowledge_points.md`：Markdown 可读版本

**为什么不用 jieba 分词？**  
工业自动化文档中大量专有名词（如 "SICAR"、"G120"、"FB功能块"），jieba 词典中没有这些词。简单的正则匹配 `[\u4e00-\u9fff]{2,}` 反而更稳定——不会误分词，且能正确提取英文技术术语。

### 4.7 命令行用法

```bash
# 全流程构建
CUDA_VISIBLE_DEVICES="" python3 rag_builder.py build

# 仅提取文本（用于调试）
CUDA_VISIBLE_DEVICES="" python3 rag_builder.py extract

# 命令行查询
CUDA_VISIBLE_DEVICES="" python3 rag_builder.py query "G120变频器调试步骤"

# 查看统计信息
CUDA_VISIBLE_DEVICES="" python3 rag_builder.py stats
```

**query 输出示例**：
```
查询: "G120变频器调试步骤"
返回 5 条结果:

============================================================
[1] 相关度: 0.8234
    文件: G120变频器调试手册.pdf
    分类: 变频器/西门子G120
    块:   12/28
    路径: /mnt/d/知识库wiki/变频器/西门子G120/G120变频器调试手册.pdf
────────────────────────────────────────────────────────────
    调试步骤：1. 接通电源，等待变频器完成初始化...
```

---

## 五、智能问答 Web UI

### 5.1 脚本：`/home/hp/rag_web.py`

基于 Gradio 的 Web 问答界面，核心特性：
- 三通道 LLM 容灾
- 流式输出
- 可调检索参数
- 通道健康监控

### 5.2 三通道容灾架构

```python
MODEL_CHANNELS = [
    {
        "id": "mimo",
        "name": "MiMo-V2-Flash",
        "model_id": "xiaomi/mimo-v2-flash",
        "api_base": "http://model.mify.ai.srv/v1",   # 小米内部 API
        "api_key": "sk-xxx",
        "timeout": 60,
    },
    {
        "id": "qwen-cloud",
        "name": "Qwen-Plus",
        "model_id": "tongyi/qwen-plus",
        "api_base": "http://model.mify.ai.srv/v1",   # 同一平台
        "api_key": "sk-xxx",
        "timeout": 60,
    },
    {
        "id": "qwen-local",
        "name": "Qwen2.5-3B (本地)",
        "model_id": "qwen2.5:3b",
        "api_base": "http://localhost:11434/v1",       # Ollama
        "api_key": "ollama",
        "timeout": 90,
    },
]
```

**为什么用 OpenAI SDK 调用所有模型？**  
小米内部 API 平台 (`model.mify.ai.srv`) 和 Ollama 都兼容 OpenAI API 格式。使用统一的 `openai.OpenAI` 客户端，三个通道的调用代码完全一致，只是 base_url 和 model_id 不同。这大大简化了容灾逻辑。

### 5.3 ChannelManager — 通道健康管理

```python
class ChannelManager:
    def __init__(self, channels):
        self.channels = list(channels)
        self.health = {}  # channel_id → {alive, last_check, error, latency}
        self._lock = threading.Lock()
    
    def _probe(self, ch):
        """快速探测：发一个 'hi'，看是否有响应"""
        client = OpenAI(base_url=ch["api_base"], api_key=ch["api_key"], timeout=15)
        resp = client.chat.completions.create(
            model=ch["model_id"],
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
            timeout=15,
        )
        return True, "", latency
    
    def check_all(self):
        """并行探测所有通道（多线程）"""
        threads = []
        for ch in self.channels:
            t = threading.Thread(target=self.check_health, args=(ch["id"],))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=20)
    
    def get_ordered_channels(self, preferred=None):
        """获取按优先级排序的可用通道"""
        # 跳过已知不可用且缓存未过期的通道
        # 如果全被过滤，返回全部（给恢复机会）
```

**健康检查策略**：
- 启动时并行检查所有通道
- 运行时缓存检查结果，TTL = 120 秒
- 通道失败后标记为不可用，120 秒后重新检测（给恢复机会）

### 5.4 容灾生成流程

```python
def generate_with_failover(query, chunks, preferred, temperature):
    """逐通道尝试，失败自动降级"""
    ordered = channel_mgr.get_ordered_channels(preferred)
    
    for ch in ordered:
        try:
            response = client.chat.completions.create(
                model=ch["model_id"],
                messages=messages,
                stream=True,        # 流式输出
            )
            for part in response:
                yield (delta.content, f"通道: {ch_name}")
            
            if got_content:
                channel_mgr.mark(ch["id"], True)
                return  # 成功，不再尝试下一通道
        except Exception:
            channel_mgr.mark(ch["id"], False, error=err)
            yield ("", f"{ch_name} 失败，切换下一通道...")
    
    # 全部失败 → 降级为纯检索模式
    yield (format_retrieval_only(chunks), "已降级: 纯检索模式")
```

**四级降级策略**：
1. MiMo-Flash 成功 → 返回（最优路径，~4s）
2. MiMo 失败 → Qwen-Plus 尝试（~2s）
3. Qwen 也失败 → Qwen-Local/Ollama 尝试（~25s）
4. 全部失败 → 返回原始检索片段 + 错误提示

### 5.5 System Prompt 设计

```python
SYSTEM_PROMPT = """你是工业自动化技术文档助手。根据检索到的文档片段回答用户问题。
要求：
1. 综合多个文档片段进行跨文档总结
2. 用【文件名】格式引用来源
3. 条理清晰，必要时使用列表或表格
4. 如果检索内容不足以回答，明确说明并建议搜索方向"""
```

**为什么强调"跨文档总结"？**  
工业文档的知识往往分散在多个文件中。比如"G120 调试步骤"可能在调试手册里，而"G120 参数说明"在另一份参数手册里。用户问"G120 怎么调试"时，需要 LLM 综合多个检索结果。

**为什么要求引用来源？**  
工业场景对信息准确性要求极高。引用来源让用户能回到原文核实，避免 LLM 幻觉造成的风险。

### 5.6 Gradio UI 布局

```
┌─────────────────────────────┬───────────────────────┐
│                             │                       │
│        对话窗口              │   模型通道选择         │
│        (Chatbot)            │   ○ 自动 (智能切换)    │
│        height=500           │   ○ MiMo-Flash (快速)  │
│                             │   ○ Qwen (云端)        │
│                             │   ○ Qwen (本地Ollama)  │
│                             │                       │
│─────────────────────────────│   检索参数             │
│  [输入问题...]    [发送]     │   top_k: [===8===]    │
│                             │   温度:  [=0.3=====]   │
│                             │                       │
│                             │   引用来源             │
│                             │   (查询后显示)         │
│                             │                       │
│                             │   通道状态表           │
│                             │   [刷新健康检查]       │
├─────────────────────────────┴───────────────────────┤
│  [清空对话]                                          │
└─────────────────────────────────────────────────────┘
```

---

## 六、一键启动脚本

### 6.1 脚本：`/home/hp/start_rag.sh`

```bash
#!/bin/bash
set -e

export OLLAMA_MODELS="/mnt/d/ollama/models"
export OLLAMA_HOST="0.0.0.0:11434"
export PATH="/home/hp/.local/bin:$PATH"
export CUDA_VISIBLE_DEVICES=""    # 强制 CPU

# 1. 启动 Ollama（如果未运行）
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    sleep 3
fi

# 2. 启动 RAG Web UI（如果未运行）
if ! curl -s http://localhost:7860/ > /dev/null 2>&1; then
    source /home/hp/mkdocs-env/bin/activate
    PYTHONUNBUFFERED=1 nohup python3 /home/hp/rag_web.py --port 7860 > /tmp/rag_web.log 2>&1 &
    # 等待最多 30 秒
    for i in $(seq 1 30); do
        curl -s http://localhost:7860/ > /dev/null 2>&1 && break
        sleep 1
    done
fi
```

**设计要点**：
- `set -e`：任何命令失败立即退出
- 幂等性：用 curl 检测服务是否已在运行，不会重复启动
- `CUDA_VISIBLE_DEVICES=""`：全局强制 CPU（避免 CUDA 错误）
- `PYTHONUNBUFFERED=1`：Python 输出不缓冲，日志实时写入
- 等待循环：最多等 30 秒让服务启动，避免无限等待

---

## 七、MkDocs 文档站

### 7.1 脚本：`/home/hp/generate_mkdocs.py`

为分类后的文档生成 MkDocs 静态站点页面，提供浏览式访问。

```bash
# 生成站点
python3 generate_mkdocs.py

# 启动预览
cd /mnt/d/知识库wiki && mkdocs serve
# 访问: http://localhost:8000
```

**与 RAG 的关系**：MkDocs 提供"浏览"能力（按目录翻阅），RAG 提供"搜索"能力（自然语言查询）。两者互补。

---

## 八、企业微信接入方案

### 8.1 方案背景

RAG 系统已通过 Web UI 可用，但实际使用中：
- 用户需要打开浏览器 → 输入 URL → 才能查询
- 希望在日常沟通工具（企业微信）中直接查询
- 通过 `/查` 命令触发，降低使用门槛

### 8.2 技术方案选型

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| WeChatFerry (hook桌面微信) | 个人微信可用 | 不合规，有封号风险 | 否 |
| Wechaty (puppet协议) | 跨平台 | 免费puppet不稳定，付费~200元/月 | 否 |
| itchat-uos (Web协议) | 纯Python | 大部分账号已封禁Web登录 | 否 |
| **企业微信自建应用** | **官方API，稳定合规** | **需管理员权限** | **选择** |

### 8.3 架构设计

```
用户在企业微信发送: /查 G120变频器调试步骤
       │
       ▼
企业微信服务器 (Tencent)
       │ POST 加密XML
       ▼
FastAPI 回调端点 (wecom_bot.py :8001/callback)
       │
       ├── [1] 解密消息 (wecom_crypto.py, AES-256-CBC)
       ├── [2] 验证签名 (SHA1)
       ├── [3] 解析命令 (/查, /状态, /帮助)
       ├── [4] 立即返回 "success" (≤5秒限制)
       │
       └── [后台线程]
            ├── [5] RAG 检索 (rag_core.retrieve)
            ├── [6] LLM 生成 (rag_core.generate_answer, 三通道容灾)
            ├── [7] 截断到 2000 字节 (企业微信限制 2048)
            └── [8] 主动推送回复 (qyapi.weixin.qq.com/message/send)
                    │
                    ▼
              用户收到答案
```

**关键设计决策：异步主动回复**

企业微信要求回调端点在 **5 秒内** 响应。但 RAG 查询（检索 + LLM 生成）需要 5-30 秒。因此：
- 回调接口立即返回 `"success"`
- 实际查询在 `ThreadPoolExecutor` 后台线程中执行
- 结果通过企业微信 `message/send` API 主动推送

### 8.4 新增文件说明

#### 8.4.1 `rag_core.py` — 共享 RAG 核心模块

从 `rag_web.py` 中提取所有非 UI 逻辑，形成可复用模块：

```python
# rag_core.py 导出的接口
get_collection()           # 获取 ChromaDB collection（懒加载）
retrieve(query, top_k)     # 向量检索
format_context(chunks)     # 格式化检索结果为 LLM 上下文
format_sources(chunks)     # 格式化引用来源
generate_with_failover()   # 流式生成（Gradio 用）
generate_answer()          # 非流式生成（企业微信用）—— 新增
channel_mgr               # 通道管理器单例
MODEL_CHANNELS             # 通道配置
```

**新增的 `generate_answer()`**：
```python
def generate_answer(query, chunks, preferred="auto", temperature=0.3):
    """非流式封装，收集全部 token 返回完整字符串"""
    answer = ""
    last_status = ""
    for token, status in generate_with_failover(query, chunks, preferred, temperature):
        answer += token
        last_status = status
    return answer, last_status
```

#### 8.4.2 `wecom_crypto.py` — 企业微信消息加解密

实现 WXBizMsgCrypt 协议（腾讯官方 SDK 是 Python 2，需要自行实现 Python 3 版本）。

**加解密流程**：
```
加密:
  明文 → 16字节随机数 + 4字节消息长度(网络字节序) + 明文 + CorpID
       → PKCS#7 填充 (block_size=32)
       → AES-256-CBC 加密 (key=base64decode(AESKey+"="), IV=key[:16])
       → Base64 编码
       → SHA1签名 (sort([token, timestamp, nonce, encrypted]))
       → 组装 XML

解密 (反向):
  XML → 提取 Encrypt 字段
      → Base64 解码
      → AES-256-CBC 解密
      → 去除 PKCS#7 填充
      → 解析: 跳过16字节随机数 → 读4字节长度 → 提取明文 → 验证 CorpID
```

**依赖**: `pycryptodome`（需新安装）

#### 8.4.3 `wecom_config.yaml` — 配置文件

```yaml
wecom:
  corpid: ""              # 企业ID (我的企业 → 企业信息)
  corpsecret: ""          # 应用Secret
  agentid: 0              # 应用AgentId
  token: ""               # 回调Token
  encoding_aes_key: ""    # 回调EncodingAESKey

server:
  host: "0.0.0.0"
  port: 8001

rag:
  top_k: 8
  temperature: 0.3
  preferred_channel: "auto"
  max_reply_bytes: 2000   # 留 48 字节余量（限制 2048）

commands:
  query_prefix: "/查"
  status_cmd: "/状态"
  help_cmd: "/帮助"
```

#### 8.4.4 `wecom_bot.py` — FastAPI 主程序

核心组件：

| 组件 | 功能 |
|------|------|
| `TokenManager` | access_token 自动刷新缓存（7200s 有效期，提前 5 分钟刷新） |
| `MsgDeduplicator` | 基于 MsgId 的消息去重（防止企业微信重试导致重复处理） |
| `truncate_utf8()` | UTF-8 安全截断（不在多字节字符中间切断） |
| `GET /callback` | 企业微信 URL 验证（首次配置时触发） |
| `POST /callback` | 接收加密消息 → 解密 → 路由命令 → 后台处理 |
| `GET /health` | 健康检查端点 |

**命令路由**：
```
/查 <关键词>  → 后台线程执行 RAG 查询，推送结果
/状态         → 查看 LLM 通道 + 向量库状态
/帮助         → 显示使用说明
其他          → 返回帮助文本
```

### 8.5 企业微信管理后台配置步骤

1. **获取企业ID**：登录 `work.weixin.qq.com` → "我的企业" → 页面底部 "企业ID"
2. **创建自建应用**："应用管理" → "自建" → "创建应用"
   - 应用名称：知识库助手
   - 可见范围：选择需要使用的部门/人员
3. **记录 AgentId 和 Secret**：应用详情页面可见
4. **配置消息回调**："接收消息" → "设置API接收"
   - URL：`https://<你的域名或ngrok地址>/callback`
   - Token：点击"随机获取"
   - EncodingAESKey：点击"随机获取"
   - **注意**：点保存时企业微信会发送 GET 验证请求，此时 `wecom_bot.py` 必须已在运行
5. **填写配置文件**：将上述信息填入 `wecom_config.yaml`

### 8.6 网络隧道方案

企业微信回调要求 HTTPS 可达。WSL2 本地服务无公网 IP，需要隧道：

**开发阶段：ngrok**
```bash
# 安装
snap install ngrok   # 或从 ngrok.com 下载

# 启动隧道
ngrok http 8001
# 输出示例: https://abc123.ngrok-free.app → http://localhost:8001

# 将 https://abc123.ngrok-free.app/callback 填入企业微信回调 URL
```

**生产阶段选项**：
- `ngrok` 付费版（固定域名）
- `frp` 反向代理（自建服务器）
- `cloudflared`（Cloudflare 免费隧道）
- 公司内网 nginx + 证书（如果企业微信服务器能直达）

---

## 九、踩坑记录 — 逐条细节复盘

### 坑 1：CUDA 驱动版本不兼容

**发现过程**：  
首次运行 `rag_builder.py build` 时，PyTorch 尝试使用 GPU，报错：
```
RuntimeError: CUDA error: no kernel image is available for execution on the device
CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.
```

**排查过程**：
```bash
# 检查 CUDA 驱动版本
nvidia-smi
# 输出: CUDA Version: 12.0 (driver 12080)

# 检查 PyTorch 编译时的 CUDA 版本
python3 -c "import torch; print(torch.version.cuda)"
# 输出: 13.0
```

**根因**：WSL2 的 CUDA 驱动版本 (12080) 低于 PyTorch pip 包编译使用的 CUDA 版本 (13.0)。PyTorch 的 CUDA 内核无法在旧驱动上运行。

**解决方案**：
```bash
# 方案一（选择）：强制 CPU 推理
export CUDA_VISIBLE_DEVICES=""

# 方案二（未采用）：安装 PyTorch CPU-only 版本
# pip install torch --index-url https://download.pytorch.org/whl/cpu

# 方案三（未采用）：升级 Windows 上的 NVIDIA 驱动
# 风险：可能影响其他 CUDA 应用
```

**最终处理**：所有运行命令都带 `CUDA_VISIBLE_DEVICES=""`，在 `start_rag.sh` 中也全局设置。

**教训**：WSL2 的 CUDA 支持依赖宿主机 Windows 上的 NVIDIA 驱动版本。不能假设 GPU 可用——特别是 pip 安装的 PyTorch 默认编译最新 CUDA，而驱动可能落后几个版本。

---

### 坑 2：ChromaDB 在 NTFS 上 SQLite 错误

**发现过程**：  
最初将 ChromaDB 数据目录设在 `/mnt/d/知识库wiki/rag_data/chromadb/`（NTFS 文件系统），构建向量库时在第 3000 条左右报错：
```
sqlite3.OperationalError: disk I/O error
```
或：
```
sqlite3.OperationalError: database disk image is malformed
```

**排查过程**：
1. 重新运行 → 同样位置报错
2. 检查磁盘空间 → 充足
3. 检查文件权限 → 正常
4. Google 搜索 "WSL2 NTFS SQLite error" → 发现大量类似报告

**根因**：WSL2 通过 9P 文件系统协议访问 Windows NTFS 分区。SQLite 依赖的文件锁（`fcntl` 锁）在 9P 上行为不一致。具体表现：
- SQLite WAL（Write-Ahead Logging）模式在 9P 上不可靠
- 并发写入时锁竞争导致数据损坏
- ChromaDB 内部的 compaction（压缩）操作触发 SQLite 并发写入

**解决方案**：
```python
# 将 ChromaDB 数据目录移到 Linux 原生文件系统
# 改前:
CHROMA_DIR = Path("/mnt/d/知识库wiki/rag_data/chromadb/")
# 改后:
CHROMA_DIR = Path("/home/hp/rag_chromadb/")
```

**验证**：移动后重新构建，22,181 条向量顺利入库，再无 SQLite 错误。

**教训**：在 WSL2 中，所有使用 SQLite 的应用（ChromaDB、Django SQLite backend 等）的数据文件必须放在 Linux 原生分区（`/home/`、`/tmp/` 等），绝不能放在 `/mnt/` 下的 Windows 分区。

**额外发现**：提取文本缓存（纯 JSON 读写）放在 NTFS 上完全没问题，因为 JSON 文件是原子写入，不涉及文件锁。

---

### 坑 3：大文件文本提取内存爆炸 & 分块数量失控

**发现过程**：  
构建过程中发现某些电气图纸 PDF 的提取极其缓慢，且生成了数万个 chunks。检查发现：
```
  [38/442] 电气原理图_总装.pdf ... 3,241,567 chars
```
一个 PDF 提取出 324 万字符！按 800 字符/块计算，会产生 ~4000 个 chunks。

**根因**：电气图纸 PDF 的本质是矢量图导出，内含大量坐标数据、线段定义、图层信息。pymupdf4llm 将这些都转成了文本。这些坐标数据对 RAG 检索毫无意义，但占据了巨大空间。

**解决方案**：
```python
MAX_TEXT_PER_DOC = 100000  # 10 万字符上限

# 在分块时截断
if len(text) > MAX_TEXT_PER_DOC:
    text = text[:MAX_TEXT_PER_DOC]
```

**为什么选 10 万字符？**
- 99% 的正常文档（技术手册、操作指南）文本量在 1 万 ~ 5 万字符
- 10 万字符足以覆盖最长的正常文档
- 电气图纸的有用文本（标题栏、注释）通常在前几万字符内
- 截断后单文档最多产生 ~125 个 chunks，可接受

**教训**：工业文档格式复杂，必须对提取文本长度做防御性截断。否则一个异常文件就能让整个构建过程变慢 10 倍。

---

### 坑 4：pymupdf4llm 对部分 PDF 失败

**发现过程**：  
构建过程中出现多条警告：
```
  [WARN] pymupdf4llm failed for /mnt/d/.../某文档.pdf: 
  RuntimeError: cannot open broken document
```

**受影响的 PDF 类型**：
1. **扫描版 PDF**：纯图片页面，没有文本层 → pymupdf4llm 输出空字符串（不算报错，但内容为空）
2. **加密 PDF**：设置了打开密码或编辑限制
3. **损坏的 PDF**：文件头或交叉引用表损坏
4. **DWG 转 PDF**：AutoCAD 导出的特殊格式，部分元数据不标准

**解决方案**：双层回退机制
```python
def extract_pdf(filepath):
    try:
        return pymupdf4llm.to_markdown(str(filepath))  # 第一层
    except Exception:
        try:
            doc = pymupdf.open(str(filepath))           # 第二层回退
            text = "".join(page.get_text() + "\n" for page in doc)
            doc.close()
            return text
        except Exception:
            return ""                                    # 最终放弃
```

**统计结果**：442 份文档中，约 15 份触发了回退，约 8 份提取为空（扫描版）。

**教训**：文本提取必须有 fallback 链。pymupdf4llm 在大多数情况下效果最好，但不能假设它能处理所有 PDF。对于完全无法提取的文件，记录日志但不中断流程。

---

### 坑 5：.xls 老旧格式不兼容

**发现过程**：  
部分早期的 Excel 文件使用 `.xls` 格式（Excel 97-2003 二进制格式），openpyxl 无法打开：
```
openpyxl.utils.exceptions.InvalidFileException: 
File is not a zip file
```

**根因**：openpyxl 只支持 `.xlsx`（Office Open XML，基于 ZIP 的 XML 格式）。`.xls` 是完全不同的二进制格式（BIFF8），需要 `xlrd` 库。

**解决方案**：
```python
def extract_xls(filepath):
    try:
        return extract_xlsx(filepath)  # 尝试用 openpyxl
    except Exception:
        print(f"  [WARN] .xls not supported, skipping: {filepath}")
        return ""
```

**为什么不安装 xlrd？**
- .xls 文件在 442 份文档中只有 3-4 份
- xlrd 新版已移除 .xls 支持（安全原因），需要安装旧版 xlrd==1.2.0
- 引入旧版 xlrd 有安全风险
- 投入产出比太低

**教训**：工业现场文档格式可能非常老旧。完美支持所有格式的成本很高，需要根据文件数量做取舍。

---

### 坑 6：Ollama 模型存储路径

**发现过程**：  
`ollama pull qwen2.5:3b` 时系统盘（WSL2 的虚拟磁盘）空间不足：
```
Error: write /home/hp/.ollama/models/...: no space left on device
```

**根因**：Ollama 默认下载模型到 `~/.ollama/models/`，即 WSL2 的虚拟磁盘。WSL2 默认虚拟磁盘大小有限（通常 256GB），且被其他内容占用。

**解决方案**：
```bash
# 设置环境变量，将模型存储到 D 盘
export OLLAMA_MODELS="/mnt/d/ollama/models"

# 在 start_rag.sh 中固化
export OLLAMA_MODELS="/mnt/d/ollama/models"
```

**教训**：大模型文件（qwen2.5:3b 约 2GB）需要提前规划存储位置。WSL2 环境尤其要注意，虚拟磁盘空间有限。

---

### 坑 7：LLM 单点故障

**发现过程**：  
最初只配置了小米内部 API (`model.mify.ai.srv`) 作为 LLM 通道。某天平台维护，整个问答系统完全不可用。

**解决过程**：
1. 先加了 Qwen-Plus 作为备通道（同一平台不同模型）→ 但平台维护时全挂
2. 再加了本地 Ollama 作为兜底 → 网络完全断开时仍可用
3. 最后加了纯检索降级 → LLM 全部不可用时至少返回原文片段

**最终架构**：
```
MiMo-Flash (云端, 快) → Qwen-Plus (云端, 稳) → Qwen2.5:3b (本地, 慢) → 纯检索 (无LLM)
```

**ChannelManager 的健康检查机制**：
- 启动时并行探测所有通道
- 运行时缓存状态 120 秒
- 失败后标记不可用，下次请求跳过
- 120 秒后重新探测（给恢复机会）
- 如果所有通道都标记为不可用，重置全部（最后的恢复手段）

**教训**：生产级 RAG 系统必须有 LLM 容灾。至少需要一个本地模型作为兜底——即使质量差一些，也比"完全不可用"好一万倍。

---

### 坑 8：中文分块效果差

**发现过程**：  
早期使用默认的 RecursiveCharacterTextSplitter（只有英文分隔符），检索结果中经常出现句子从中间被切断的情况：
```
...变频器的调试步骤如下：1. 接通电源，等待初始化完成 2. 设
───────────── 这里被切断了 ──────────────────
置参数 P1080 为适当值...
```

**根因**：默认分隔符列表 `["\n\n", "\n", " ", ""]` 对中文不友好。中文文档中句子之间没有空格分隔，当段落长度超过 chunk_size 时，会在汉字中间硬切。

**解决方案**：
```python
separators=["\n\n", "\n", "。", "；", " ", ""]
```
在 `\n` 和 ` ` 之间插入中文标点 `。` 和 `；`，让切分点落在句子边界。

**效果对比**：

切分前（默认分隔符）：
```
chunk 1: ...变频器的调试步骤如下：1. 接通电源，等待初始化完成 2. 设
chunk 2: 置参数 P1080 为适当值...
```

切分后（加中文标点）：
```
chunk 1: ...变频器的调试步骤如下：1. 接通电源，等待初始化完成。
chunk 2: 2. 设置参数 P1080 为适当值...
```

**教训**：中文 NLP 场景的文本处理不能直接套用英文工具的默认配置。分块、分词、停用词都需要专门适配。

---

### 坑 9：sentence-transformers 首次加载极慢

**发现过程**：  
`rag_web.py` 首次启动时，加载嵌入模型耗时约 30-40 秒，期间 Web UI 无法响应。

**根因**：`SentenceTransformerEmbeddingFunction` 在首次调用时才加载模型到内存。模型加载包括：
1. 从磁盘读取 ~400MB 模型文件
2. 初始化 PyTorch 运行时
3. 加载模型权重到 CPU 内存

**解决方案**：
```python
# 在 startup 时就预加载
def main():
    print("正在加载向量库...")
    get_collection()  # 这会触发嵌入模型加载
    
    # 然后再启动 Gradio
    app = build_ui()
    app.launch(...)
```

通过在启动流程中提前调用 `get_collection()`，确保模型在用户访问前就已加载。

**额外优化**：使用全局变量 `_collection` 缓存 collection 对象，避免每次查询都重新连接 ChromaDB：
```python
_collection = None

def get_collection():
    global _collection
    if _collection is not None:
        return _collection
    # ... 初始化逻辑 ...
    _collection = client.get_collection(...)
    return _collection
```

---

### 坑 10：Gradio 流式输出与 LLM 超时的冲突

**发现过程**：  
当 MiMo 通道超时（60秒无响应），切换到 Qwen 时，Gradio 的 chatbot 界面会显示一段空白，用户以为系统卡死了。

**根因**：`generate_with_failover()` 在通道切换期间没有向前端发送任何内容。

**解决方案**：在通道切换时发送状态提示：
```python
for ch in ordered:
    yield ("", f"连接 {ch_name}...")     # 连接提示
    try:
        # ... 尝试连接和生成 ...
    except Exception:
        yield ("", f"{ch_name} 失败，切换下一通道...")  # 切换提示
```

通过 yield 空 token + 状态消息，让 UI 实时显示当前状态，用户知道系统在工作。

---

### 坑 11：企业微信消息 2048 字节限制

**发现过程**：  
企业微信 text 消息类型限制 2048 字节。RAG 的回答（含引用来源）经常超过这个限制，导致发送失败。

**关键细节**：是 **2048 字节**，不是 **2048 字符**。一个中文字符在 UTF-8 编码下占 3 字节，所以实际只能发送约 682 个汉字。

**解决方案**：
```python
def truncate_utf8(text, max_bytes=2000):
    """UTF-8 安全截断，不会在多字节字符中间切断"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # 预留截断提示的空间
    indicator = "\n...(内容已截断)"
    budget = max_bytes - len(indicator.encode("utf-8"))
    truncated = encoded[:budget].decode("utf-8", errors="ignore")
    return truncated + indicator
```

**为什么用 2000 而不是 2048？**  
留 48 字节余量，防止截断提示文本本身加上后超限。

---

### 坑 12：企业微信消息加解密 Python 3 兼容性

**发现过程**：  
腾讯官方提供的 WXBizMsgCrypt SDK 是 Python 2 代码：
- 使用 `print` 语句而非函数
- 使用 `Crypto.Cipher.AES`（需要 PyCrypto，已停止维护）
- 字符串/字节混用

**解决方案**：  
自行实现 Python 3 版本 `wecom_crypto.py`，使用 `pycryptodome`（PyCrypto 的活跃维护分支）。

**关键实现细节**：

1. **PKCS#7 填充的 block_size 是 32，不是 16**  
   标准 AES 的 PKCS#7 用 16 字节块，但企业微信加密协议用 **32 字节块**。这是最容易踩的坑。

2. **消息格式**：
   ```
   [16字节随机数][4字节消息长度(大端序)][消息内容][CorpID]
   ```

3. **签名验证**：
   ```python
   # 注意：是排序后拼接，不是按固定顺序
   sort_list = sorted([token, timestamp, nonce, encrypt_str])
   sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
   ```

---

## 十、项目文件清单与路径地图

```
/home/hp/                              # 主项目目录 (Linux ext4)
├── rag_builder.py                     # 向量库构建工具 (17,743 bytes)
├── rag_web.py                         # Gradio Web UI (18,094 bytes)
├── doc_classifier.py                  # 文档分类器 (21,648 bytes)
├── generate_mkdocs.py                 # MkDocs 站点生成 (11,967 bytes)
├── start_rag.sh                       # 一键启动脚本 (1,386 bytes)
├── CLAUDE.md                          # Claude Code 项目说明
│
├── rag_core.py                        # [待创建] 共享 RAG 核心模块
├── wecom_bot.py                       # [待创建] 企业微信 FastAPI 后端
├── wecom_crypto.py                    # [待创建] 企业微信消息加解密
├── wecom_config.yaml                  # [待创建] 企业微信凭证配置
│
├── rag_chromadb/                      # ChromaDB 向量数据库
│   ├── chroma.sqlite3                 # 主数据文件 (~116 MB)
│   └── 9b5f7518-.../                  # HNSW 索引文件
│
└── mkdocs-env/                        # Python 3.12 虚拟环境
    └── lib/python3.12/site-packages/  # 已安装的包


/mnt/d/知识库wiki/                      # Wiki 根目录 (Windows NTFS)
├── mkdocs.yml                         # MkDocs 配置
├── 00_目录索引/
│   └── classification_result.json     # 分类结果 (442 文档)
├── rag_data/
│   ├── extracted/                     # 提取文本缓存 (460 JSON 文件)
│   ├── knowledge_points.json          # 知识点归档 (结构化)
│   └── knowledge_points.md            # 知识点归档 (可读版)
├── PLC/                               # 分类: PLC 文档
├── 变频器/                             # 分类: 变频器文档
├── 机器人/                             # 分类: 机器人文档
├── SICAR/                             # 分类: SICAR 标准块
├── 电气图纸/                           # 分类: 电气图纸
└── .../                               # 其他分类目录


/mnt/d/ollama/                         # Ollama (Windows NTFS)
├── bin/ollama                         # Ollama 二进制
└── models/                            # 模型文件 (qwen2.5:3b ~2GB)
```

---

## 十一、快速使用手册

### 11.1 一键启动
```bash
bash /home/hp/start_rag.sh
```
自动启动 Ollama + RAG Web UI，输出访问地址。

### 11.2 手动启动
```bash
source /home/hp/mkdocs-env/bin/activate

# 启动 Ollama
OLLAMA_MODELS=/mnt/d/ollama/models OLLAMA_HOST=0.0.0.0:11434 ollama serve &

# 启动 RAG Web UI
CUDA_VISIBLE_DEVICES="" python3 /home/hp/rag_web.py --port 7860

# (可选) 启动 MkDocs 文档站
cd /mnt/d/知识库wiki && mkdocs serve
```

### 11.3 重建向量库
```bash
source /home/hp/mkdocs-env/bin/activate
CUDA_VISIBLE_DEVICES="" python3 /home/hp/rag_builder.py build
```

### 11.4 命令行查询
```bash
CUDA_VISIBLE_DEVICES="" python3 /home/hp/rag_builder.py query "G120变频器调试步骤"
CUDA_VISIBLE_DEVICES="" python3 /home/hp/rag_builder.py query "SICAR标准块FB功能块" --top_k 10
```

### 11.5 查看统计
```bash
CUDA_VISIBLE_DEVICES="" python3 /home/hp/rag_builder.py stats
```

### 11.6 服务地址

| 服务 | 地址 | 说明 |
|------|------|------|
| RAG Web UI | http://localhost:7860 | 主问答界面 |
| MkDocs 站点 | http://localhost:8000 | 文档浏览 |
| Ollama API | http://localhost:11434 | 本地 LLM |
| WeCom Bot | http://localhost:8001 | 企业微信回调 (待部署) |

### 11.7 停止服务
```bash
pkill -f ollama
pkill -f rag_web
pkill -f wecom_bot   # 企业微信 bot (待部署)
```

---

## 十二、后续规划

| 状态 | 任务 | 说明 |
|------|------|------|
| [设计完成] | 企业微信接入 | `/查` 命令查询知识库，方案已设计，待实施 |
| [待定] | 增量更新 | 新增文档自动入库，无需全量重建 |
| [待定] | 多轮对话 | 支持上下文连续提问 |
| [待定] | 权限控制 | 按部门/角色限制可查询的文档分类 |
| [待定] | OCR 集成 | 对扫描版 PDF 进行 OCR 文字识别 |
| [待定] | 混合检索 | 向量检索 + BM25 关键词检索融合，提升召回率 |

---

*文档生成时间: 2026-04-20*  
*项目维护: hp*  
*文档版本: v1.0*
