# Agent Integration Plan for JobCollection Project
你好！作为一个 Agent 初学者，在你的职位采集和通过 WebAPI 展示的项目中集成 Agent 是一个非常棒的想法。Agent (智能体) 可以帮助你把“死”的数据变成“活”的服务。

根据你目前的项架构（Spider + FastAPI + Postgres），我为你设计了一个循序渐进的 **三阶段集成方案**。

## 0. 准备工作
在开始之前，你需要准备一个大模型（LLM）的 API Key。
推荐使用 DeepSeek、OpenAI 或其他兼容 OpenAI 格式的 API，方便开发。

---

## 阶段一：智能数据清洗 Agent (Parser Agent)
**目标**：利用 Agent 强大的理解能力，把爬虫抓回来的“非结构化”数据（如大段的职位描述文本）整理成“结构化”数据。

### 现状 vs 改进
- **现状**：你的爬虫 (`boss_detail_spider.py`) 抓取了 `job_desc`，是一大段纯文本。想要按“技能”、“福利”、“学历要求”筛选很难。
- **改进**：在数据入库前（或入库后异步处理），让 Agent 阅读 `job_desc`，并提取出 JSON 格式的关键信息。

### 实施步骤
1. **定义结构**：使用 `Pydantic` 定义你想要提取的数据字段。
   ```python
   class JobAnalysisResult(BaseModel):
       skills: List[str] = Field(description="编程语言和技术栈，如 Python, Vue, Docker")
       bonus_benefits: List[str] = Field(description="福利待遇，如 年底双薪, 股票期权")
       is_remote: bool = Field(description="是否支持远程")
       summary: str = Field(description="一句话总结职位亮点")
   ```
2. **编写 Prompt**：
   > "你是一个资深猎头。请阅读下面的职位描述，提取出关键信息，并以 JSON 格式返回..."
3. **集成点**：
   - **方案 A (推荐)**：写一个独立的脚本 `process_jobs_agent.py`，从数据库读取 `is_crawl=1` 且未分析过的职位，调用 LLM 分析，然后存回数据库（需要给 Job 表增加 `analysis_result` 字段）。
   - **方案 B**：直接集成在 Spider 的 Pipeline 中（可能会拖慢爬虫速度，不推荐）。

---

## 阶段二：自然语言搜索 Agent (Search Agent)
**目标**：让用户可以像跟人说话一样找工作，而不是在一个个输入框里填表。
lk
### 现状 vs 改进
- **现状**：API (`search_service.py`) 需要确切的参数：`keyword="Python", salary_min=20000`。
- **改进**：用户输入 "帮我找北京3万以上的Python工作，最好是双休的"。Agent 自动理解意图，并将其转换为数据库查询条件。

### 实施步骤
1. **工具描述 (Function Calling)**：
   告诉 Agent 你有一个工具叫 `search_jobs`，它接受 `location`, `keyword`, `salary_min` 等参数。
2. **意图识别**：
   当用户输入一句话时，Agent 会分析这句话，并决定调用 `search_jobs` 函数。
   - 用户："北京 Python 30k"
   - Agent -> 调用 `search_jobs(city='北京', keyword='Python', salary_min=30000)`
3. **集成点**：
   - 在 `jobCollectionWebApi` 中增加一个新的接口 `POST /api/v1/agent/chat`。
   - 接收用户的 query，在后台调用 LLM 进行意图转换，然后调用现有的 `search_service.py` 获取结果，最后总结并返回给用户。

---

## 阶段三：人岗匹配 Agent (Matcher Agent)
**目标**：根据用户的简历，自动计算与职位的匹配度，并给出修改建议。

### 实施步骤
1. 用户上传简历（文本或 PDF）。
2. Agent 将简历内容与职位描述 (`description`) 进行通过对比。
3. Agent 输出：
   - **匹配分数** (0-100)
   - **匹配理由** ("你的 Python 经验符合，但缺少 Docker 实战经验")
   - **简历修改建议**

---

## 4. LangChain & LangGraph 集成方案 (Python)
既然你想学习并使用 `LangChain` 和 `LangGraph`，这非常适合本项目！

### 为什么要用它们？
- **LangChain**: 它是基础。提供了方便的 Prompt 模板管理（PromptTemplates）、输出解析器（OutputParsers，保证 LLM 吐出合法的 JSON）和模型接口（ChatModels）。
- **LangGraph**: 它是进阶。用于构建 **有状态**、**循环** 的工作流。比如：Agent 搜索一次没结果 -> 自动换个关键词再搜一次 -> 还没结果 -> 询问用户。这种复杂的逻辑用 Graph 非常清晰。

### 具体实施方案

#### A. 在“阶段一：智能解析”中使用 LangChain
直接使用 LangChain 的 **Result Parsing** 功能。
*   **核心组件**：`ChatPromptTemplate`, `PydanticOutputParser`
*   **优势**：不用自己写复杂的正则去提取 JSON，LangChain 会自动处理。

```python
# 伪代码示例
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

parser = PydanticOutputParser(pydantic_object=JobAnalysisResult)
prompt = ChatPromptTemplate.from_template(
    "请提取职位信息...\n{format_instructions}\n职位描述:\n{job_desc}"
)
chain = prompt | llm | parser
result = chain.invoke({"job_desc": text, "format_instructions": parser.get_format_instructions()})
```

#### B. 在“阶段二：搜索助手”中使用 LangGraph
搜索往往不是一次完成的，可能需要多轮对话，因此适合用 LangGraph。

*   **架构设计**：这也是最经典的 "ReAct" (Reasoning + Acting) 模式。
*   **Graph 节点 (Nodes)**:
    1.  `agent`: 负责思考。接收用户输入，决定是否调用工具。
    2.  `tools`: 负责执行。就是你的 `search_service.py`。
*   **工作流**:
    *   Start -> `agent` -> (决定调用工具) -> `tools` -> `agent` -> (生成回答) -> End
*   **集成位置**:
    *   在 `jobCollectionWebApi` 中创建一个 `agent_graph.py`。
    *   API 接口接收到请求后，直接 `graph.invoke({"messages": [HumanMessage(content=query)]})`。

```python
# 伪代码示例 webapi/agent_graph.py
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
import operator

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]

workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("action", call_tool)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("action", "agent")

app_graph = workflow.compile()
```

### 推荐学习路线
1.  先用 **LangChain** 实现阶段一的脚本（最简单，立马能跑通）。
2.  再用 **LangGraph** 实现阶段二的 API（涉及到状态管理，稍微复杂一点）。

---

## 快速启动建议

我建议你从 **阶段一（智能解析）** 或 **阶段二（搜索助手）** 开始。

如果你想立刻看到效果，我们可以先做一个简单的 **Demo 脚本**，不修改现有核心代码，只是演示 Agent 如何在这个项目中工作。

### 你需要我为你做什么？
1.  **编写 Demo**：写一个脚本，演示如何用 Agent 解析你数据库里的一条职位数据。
2.  **修改 API**：直接着手在 WebAPI 里加一个“AI 搜索”接口。
3.  **数据库集成**：帮你在 Job 表里加字段，并写好批量清洗数据的脚本。


请告诉我你想先做哪个，或者有什么不明白的地方？

## 5. 前台 AI 智能搜索完整方案 (LangGraph + Vue)

本方案旨在将首页原本的关键词搜索升级为“自然语言意图搜索”。

### 架构设计
1.  **前端 (`HomeView.vue`)**:
    *   用户输入自然语言（例如：“找杭州 15k 左右的 Python 工作”）
    *   调用新接口 `POST /api/v1/agent/search?q=...`
    *   展示结果。

2.  **后端 (`Agent Graph`)**:
    *   接收 Query。
    *   **Node 1 (Rephrase/Extract)**: 使用 LLM 分析 Query，提取结构化参数 (City, Salary, Keyword)。
    *   **Node 2 (Search)**: 调用现有的 `search_service` 执行搜索。
    *   **Node 3 (Response)**: (可选) 生成一段总结性的回答。

### 详细步骤

#### A. 后端开发 (`jobCollectionWebApi`)

1.  **定义 Graph State (`api/v1/agent/graph.py`)**:
    ```python
    class AgentState(TypedDict):
        query: str
        extracted_params: dict
        job_results: list
        final_answer: str
    ```

2.  **创建节点 (`api/v1/agent/nodes.py`)**:
    *   `extract_params_node`: Prompt 类似于 "Extract city, salary, keyword from query..."
    *   `search_tool_node`: 映射提取的参数到 `search_service.search_jobs`。

3.  **构建 API (`api/v1/endpoints/agent_controller.py`)**:
    *   `POST /search`: 接收 plain text，运行 Graph，返回 `{ answer: str, jobs: List[Job] }`。

#### B. 前端开发 (`frontend`)

1.  **修改 `HomeView.vue`**:
    *   搜索框逻辑变更：不再直接跳转 `/jobs?q=...`。
    *   而是发起异步请求到 Agent API。
    *   展示 Loading 状态（AI 思考中...）。
    *   拿到结果后，可以直接在首页展示“推荐列表”，或者带参数跳转到列表页。

### 推荐实施路径
1.  先在后端把 `agent_graph` 跑通（用单元测试或脚本测）。
2.  写 API 接口暴露出来。
3.  最后改前端 UI。
